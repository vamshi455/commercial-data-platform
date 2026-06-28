"""Silver conformance for contracts and sales orders.

Inputs
------
* ``bronze_crm_contracts``     -- CRM contract records
* ``bronze_crm_opportunities`` -- CRM opportunities (we treat ``Closed Won`` as
  bookings that may not yet have a formal contract row)
* ``bronze_erp_sales_orders``  -- ERP sales order headers
* ``silver_customer``          -- to attach the conformed ``customer_sk``

Outputs
-------
* ``silver_contract``     -- conformed contracts (from CRM contracts UNION
  closed-won opportunities that lack a contract), keyed to ``customer_sk``.
* ``silver_sales_order``  -- conformed ERP sales orders, keyed to ``customer_sk``.

Why union opportunities into contracts?
---------------------------------------
In this commercial model, a *booking* is recognised when an opportunity is
Closed Won; a formal ``contract`` row may follow later (or never, for
transactional business). To get a complete "committed revenue" picture we
conform both into ``silver_contract`` with a ``contract_source`` discriminator
(``crm_contract`` vs ``won_opportunity``).

Data quality
------------
* contracts: drop rows missing a contract key or amount; warn on missing dates.
* sales_orders: drop rows missing the order id; expect a positive net amount and
  a sane order date (not in the far future).
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F

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
# silver_contract
# ---------------------------------------------------------------------------

@dlt.view(comment="CRM contracts normalised + keyed to silver customer.")
def stg_crm_contracts():
    c = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_contracts")
    cust = dlt.read("silver.silver_customer").select("customer_sk", "crm_account_id")
    return (
        c.join(cust, c.account_id == cust.crm_account_id, "left")
         .select(
             F.col("contract_id"),
             F.lit("crm_contract").alias("contract_source"),
             F.col("customer_sk"),
             F.col("account_id").alias("crm_account_id"),
             F.col("contract_number") if "contract_number" in c.columns
             else F.col("contract_id").alias("contract_number"),
             F.col("status").alias("contract_status") if "status" in c.columns
             else F.lit(None).cast("string").alias("contract_status"),
             F.to_date("start_date").alias("start_date") if "start_date" in c.columns
             else F.lit(None).cast("date").alias("start_date"),
             F.to_date("end_date").alias("end_date") if "end_date" in c.columns
             else F.lit(None).cast("date").alias("end_date"),
             F.col("contract_value").cast("decimal(18,2)").alias("contract_amount")
             if "contract_value" in c.columns
             else F.lit(None).cast("decimal(18,2)").alias("contract_amount"),
             F.col("currency").alias("currency")
             if "currency" in c.columns
             else F.lit(None).cast("string").alias("currency"),
         )
    )


@dlt.view(comment="Closed-won opportunities treated as bookings without a contract.")
def stg_won_opps():
    o = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_opportunities")
    cust = dlt.read("silver.silver_customer").select("customer_sk", "crm_account_id")
    won = o.where(F.lower(F.col("stage")).contains("closed won")) \
        if "stage" in o.columns else o.where(F.lit(False))
    return (
        won.join(cust, won.account_id == cust.crm_account_id, "left")
        .select(
            F.col("opportunity_id").alias("contract_id"),
            F.lit("won_opportunity").alias("contract_source"),
            F.col("customer_sk"),
            F.col("account_id").alias("crm_account_id"),
            F.col("opportunity_id").alias("contract_number"),
            F.lit("Won").alias("contract_status"),
            F.to_date("close_date").alias("start_date")
            if "close_date" in o.columns else F.lit(None).cast("date").alias("start_date"),
            F.lit(None).cast("date").alias("end_date"),
            F.col("amount").cast("decimal(18,2)").alias("contract_amount")
            if "amount" in o.columns
            else F.lit(None).cast("decimal(18,2)").alias("contract_amount"),
            F.col("currency").alias("currency")
            if "currency" in o.columns
            else F.lit(None).cast("string").alias("currency"),
        )
    )


@dlt.table(
    name="silver.silver_contract",
    comment="Conformed contracts: CRM contracts UNION closed-won opportunities.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_contract_id", "contract_id IS NOT NULL")
@dlt.expect_or_drop("has_amount", "contract_amount IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
@dlt.expect("non_negative_amount", "contract_amount >= 0")
@dlt.expect("dates_ordered", "end_date IS NULL OR start_date IS NULL OR end_date >= start_date")
def silver_contract():
    return dlt.read("stg_crm_contracts").unionByName(dlt.read("stg_won_opps"))


# ---------------------------------------------------------------------------
# silver_sales_order
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.silver_sales_order",
    comment="Conformed ERP sales order headers, keyed to silver customer.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_order_id", "sales_order_id IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
@dlt.expect("positive_net_amount", "net_amount IS NULL OR net_amount >= 0")
@dlt.expect("sane_order_date", "order_date IS NULL OR order_date <= current_date()")
def silver_sales_order():
    so = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_erp_sales_orders")
    cust = dlt.read("silver.silver_customer").select("customer_sk", "erp_customer_id")
    return (
        so.join(cust, so.customer_id == cust.erp_customer_id, "left")
        .select(
            F.col("order_id").alias("sales_order_id"),
            F.col("customer_sk"),
            F.col("customer_id").alias("erp_customer_id"),
            normalize_name(F.col("customer_id").cast("string")).alias("_order_key_dbg"),
            F.to_date("order_date").alias("order_date")
            if "order_date" in so.columns
            else F.lit(None).cast("date").alias("order_date"),
            F.col("net_total_usd").cast("decimal(18,2)").alias("net_amount")
            if "net_total_usd" in so.columns
            else F.lit(None).cast("decimal(18,2)").alias("net_amount"),
            F.col("currency").alias("currency")
            if "currency" in so.columns
            else F.lit(None).cast("string").alias("currency"),
            F.col("status").alias("order_status")
            if "status" in so.columns
            else F.lit(None).cast("string").alias("order_status"),
        )
        .drop("_order_key_dbg")
    )
