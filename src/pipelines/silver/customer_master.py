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

from src.pipelines._common import (
    crosswalk_path,
    normalize_domain,
    normalize_name,
    surrogate_key,
)


# ---------------------------------------------------------------------------
# Deduplicated, normalised staging views (one per source system).
# These are DLT *views* (not materialised) — cheap intermediate logic.
# ---------------------------------------------------------------------------

@dlt.view(comment="CRM accounts, deduped to latest per source id, with match keys.")
def stg_crm_accounts():
    df = dlt.read("bronze_crm_accounts")
    # Pick the latest record per CRM account id (defensive dedup). We assume a
    # last-modified column from the source; fall back to ingest time.
    mod_col = "last_modified_date" if "last_modified_date" in df.columns else "_ingested_at"
    w = Window.partitionBy("account_id").orderBy(F.col(mod_col).desc())
    return (
        df.withColumn("_rn", F.row_number().over(w))
          .where("_rn = 1")
          .withColumn("name_key", normalize_name("name"))
          .withColumn("domain_key", normalize_domain(
              F.coalesce(F.col("website"), F.col("email")) if "website" in df.columns
              else F.col("email")))
          .select(
              F.col("account_id").alias("crm_account_id"),
              F.col("name").alias("crm_name"),
              "name_key", "domain_key",
              F.col("billing_country").alias("crm_country")
              if "billing_country" in df.columns else F.lit(None).alias("crm_country"),
          )
    )


@dlt.view(comment="ERP customers, deduped to latest per source id, with match keys.")
def stg_erp_customers():
    df = dlt.read("bronze_erp_customers")
    mod_col = "changed_on" if "changed_on" in df.columns else "_ingested_at"
    w = Window.partitionBy("customer_id").orderBy(F.col(mod_col).desc())
    domain_src = F.col("email") if "email" in df.columns else F.lit(None)
    return (
        df.withColumn("_rn", F.row_number().over(w))
          .where("_rn = 1")
          .withColumn("name_key", normalize_name("name"))
          .withColumn("domain_key", normalize_domain(domain_src))
          .select(
              F.col("customer_id").alias("erp_customer_id"),
              F.col("name").alias("erp_name"),
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
    name="silver_customer",
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
