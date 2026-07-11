# Databricks notebook source
# =============================================================================
# seed_collections_risk — synthetic gold.collections_risk for the agent vertical
# -----------------------------------------------------------------------------
# Decoupled from the (half-done) CRM cutover so the collections agent loop can be
# built + proven now. Mix of actionable / non-actionable accounts across tiers so
# the monitor's filtering is visible. Explicit schema (no inference).
# Swap this for the real gold.collections_risk once D6 lands.
# =============================================================================
from pyspark.sql import functions as F, types as T  # noqa: E402

dbutils.widgets.text("catalog", "cdp_dev", "Target catalog")  # noqa: F821
CATALOG = dbutils.widgets.get("catalog")  # noqa: F821
TABLE = f"{CATALOG}.gold.collections_risk"

# account_id, name, mcid, ar_balance, oldest_invoice_days, avg_days_to_pay,
# open_invoice_count, prior_slips, risk_score, risk_tier, account_health, last_payment_date
ROWS = [
    ("A1001", "Meridian Industrial Corp", "M-1001", 128500.0, 47, 38, 3, 0, 82, "High", "Healthy", "2026-05-24"),
    ("A1002", "Cascade Equipment Ltd",     "M-1002",  56200.0, 63, 55, 2, 3, 76, "High", "At-Risk", "2026-05-02"),
    ("A1003", "Apex Fabrication Inc",      "M-1003",   9400.0, 34, 30, 1, 1, 58, "Medium", "Healthy", "2026-06-08"),
    ("A1004", "Northwind Pumps",           "M-1004", 210000.0, 72, 61, 5, 4, 91, "High", "Critical", "2026-04-19"),
    ("A1005", "Blue Ridge Motors",         "M-1005",   3200.0, 41, 33, 1, 0, 44, "Medium", "Healthy", "2026-06-01"),
    ("A1006", "Granite State Tooling",     "M-1006",  18750.0, 22, 25, 2, 0, 39, "Low", "Healthy", "2026-06-20"),
    ("A1007", "Delta Valve Systems",       "M-1007",  74300.0, 58, 49, 4, 2, 71, "Medium", "At-Risk", "2026-05-11"),
    ("A1008", "Summit Hydraulics",         "M-1008",   1200.0, 12, 20, 1, 0, 18, "Low", "Healthy", "2026-06-28"),
]

schema = T.StructType([
    T.StructField("account_id", T.StringType()), T.StructField("account_name", T.StringType()),
    T.StructField("master_customer_id", T.StringType()), T.StructField("ar_balance", T.DoubleType()),
    T.StructField("oldest_invoice_days", T.IntegerType()), T.StructField("avg_days_to_pay", T.IntegerType()),
    T.StructField("open_invoice_count", T.IntegerType()), T.StructField("prior_slips", T.IntegerType()),
    T.StructField("risk_score", T.IntegerType()), T.StructField("risk_tier", T.StringType()),
    T.StructField("account_health", T.StringType()), T.StructField("last_payment_date", T.StringType()),
])

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.gold")  # noqa: F821
(spark.createDataFrame(ROWS, schema=schema)  # noqa: F821
    .withColumn("_seeded_at", F.current_timestamp())
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TABLE))
print(f"[seed] wrote {len(ROWS)} accounts to {TABLE}")
display(spark.table(TABLE))  # noqa: F821
