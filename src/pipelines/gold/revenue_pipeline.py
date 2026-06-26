"""Gold marts: ``revenue_pipeline`` and ``bookings_vs_billings``.

Inputs (silver)
---------------
* ``silver_contract``    -- bookings (contracts + closed-won opps)
* ``silver_sales_order`` -- ERP orders
* ``silver_invoice``     -- billings/invoices

Outputs
-------
* ``gold_revenue_pipeline`` -- monthly pipeline/bookings rollup by customer,
  combining committed bookings with ordered and billed amounts.
* ``gold_bookings_vs_billings`` -- monthly bookings vs billings comparison with a
  ``billings_gap`` (bookings recognised but not yet billed).

Iceberg note
------------
``revenue_pipeline`` is an **Iceberg candidate** (wide, cross-engine BI/finance
product). Materialised as Delta in DLT; see ``customer_360.py`` for the managed
Iceberg ``CREATE TABLE ... USING ICEBERG`` publishing pattern.
``bookings_vs_billings`` stays Delta (internal finance ops mart).
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


def _month(col):
    """First-of-month truncation helper for monthly grain."""
    return F.trunc(col, "month")


@dlt.table(
    name="gold_revenue_pipeline",
    comment="Monthly bookings/orders/billings by customer. Iceberg candidate "
            "(materialised as Delta in DLT).",
    table_properties={"quality": "gold", "cdp.iceberg_candidate": "true"},
)
@dlt.expect("has_period", "period_month IS NOT NULL")
def gold_revenue_pipeline():
    bookings = (
        dlt.read("silver_contract")
        .withColumn("period_month", _month(F.col("start_date")))
        .groupBy("customer_sk", "period_month")
        .agg(F.sum("contract_amount").alias("booked_amount"),
             F.count("*").alias("booking_count"))
    )
    orders = (
        dlt.read("silver_sales_order")
        .withColumn("period_month", _month(F.col("order_date")))
        .groupBy("customer_sk", "period_month")
        .agg(F.sum("net_amount").alias("ordered_amount"),
             F.count("*").alias("order_count"))
    )
    billings = (
        dlt.read("silver_invoice")
        .withColumn("period_month", _month(F.col("invoice_date")))
        .groupBy("customer_sk", "period_month")
        .agg(F.sum("gross_amount").alias("billed_amount"),
             F.count("*").alias("invoice_count"))
    )

    return (
        bookings
        .join(orders, ["customer_sk", "period_month"], "full_outer")
        .join(billings, ["customer_sk", "period_month"], "full_outer")
        .fillna(0, ["booked_amount", "booking_count", "ordered_amount",
                    "order_count", "billed_amount", "invoice_count"])
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )


@dlt.table(
    name="gold_bookings_vs_billings",
    comment="Monthly bookings vs billings with the unbilled gap (Delta).",
    table_properties={"quality": "gold"},
)
@dlt.expect("has_period", "period_month IS NOT NULL")
def gold_bookings_vs_billings():
    rp = dlt.read("gold_revenue_pipeline")
    return (
        rp.groupBy("period_month")
        .agg(
            F.sum("booked_amount").alias("total_booked"),
            F.sum("billed_amount").alias("total_billed"),
            F.sum("ordered_amount").alias("total_ordered"),
        )
        .withColumn("billings_gap", F.col("total_booked") - F.col("total_billed"))
        .withColumn(
            "billed_to_booked_ratio",
            F.when(F.col("total_booked") != 0,
                   F.round(F.col("total_billed") / F.col("total_booked"), 4))
             .otherwise(F.lit(None)),
        )
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )
