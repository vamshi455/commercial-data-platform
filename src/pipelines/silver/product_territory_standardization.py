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
    p = spark.readStream.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_erp_products")
    hier_raw = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_ref_product_hierarchy")

    seq_col = "scd_version" if "scd_version" in p.columns else "_ingested_at"

    # Products and the reference hierarchy share a ``division`` key (the
    # hierarchy is per division/category, not per material). Narrow the
    # hierarchy to just the columns we need and rename its join key so the
    # stream-static join produces NO duplicated column names (division and the
    # _ingested_at/_source_* audit columns exist on both sides otherwise).
    hier = hier_raw.select(
        hier_raw["division"].alias("_hier_division"),
        (hier_raw["category"] if "category" in hier_raw.columns
         else F.lit(None).cast("string")).alias("_hier_category"),
        (hier_raw["subcategory"] if "subcategory" in hier_raw.columns
         else F.lit(None).cast("string")).alias("_hier_subcategory"),
    )
    join_cond = (
        (p["division"] == hier["_hier_division"])
        if "division" in p.columns
        else F.lit(False)
    )
    enriched = p.join(hier, join_cond, "left")
    return enriched.select(
        p["material_id"].alias("product_id"),
        F.trim(p["material_desc"]).alias("product_name") if "material_desc" in p.columns
        else F.lit(None).cast("string").alias("product_name"),
        F.col("_hier_category").alias("category"),
        F.col("_hier_subcategory").alias("family"),
        (p["list_price_usd"].cast("decimal(18,2)") if "list_price_usd" in p.columns
         else F.lit(None).cast("decimal(18,2)")).alias("unit_price"),
        # No product status column on bronze_erp_products; surface as null.
        (p["status"] if "status" in p.columns
         else F.lit(None).cast("string")).alias("status"),
        F.col(seq_col).alias("_seq"),
    )


# 1) Declare the SCD2 target streaming table.
dlt.create_streaming_table(
    name="silver.silver_product",
    comment="Product dimension, SCD Type 2 history (validity windows).",
    table_properties={"quality": "silver"},
)

# 2) Apply the change feed into it as Type 2 history.
dlt.apply_changes(
    target="silver.silver_product",
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
    name="silver.silver_territory",
    comment="Standardized CRM territory dimension.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_territory_id", "territory_id IS NOT NULL")
@dlt.expect("has_name", "territory_name IS NOT NULL")
def silver_territory():
    t = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_territories")
    return t.select(
        F.col("territory_id"),
        F.trim(F.col("territory_name")).alias("territory_name") if "territory_name" in t.columns
        else F.lit(None).cast("string").alias("territory_name"),
        F.col("parent_territory_id") if "parent_territory_id" in t.columns
        else F.lit(None).cast("string").alias("parent_territory_id"),
        F.upper(F.trim(F.col("region"))).alias("region") if "region" in t.columns
        else F.lit(None).cast("string").alias("region"),
        F.upper(F.trim(F.col("country_code"))).alias("country_code")
        if "country_code" in t.columns
        else F.lit(None).cast("string").alias("country_code"),
    )
