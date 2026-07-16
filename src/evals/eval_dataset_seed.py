# Databricks notebook source
# =============================================================================
# eval_dataset_seed — write the golden eval set to contracts.eval_dataset
# -----------------------------------------------------------------------------
# A small, hand-authored starter set spanning the eval categories in
# docs/agent-evals.md §2 (retrieval, groundedness, safety, edge-case). Grow it
# with synthetic-generated + SME-reviewed rows over time; it's a versioned Delta
# table so eval scores stay comparable across releases.
#
# Explicit schema on write (never infer — an all-None column would raise
# CANNOT_DETERMINE_TYPE, the same bug we hit in silver parse).
# =============================================================================
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")

from pyspark.sql import functions as F, types as T  # noqa: E402

dbutils.widgets.text("catalog", "cdp_dev", "Target catalog")  # noqa: F821
CATALOG = dbutils.widgets.get("catalog")  # noqa: F821
TABLE = f"{CATALOG}.contracts.eval_dataset"

# COMMAND ----------
# Golden rows live in the pure `golden_set` module (import-clean, no Spark) so the
# same source of truth backs both this notebook and the off-cluster pytest criteria
# (tests/pipeline_validation/test_eval_dataset_contract.py). See docs/agent-evals.md §3.
from golden_set import SEED  # noqa: E402

schema = T.StructType([
    T.StructField("request", T.StringType()),
    T.StructField("expected_facts", T.StringType()),
    T.StructField("expected_chunk_ids", T.ArrayType(T.StringType())),
    T.StructField("category", T.StringType()),
    T.StructField("master_customer_id", T.StringType()),
    T.StructField("notes", T.StringType()),
])

# COMMAND ----------
df = (spark.createDataFrame(SEED, schema=schema)  # noqa: F821
      .withColumn("_seeded_at", F.current_timestamp()))
(df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TABLE))
spark.sql(  # noqa: F821
    f"COMMENT ON TABLE {TABLE} IS 'Golden evaluation set for the "
    f"contract_intelligence agent: request, expected_facts, expected_chunk_ids, "
    f"category (retrieval/groundedness/safety/edge-case). See docs/agent-evals.md.'")
print(f"[eval] wrote {df.count()} golden rows to {TABLE}")
display(spark.table(TABLE))  # noqa: F821
