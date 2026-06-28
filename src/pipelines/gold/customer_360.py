"""Gold mart: ``customer_360`` — one wide row per customer.

Inputs (all silver)
-------------------
* ``silver_customer``  -- conformed customer master (grain: customer_sk)
* ``silver_contract``  -- committed bookings (contracts + won opps)
* ``silver_invoice``   -- reconciled invoices (open/paid/late)
* ``silver_case``      -- support cases
* ``silver_activity``  -- engagement activities

Output
------
``gold_customer_360`` at grain = one row per ``customer_sk``, blending
commercial, financial, support and engagement signals for a 360 view.

Iceberg note
------------
``customer_360`` is a **Managed Iceberg candidate**: it is a broadly-shared,
cross-engine "single source of truth" product that benefits from open-format
interoperability (queryable by external Iceberg-aware engines). DLT currently
materialises tables as **Delta**, so this table is Delta here. To publish the
Iceberg variant you would declare a managed Iceberg table in Unity Catalog
outside DLT (or via a downstream task), e.g.::

    CREATE TABLE <catalog>.gold.customer_360_iceberg
    USING ICEBERG
    TBLPROPERTIES (
      'delta.columnMapping.mode' = 'name'      -- if converting from Delta
    )
    AS SELECT * FROM <catalog>.gold.customer_360;

    -- or, for a natively managed Iceberg table:
    -- CREATE TABLE <catalog>.gold.customer_360 (...) USING ICEBERG
    --   TBLPROPERTIES ('format-version' = '2');

Gold products that would be published as **Iceberg** in this platform:
``customer_360`` and ``revenue_pipeline`` (wide, cross-engine BI products).
The rest stay Delta (operational / internally-consumed marts).
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


@dlt.table(
    name="gold_customer_360",
    comment="One row per customer blending commercial/financial/support/engagement. "
            "Iceberg candidate (materialised as Delta in DLT).",
    table_properties={"quality": "gold", "cdp.iceberg_candidate": "true"},
)
@dlt.expect_or_drop("has_customer", "customer_sk IS NOT NULL")
def gold_customer_360():
    cust = dlt.read("silver.silver_customer")

    contracts = (
        dlt.read("silver.silver_contract").groupBy("customer_sk").agg(
            F.count("*").alias("contract_count"),
            F.sum("contract_amount").alias("total_contract_amount"),
            F.max("start_date").alias("latest_contract_date"),
        )
    )
    invoices = (
        dlt.read("silver.silver_invoice").groupBy("customer_sk").agg(
            F.count("*").alias("invoice_count"),
            F.sum("gross_amount").alias("total_invoiced"),
            F.sum("amount_paid").alias("total_paid"),
            F.sum("open_amount").alias("total_open_ar"),
            F.sum(F.col("is_late").cast("int")).alias("late_invoice_count"),
            F.max("days_past_due").alias("max_days_past_due"),
        )
    )
    cases = (
        dlt.read("silver.silver_case").groupBy("customer_sk").agg(
            F.count("*").alias("case_count"),
            F.sum(F.col("is_open").cast("int")).alias("open_case_count"),
            F.avg("resolution_hours").alias("avg_resolution_hours"),
        )
    )
    acts = (
        dlt.read("silver.silver_activity").groupBy("customer_sk").agg(
            F.count("*").alias("activity_count"),
            F.max("activity_date").alias("last_activity_date"),
        )
    )

    return (
        cust.join(contracts, "customer_sk", "left")
        .join(invoices, "customer_sk", "left")
        .join(cases, "customer_sk", "left")
        .join(acts, "customer_sk", "left")
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )
