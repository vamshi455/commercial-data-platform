"""Shared helpers for every Lakeflow / Delta Live Tables (DLT) pipeline file.

Why this file exists
--------------------
A DLT pipeline is configured (in ``resources/*.yml``) with a *list of
notebooks / Python files*. At runtime DLT loads **all** of those files into a
single execution graph — so a plain ``import`` of a sibling module in the same
pipeline "just works" because the files are co-located and DLT puts the
pipeline root on ``sys.path``. That means we can centralise tiny, repeated
helpers here and import them everywhere without building a wheel or library.

Keep this module dependency-light and side-effect free: **no** ``@dlt.table``
definitions live here, only pure helpers. (If DLT discovered a table here it
would try to materialise it, which we do not want for a utilities file.)

Configuration model
--------------------
The same code is deployed to ``cdp_dev`` / ``cdp_qa`` / ``cdp_prod``. Two knobs
are read from the Spark config at runtime, both set by the DLT pipeline spec /
Databricks Asset Bundle (see ``databricks.yml`` ``var.catalog`` and
``var.landing_volume``):

  * ``cdp.catalog``       -> Unity Catalog name to publish into (default cdp_dev)
  * ``cdp.landing_path``  -> root path/Volume where raw source files land

In ``resources/*.yml`` you would wire these through the pipeline
``configuration`` block, e.g.::

    configuration:
      cdp.catalog: ${var.catalog}
      cdp.landing_path: ${var.landing_volume}

The pipeline's Unity Catalog *target* (catalog + schema) is also set in the
pipeline YAML (``catalog: ${var.catalog}`` and ``schema: ...`` / per-table
``name`` qualifiers), so DLT writes managed tables to the right place. We still
expose ``get_catalog()`` for code that needs the catalog name explicitly (e.g.
building fully-qualified read paths or SQL strings).
"""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.column import Column

# ``spark`` is injected into the global namespace by the Databricks runtime, so
# it is always available inside a DLT pipeline. We reference it lazily inside
# functions rather than importing an active session.

# ---------------------------------------------------------------------------
# Entity registries — single source of truth, reused by the Auto Loader
# factories so the ingestion files stay DRY.
# ---------------------------------------------------------------------------

CRM_ENTITIES: list[str] = [
    "accounts", "contacts", "leads", "opportunities", "opportunity_line_items",
    "quotes", "contracts", "activities", "cases", "users", "territories",
]

ERP_ENTITIES: list[str] = [
    "customers", "vendors", "products", "sales_orders", "sales_order_items",
    "billing_documents", "invoices", "payments", "purchase_orders",
    "gl_entries", "cost_centers", "profit_centers", "currency_rates",
]

REFERENCE_ENTITIES: list[str] = [
    "fiscal_calendar", "product_hierarchy", "currency_rates", "country_codes",
]


# ---------------------------------------------------------------------------
# Configuration getters
# ---------------------------------------------------------------------------

def get_catalog(default: str = "cdp_dev") -> str:
    """Return the target Unity Catalog name.

    Reads ``cdp.catalog`` from the Spark config (set by the DLT pipeline
    ``configuration`` block / bundle ``var.catalog``). Falls back to
    ``cdp_dev`` so the module is safe to import even if the key is unset.
    """
    return spark.conf.get("cdp.catalog", default)  # noqa: F821 (spark is a runtime global)


def get_landing_path(default: str = "/Volumes/cdp_dev/landing/files") -> str:
    """Return the root landing path/Volume for raw source files.

    Reads ``cdp.landing_path`` from the Spark config. The generators write to::

        <landing>/crm/<entity>/dt=YYYY-MM-DD/*.csv
        <landing>/erp/<entity>/dt=YYYY-MM-DD/*.csv
        <landing>/reference/<entity>/*.csv

    Trailing slashes are stripped so callers can safely f-string a suffix.
    """
    return spark.conf.get("cdp.landing_path", default).rstrip("/")  # noqa: F821


def landing_glob(source_system: str, entity: str) -> str:
    """Build the Auto Loader input path for one source entity.

    ``source_system`` is one of ``crm`` / ``erp`` / ``reference``. We point
    Auto Loader at the *entity* directory and let it walk the ``dt=...``
    partitions (``cloudFiles`` discovers new files under the path over time).
    """
    return f"{get_landing_path()}/{source_system}/{entity}"


def schema_location(source_system: str, entity: str) -> str:
    """Per-entity schema/checkpoint location for Auto Loader schema inference.

    Auto Loader persists the inferred schema (and tracks evolution) here. It
    lives under the landing root in a hidden ``_schemas`` folder, namespaced by
    source + entity so entities never collide.
    """
    return f"{get_landing_path()}/_schemas/{source_system}/{entity}"


# ---------------------------------------------------------------------------
# Audit columns
# ---------------------------------------------------------------------------

def with_audit_columns(df: DataFrame, batch_id: str | None = None) -> DataFrame:
    """Append the standard bronze audit columns to a DataFrame.

    Convention (see src/pipelines/bronze/README.md):
      * ``_ingested_at`` -- processing-time the row was ingested
      * ``_source_file`` -- the file the row came from (``_metadata.file_path``)
      * ``_batch_id``    -- logical batch label (defaults to ingest date)
      * ``_rescued_data`` -- Auto Loader's rescued-data column (already present
        on the streaming DataFrame when ``rescuedDataColumn`` is configured;
        we leave it as-is and only add it as NULL if missing so the bronze
        schema is uniform across entities).

    ``_metadata`` is a hidden struct column Auto Loader/Spark exposes on file
    sources; ``_metadata.file_path`` is the modern replacement for the
    deprecated ``input_file_name()``.
    """
    out = (
        df.withColumn("_ingested_at", F.current_timestamp())
          .withColumn("_source_file", F.col("_metadata.file_path"))
    )
    # batch id defaults to the ingest date (yyyy-MM-dd) when not supplied.
    if batch_id is None:
        out = out.withColumn("_batch_id", F.date_format(F.current_timestamp(), "yyyy-MM-dd"))
    else:
        out = out.withColumn("_batch_id", F.lit(batch_id))

    # Guarantee a uniform _rescued_data column even if a source had no rescues.
    if "_rescued_data" not in out.columns:
        out = out.withColumn("_rescued_data", F.lit(None).cast("string"))
    return out


# ---------------------------------------------------------------------------
# Normalisation helpers (used heavily by silver identity resolution)
# ---------------------------------------------------------------------------

# Common company-name "noise" suffixes we strip to improve deterministic match.
_LEGAL_SUFFIXES = [
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "limited", "ltd", "llc", "llp", "lp", "plc", "gmbh", "ag", "sa", "nv",
    "bv", "pty", "group", "holdings", "the",
]


def normalize_name(col: "Column | str") -> Column:
    """Return a normalised company/person name column for fuzzy-deterministic match.

    Steps: lower-case -> strip accents-ish punctuation -> collapse whitespace ->
    drop common legal suffixes -> trim. This produces a stable join key so
    "Apex Industries, Inc." and "apex industries inc" resolve to the same key.

    Accepts either a column name (str) or an existing ``Column``.
    """
    c = F.col(col) if isinstance(col, str) else col
    c = F.lower(c)
    # Remove anything that is not a letter, digit or space.
    c = F.regexp_replace(c, r"[^a-z0-9\s]", " ")
    # Drop standalone legal-suffix tokens (word-boundary match).
    for suffix in _LEGAL_SUFFIXES:
        c = F.regexp_replace(c, rf"\b{suffix}\b", " ")
    # Collapse repeated whitespace and trim.
    c = F.trim(F.regexp_replace(c, r"\s+", " "))
    return c


def normalize_domain(col: "Column | str") -> Column:
    """Extract a normalised email/web domain (lower-cased, no leading www.).

    From an email like ``a.b@apex.com`` returns ``apex.com``; from a bare
    domain it just normalises case and strips ``www.``.
    """
    c = F.col(col) if isinstance(col, str) else col
    c = F.lower(F.trim(c))
    # If it's an email, take the part after '@'.
    c = F.when(c.contains("@"), F.split(c, "@").getItem(1)).otherwise(c)
    c = F.regexp_replace(c, r"^www\.", "")
    return c


def surrogate_key(*cols: "Column | str") -> Column:
    """Deterministic surrogate-key hash from one or more business-key columns.

    Uses SHA-2(256) over a ``||``-joined, null-safe concatenation so the same
    business key always maps to the same surrogate across runs (stable, unlike
    monotonically_increasing_id()).
    """
    resolved = [F.col(c) if isinstance(c, str) else c for c in cols]
    coalesced = [F.coalesce(c.cast("string"), F.lit("")) for c in resolved]
    return F.sha2(F.concat_ws("||", *coalesced), 256)


def crosswalk_path() -> str:
    """Path to the CRM<->ERP crosswalk JSON emitted by the data generators.

    The generators persist a shared identity map at
    ``<landing>/_crosswalk/crm_erp_crosswalk.json`` (see data_gen/common.py).
    Silver identity resolution reads it as a deterministic match assist.
    """
    return f"{get_landing_path()}/_crosswalk/crm_erp_crosswalk.json"
