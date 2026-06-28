"""Gold mart: ``collections_risk`` — AR aging and collections risk scoring.

Inputs (silver)
---------------
* ``silver_invoice`` -- reconciled invoices (open_amount, days_past_due, flags)
* ``silver_payment`` -- payments (for recent-payment behaviour signals)
* ``silver_customer`` -- customer attributes

Output
------
``gold_collections_risk`` at grain = one row per ``customer_sk`` with AR aging
buckets, total open AR, weighted days-past-due, and a coarse ``risk_tier``.

Aging buckets (days past due): current (<=0), 1-30, 31-60, 61-90, 90+.

Iceberg note
------------
Delta product (operational collections mart consumed internally). Not an
Iceberg candidate.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


@dlt.table(
    name="gold_collections_risk",
    comment="Per-customer AR aging buckets + collections risk tier (Delta).",
    table_properties={"quality": "gold"},
)
@dlt.expect_or_drop("has_customer", "customer_sk IS NOT NULL")
def gold_collections_risk():
    inv = dlt.read("silver.silver_invoice").where("open_amount > 0")

    dpd = F.col("days_past_due")
    open_amt = F.col("open_amount")

    def bucket(lo, hi):
        cond = (dpd > lo) & (dpd <= hi) if hi is not None else (dpd > lo)
        return F.sum(F.when(cond, open_amt).otherwise(F.lit(0))).cast("decimal(18,2)")

    aging = (
        inv.groupBy("customer_sk").agg(
            F.sum(F.when(dpd <= 0, open_amt).otherwise(F.lit(0)))
             .cast("decimal(18,2)").alias("ar_current"),
            bucket(0, 30).alias("ar_1_30"),
            bucket(30, 60).alias("ar_31_60"),
            bucket(60, 90).alias("ar_61_90"),
            bucket(90, None).alias("ar_90_plus"),
            F.sum(open_amt).cast("decimal(18,2)").alias("total_open_ar"),
            F.max(dpd).alias("max_days_past_due"),
            # AR-weighted average days past due
            (F.sum(dpd * open_amt) / F.sum(open_amt)).alias("weighted_days_past_due"),
            F.sum(F.col("is_disputed").cast("int")).alias("disputed_invoice_count"),
        )
    )

    cust = dlt.read("silver.silver_customer").select("customer_sk", "company_name", "country")

    return (
        aging.join(cust, "customer_sk", "left")
        .withColumn(
            "risk_tier",
            F.when(F.col("ar_90_plus") > 0, F.lit("high"))
             .when((F.col("ar_61_90") > 0) | (F.col("disputed_invoice_count") > 0), F.lit("medium"))
             .when(F.col("total_open_ar") > 0, F.lit("low"))
             .otherwise(F.lit("none")),
        )
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )
