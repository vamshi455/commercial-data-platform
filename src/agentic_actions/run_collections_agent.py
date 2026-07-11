# Databricks notebook source
# =============================================================================
# run_collections_agent — monitor → diagnose → draft → ops.action_queue
# -----------------------------------------------------------------------------
# Reads gold.collections_risk, runs the collections agent (detect actionable →
# LLM diagnose + draft), and writes PROPOSALS to ops.action_queue with
# status='pending'. Nothing is sent — a human approves in the queue (see
# notebooks/agentic_actions/review_queue.sql), and decisions feed
# ops.action_feedback. Idempotent per run_id.
# =============================================================================
import sys, os, uuid
dbutils.widgets.text("catalog", "cdp_dev", "Target catalog")       # noqa: F821
dbutils.widgets.text("run_id", "", "Run id (job passes {{job.run_id}})")  # noqa: F821
dbutils.widgets.text("gen_model", "databricks-claude-sonnet-5", "LLM")  # noqa: F821
dbutils.widgets.text("source_root", "", "Bundle files root")        # noqa: F821

CATALOG = dbutils.widgets.get("catalog")     # noqa: F821
GEN_MODEL = dbutils.widgets.get("gen_model")  # noqa: F821
ROOT = dbutils.widgets.get("source_root")     # noqa: F821
# Serverless whitelists block currentRunId(); use the passed job run id, else a uuid.
RUN_ID = dbutils.widgets.get("run_id") or uuid.uuid4().hex[:16]  # noqa: F821

_AGENT = os.path.join(ROOT, "agents", "collections") if ROOT else \
    os.path.abspath("../../agents/collections")
sys.path.insert(0, _AGENT)
from agent import propose_actions  # noqa: E402

from pyspark.sql import functions as F, types as T  # noqa: E402

# COMMAND ----------
accounts = [r.asDict() for r in spark.table(f"{CATALOG}.gold.collections_risk").collect()]  # noqa: F821
print(f"[collections] scanning {len(accounts)} accounts (run {RUN_ID})")
proposals = propose_actions(accounts, run_id=RUN_ID, model=GEN_MODEL)
print(f"[collections] {len(proposals)} actionable → proposals drafted")

# COMMAND ----------
schema = T.StructType([
    T.StructField("action_id", T.StringType()), T.StructField("account_id", T.StringType()),
    T.StructField("account_name", T.StringType()), T.StructField("master_customer_id", T.StringType()),
    T.StructField("signal", T.StringType()), T.StructField("priority", T.StringType()),
    T.StructField("action_type", T.StringType()), T.StructField("diagnosis", T.StringType()),
    T.StructField("draft", T.StringType()), T.StructField("status", T.StringType()),
    T.StructField("run_id", T.StringType()),
])
if proposals:
    (spark.createDataFrame(proposals, schema=schema)  # noqa: F821
        .withColumn("agent", F.lit("collections"))
        .withColumn("_created_at", F.current_timestamp())
        .write.mode("append").saveAsTable(f"{CATALOG}.ops.action_queue"))
print(f"[collections] wrote {len(proposals)} proposals to {CATALOG}.ops.action_queue (status=pending)")
display(spark.sql(  # noqa: F821
    f"SELECT priority, account_name, action_type, signal, left(diagnosis,80) diagnosis "
    f"FROM {CATALOG}.ops.action_queue WHERE run_id='{RUN_ID}' ORDER BY priority"))
