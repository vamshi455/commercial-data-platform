"""Gold marts: ``support_performance``, ``account_health``, ``renewal_risk``.

Inputs (silver + gold)
----------------------
* ``silver_case``           -- support cases
* ``silver_activity``       -- engagement activities
* ``silver_contract``       -- contracts (for renewal windows)
* ``gold_collections_risk`` -- AR risk tier per customer
* ``silver_customer``       -- customer attributes

Outputs
-------
* ``gold_support_performance`` -- per-customer support KPIs (case volume,
  open cases, avg resolution hours, backlog).
* ``gold_account_health``      -- composite health score per customer blending
  support, engagement and collections signals into a ``health_tier``.
* ``gold_renewal_risk``        -- contracts approaching end-of-term with a
  ``renewal_risk_tier`` driven by account health + days-to-expiry.

Iceberg note
------------
All three are Delta (internal CS / ops marts). Not Iceberg candidates.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# gold_support_performance
# ---------------------------------------------------------------------------

@dlt.table(
    name="gold_support_performance",
    comment="Per-customer support KPIs (Delta).",
    table_properties={"quality": "gold"},
)
@dlt.expect_or_drop("has_customer", "customer_sk IS NOT NULL")
def gold_support_performance():
    return (
        dlt.read("silver.silver_case")
        .groupBy("customer_sk")
        .agg(
            F.count("*").alias("case_count"),
            F.sum(F.col("is_open").cast("int")).alias("open_case_count"),
            F.avg("resolution_hours").alias("avg_resolution_hours"),
            F.max("created_date").alias("last_case_date"),
            F.sum(F.when(F.lower(F.col("priority")).isin("high", "critical"), 1)
                  .otherwise(0)).alias("high_priority_case_count"),
        )
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )


# ---------------------------------------------------------------------------
# gold_account_health
# ---------------------------------------------------------------------------

@dlt.table(
    name="gold_account_health",
    comment="Composite account health blending support/engagement/collections (Delta).",
    table_properties={"quality": "gold"},
)
@dlt.expect_or_drop("has_customer", "customer_sk IS NOT NULL")
def gold_account_health():
    cust = dlt.read("silver.silver_customer").select("customer_sk", "company_name", "country")
    support = dlt.read("gold_support_performance").select(
        "customer_sk", "open_case_count", "high_priority_case_count", "avg_resolution_hours")
    collections = dlt.read("gold_collections_risk").select(
        "customer_sk", "risk_tier", "total_open_ar")
    engagement = (
        dlt.read("silver.silver_activity").groupBy("customer_sk").agg(
            F.max("activity_date").alias("last_activity_date"),
            F.count("*").alias("activity_count"),
        )
    )

    df = (
        cust.join(support, "customer_sk", "left")
        .join(collections, "customer_sk", "left")
        .join(engagement, "customer_sk", "left")
    )

    # Simple additive scoring (0 = best). Each signal contributes points.
    days_since_activity = F.datediff(F.current_date(), F.col("last_activity_date"))
    score = (
        F.coalesce(F.col("open_case_count"), F.lit(0))
        + 2 * F.coalesce(F.col("high_priority_case_count"), F.lit(0))
        + F.when(F.col("risk_tier") == "high", 5)
           .when(F.col("risk_tier") == "medium", 3)
           .when(F.col("risk_tier") == "low", 1)
           .otherwise(0)
        + F.when(days_since_activity > 180, 3)
           .when(days_since_activity > 90, 1)
           .otherwise(0)
    )

    return (
        df.withColumn("health_score", score)
        .withColumn(
            "health_tier",
            F.when(F.col("health_score") >= 8, F.lit("at_risk"))
             .when(F.col("health_score") >= 4, F.lit("watch"))
             .otherwise(F.lit("healthy")),
        )
        .withColumn("days_since_last_activity", days_since_activity)
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )


# ---------------------------------------------------------------------------
# gold_renewal_risk
# ---------------------------------------------------------------------------

@dlt.table(
    name="gold_renewal_risk",
    comment="Contracts nearing end-of-term scored by renewal risk (Delta).",
    table_properties={"quality": "gold"},
)
@dlt.expect("has_contract", "contract_id IS NOT NULL")
def gold_renewal_risk():
    contracts = dlt.read("silver.silver_contract").where("end_date IS NOT NULL")
    health = dlt.read("gold_account_health").select(
        "customer_sk", "health_tier", "health_score")

    days_to_expiry = F.datediff(F.col("end_date"), F.current_date())

    return (
        contracts.join(health, "customer_sk", "left")
        .withColumn("days_to_expiry", days_to_expiry)
        # only contracts expiring within ~180 days are in the renewal window
        .where("days_to_expiry BETWEEN -30 AND 180")
        .withColumn(
            "renewal_risk_tier",
            F.when((F.col("health_tier") == "at_risk") | (days_to_expiry < 0), F.lit("high"))
             .when((F.col("health_tier") == "watch") | (days_to_expiry <= 60), F.lit("medium"))
             .otherwise(F.lit("low")),
        )
        .select(
            "contract_id", "customer_sk", "contract_amount", "end_date",
            "days_to_expiry", "health_tier", "health_score", "renewal_risk_tier",
        )
        .withColumn("_gold_loaded_at", F.current_timestamp())
    )
