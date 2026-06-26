"""Silver product (SCD Type 2) + territory standardization.

Inputs
------
* ``bronze_erp_products``    -- ERP product master (slowly changing)
* ``bronze_ref_product_hierarchy`` -- category/family rollup for products
* ``bronze_crm_territories`` -- CRM sales territories

Outputs
-------
* ``silver_product`` -- SCD Type 2 history of products built with DLT's
  ``apply_changes`` (the Python equivalent of SQL ``APPLY CHANGES INTO``).
  Each product has validity columns (``__START_AT`` / ``__END_AT``) so we can
  ask "what did this product look like on date X".
* ``silver_territory`` -- standardized territory dimension (trimmed names,
  upper-cased region/country codes, normalized hierarchy).

SCD2 with apply_changes — concept
---------------------------------
``apply_changes`` turns a *stream of changes* into a managed dimension table:
  * ``keys``            -- the business key identifying a logical entity.
  * ``sequence_by``     -- the column that orders changes (latest wins).
  * ``stored_as_scd_type=2`` -- keep full history with validity windows instead
    of overwriting (type 1).
The **target** table is declared first with ``dlt.create_streaming_table`` and
then populated by ``apply_changes`` reading a streaming source. DLT manages the
open/close of historical versions for us.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# silver_product — SCD Type 2 via apply_changes
# ---------------------------------------------------------------------------

@dlt.view(comment="Product changes (streaming) enriched with hierarchy, for SCD2.")
def stg_product_changes():
    # Stream products so apply_changes consumes them incrementally as a change
    # feed. We enrich with the reference product hierarchy (static read).
    p = dlt.read_stream("bronze_erp_products")
    hier = dlt.read("bronze_ref_product_hierarchy")

    seq_col = "changed_on" if "changed_on" in p.columns else "_ingested_at"
    join_cond = (
        (p.product_id == hier.product_id)
        if "product_id" in hier.columns
        else F.lit(False)
    )
    enriched = p.join(hier, join_cond, "left")
    return enriched.select(
        p["product_id"],
        F.trim(p["name"]).alias("product_name") if "name" in p.columns
        else F.lit(None).cast("string").alias("product_name"),
        (hier["category"] if "category" in hier.columns
         else F.lit(None).cast("string")).alias("category"),
        (hier["family"] if "family" in hier.columns
         else F.lit(None).cast("string")).alias("family"),
        (p["unit_price"].cast("decimal(18,2)") if "unit_price" in p.columns
         else F.lit(None).cast("decimal(18,2)")).alias("unit_price"),
        (p["status"] if "status" in p.columns
         else F.lit(None).cast("string")).alias("status"),
        F.col(seq_col).alias("_seq"),
    )


# 1) Declare the SCD2 target streaming table.
dlt.create_streaming_table(
    name="silver_product",
    comment="Product dimension, SCD Type 2 history (validity windows).",
    table_properties={"quality": "silver"},
)

# 2) Apply the change feed into it as Type 2 history.
dlt.apply_changes(
    target="silver_product",
    source="stg_product_changes",
    keys=["product_id"],
    sequence_by=F.col("_seq"),
    stored_as_scd_type=2,
    # Treat absence of a delete flag as no deletes; products are soft-retired via
    # ``status`` rather than hard-deleted in this source.
)


# ---------------------------------------------------------------------------
# silver_territory — standardization (Type 1 conformance)
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver_territory",
    comment="Standardized CRM territory dimension.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_territory_id", "territory_id IS NOT NULL")
@dlt.expect("has_name", "territory_name IS NOT NULL")
def silver_territory():
    t = dlt.read("bronze_crm_territories")
    return t.select(
        F.col("territory_id"),
        F.trim(F.col("name")).alias("territory_name") if "name" in t.columns
        else F.lit(None).cast("string").alias("territory_name"),
        F.col("parent_territory_id") if "parent_territory_id" in t.columns
        else F.lit(None).cast("string").alias("parent_territory_id"),
        F.upper(F.trim(F.col("region"))).alias("region") if "region" in t.columns
        else F.lit(None).cast("string").alias("region"),
        F.upper(F.trim(F.col("country_code"))).alias("country_code")
        if "country_code" in t.columns
        else F.lit(None).cast("string").alias("country_code"),
    )
