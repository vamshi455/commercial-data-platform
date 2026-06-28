"""Silver customer master — CRM<->ERP identity resolution into ``silver.customer``.

Inputs
------
* ``bronze_crm_accounts``  -- CRM accounts (Salesforce-style 18-char Id)
* ``bronze_erp_customers`` -- ERP customers (SAP KUNNR-style numeric id)
* crosswalk JSON at ``<landing>/_crosswalk/crm_erp_crosswalk.json`` (optional
  assist emitted by the data generators that already aligns some accounts).

Output
------
``silver_customer`` (published as ``<catalog>.silver.customer``): one conformed
customer per resolved real-world company, with a stable surrogate key
``customer_sk`` and back-references to the source ids on each system.

Identity-resolution strategy
----------------------------
1. **Normalise** each side: company name -> ``normalize_name`` and email/web
   domain -> ``normalize_domain`` to build deterministic match keys.
2. **Crosswalk join (highest confidence):** if the generator-provided crosswalk
   maps a CRM account id to an ERP customer id, use that directly.
3. **Deterministic match (fallback):** otherwise match on normalised
   *name + domain*. (We require BOTH to avoid over-merging same-named companies
   in different countries.)
4. **Dedup:** within each system, collapse duplicate source rows by keeping the
   most-recently-modified record before resolution.
5. **Surrogate key:** ``customer_sk = sha2(match_key)`` so the same company maps
   to the same key on every run (idempotent, unlike monotonic ids).

Data quality (DLT expectations)
-------------------------------
* ``@dlt.expect_or_drop`` -- a customer row MUST have a non-null ``customer_sk``
  and at least one source id (CRM or ERP); rows failing this are dropped.
* ``@dlt.expect`` -- warn-only metric on having a usable ``company_name``.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F
from pyspark.sql import Window

# ---------------------------------------------------------------------------
# Inlined from src/pipelines/_common.py — serverless DLT cannot reliably IMPORT
# a .py from /Workspace files (OSError Errno 5), so the shared helpers are
# inlined here. _common.py remains the source of truth for local/test use.
# ---------------------------------------------------------------------------
from pyspark.sql import DataFrame  # noqa: F401 (inlined helper annotations)
from pyspark.sql.column import Column  # noqa: F401

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


# ---------------------------------------------------------------------------
# Deduplicated, normalised staging views (one per source system).
# These are DLT *views* (not materialised) — cheap intermediate logic.
# ---------------------------------------------------------------------------

@dlt.view(comment="CRM accounts, deduped to latest per source id, with match keys.")
def stg_crm_accounts():
    df = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_accounts")
    # Pick the latest record per CRM account id (defensive dedup). We assume a
    # last-modified column from the source; fall back to ingest time.
    mod_col = "created_date" if "created_date" in df.columns else "_ingested_at"
    w = Window.partitionBy("account_id").orderBy(F.col(mod_col).desc())
    return (
        df.withColumn("_rn", F.row_number().over(w))
          .where("_rn = 1")
          .withColumn("name_key", normalize_name("account_name"))
          # bronze_crm_accounts has no website/email column to derive a domain
          # from, so the domain match key is null for CRM accounts.
          .withColumn("domain_key", normalize_domain(F.lit(None).cast("string")))
          .select(
              F.col("account_id").alias("crm_account_id"),
              F.col("account_name").alias("crm_name"),
              "name_key", "domain_key",
              F.col("billing_country").alias("crm_country")
              if "billing_country" in df.columns else F.lit(None).alias("crm_country"),
          )
    )


@dlt.view(comment="ERP customers, deduped to latest per source id, with match keys.")
def stg_erp_customers():
    df = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_erp_customers")
    mod_col = "created_date" if "created_date" in df.columns else "_ingested_at"
    w = Window.partitionBy("customer_id").orderBy(F.col(mod_col).desc())
    domain_src = (F.col("payment_contact_email") if "payment_contact_email" in df.columns
                  else F.lit(None).cast("string"))
    return (
        df.withColumn("_rn", F.row_number().over(w))
          .where("_rn = 1")
          .withColumn("name_key", normalize_name("customer_name"))
          .withColumn("domain_key", normalize_domain(domain_src))
          .select(
              F.col("customer_id").alias("erp_customer_id"),
              F.col("customer_name").alias("erp_name"),
              "name_key", "domain_key",
              F.col("country").alias("erp_country")
              if "country" in df.columns else F.lit(None).alias("erp_country"),
          )
    )


@dlt.view(comment="Generator-provided CRM<->ERP crosswalk (account_id -> customer_id).")
def stg_crosswalk():
    """Flatten the crosswalk JSON into (crm_account_id, erp_customer_id) pairs.

    The JSON shape is ``{"accounts": {"<company_key>": {"crm_account_id": ...,
    "erp_customer_id": ...}}}``. We read it as a single multiline JSON doc and
    explode the ``accounts`` map. If the file is absent the read yields an empty
    set (the join below degrades gracefully to name+domain matching).
    """
    try:
        raw = (
            spark.read.option("multiLine", "true")  # noqa: F821
            .json(crosswalk_path())
        )
    except Exception:  # pragma: no cover - file may not exist in some envs
        # Return an empty, correctly-typed frame so downstream joins still work.
        return spark.createDataFrame(  # noqa: F821
            [], "crm_account_id string, erp_customer_id string")

    # ``accounts`` is a struct-of-structs; turn it into rows via from_json is
    # overkill here, so explode the map by selecting its fields generically.
    accounts = raw.select(F.explode(F.map_entries(F.col("accounts"))).alias("kv"))
    return accounts.select(
        F.col("kv.value.crm_account_id").alias("crm_account_id"),
        F.col("kv.value.erp_customer_id").alias("erp_customer_id"),
    ).where("crm_account_id IS NOT NULL OR erp_customer_id IS NOT NULL")


# ---------------------------------------------------------------------------
# Resolved customer master.
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.silver_customer",
    comment="Conformed customer master with CRM<->ERP identity resolution.",
    table_properties={"quality": "silver", "delta.enableChangeDataFeed": "true"},
)
# Hard expectations: drop rows we cannot key or that have no source lineage.
@dlt.expect_or_drop("has_surrogate_key", "customer_sk IS NOT NULL")
@dlt.expect_or_drop(
    "has_source_lineage",
    "crm_account_id IS NOT NULL OR erp_customer_id IS NOT NULL",
)
# Warn-only: a usable display name is desirable but not mandatory.
@dlt.expect("has_company_name", "company_name IS NOT NULL AND length(company_name) > 1")
def silver_customer():
    crm = dlt.read("stg_crm_accounts")
    erp = dlt.read("stg_erp_customers")
    xwalk = dlt.read("stg_crosswalk")

    # --- Pass 1: crosswalk join (highest confidence) -----------------------
    crm_x = crm.join(xwalk, "crm_account_id", "left")
    # Rows that matched the crosswalk to an ERP id.
    matched = (
        crm_x.where("erp_customer_id IS NOT NULL")
        .join(erp, "erp_customer_id", "left")
        .withColumn("match_method", F.lit("crosswalk"))
        # both stg_crm_accounts and stg_erp_customers carry name_key/domain_key;
        # keep the CRM side and drop the ERP duplicates so the later
        # _project select of name_key/domain_key is unambiguous.
        .drop(erp.name_key).drop(erp.domain_key)
    )

    # --- Pass 2: deterministic name+domain match for the remainder ---------
    crm_un = crm_x.where("erp_customer_id IS NULL").drop("erp_customer_id")
    name_domain = (
        crm_un.join(
            erp,
            (crm_un.name_key == erp.name_key)
            & (crm_un.domain_key == erp.domain_key)
            & crm_un.name_key.isNotNull()
            & crm_un.domain_key.isNotNull(),
            "left",
        )
        .withColumn(
            "match_method",
            F.when(F.col("erp_customer_id").isNotNull(), F.lit("name_domain"))
             .otherwise(F.lit("crm_only")),
        )
        # disambiguate the duplicated name_key/domain_key columns post-join
        .drop(erp.name_key).drop(erp.domain_key)
    )

    # ERP customers that never matched any CRM account (erp-only customers).
    matched_erp_ids = (
        matched.select("erp_customer_id")
        .union(name_domain.select("erp_customer_id"))
        .where("erp_customer_id IS NOT NULL")
        .distinct()
    )
    erp_only = (
        erp.join(matched_erp_ids, "erp_customer_id", "left_anti")
        .withColumn("crm_account_id", F.lit(None).cast("string"))
        .withColumn("crm_name", F.lit(None).cast("string"))
        .withColumn("crm_country", F.lit(None).cast("string"))
        .withColumn("match_method", F.lit("erp_only"))
    )

    # --- Union the three populations and project the conformed schema ------
    def _project(df):
        # Build a stable match_key: prefer crosswalk pairing, else name+domain,
        # else whichever single source id exists.
        match_key = F.coalesce(
            F.concat_ws("|", F.col("crm_account_id"), F.col("erp_customer_id")),
            F.concat_ws("|", F.col("name_key"), F.col("domain_key")),
            F.col("crm_account_id"),
            F.col("erp_customer_id"),
        )
        return df.select(
            surrogate_key(match_key).alias("customer_sk"),
            F.col("crm_account_id"),
            F.col("erp_customer_id"),
            F.coalesce(F.col("crm_name"), F.col("erp_name")).alias("company_name"),
            F.coalesce(F.col("crm_country"), F.col("erp_country")).alias("country"),
            F.col("name_key"),
            F.col("domain_key"),
            F.col("match_method"),
            F.current_timestamp().alias("_silver_loaded_at"),
        )

    unioned = _project(matched).unionByName(
        _project(name_domain)
    ).unionByName(_project(erp_only))

    # Final collapse: one row per customer_sk (crosswalk + name_domain could
    # both land the same company). Keep the most authoritative match_method.
    method_rank = (
        F.when(F.col("match_method") == "crosswalk", 1)
         .when(F.col("match_method") == "name_domain", 2)
         .when(F.col("match_method") == "crm_only", 3)
         .otherwise(4)
    )
    w = Window.partitionBy("customer_sk").orderBy(method_rank.asc())
    return (
        unioned.withColumn("_rank", method_rank)
        .withColumn("_rn", F.row_number().over(w))
        .where("_rn = 1")
        .drop("_rn", "_rank")
    )
