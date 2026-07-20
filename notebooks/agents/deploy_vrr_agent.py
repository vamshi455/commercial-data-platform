# Databricks notebook source
# =============================================================================
# deploy_vrr_agent — log + register + deploy the VRR Reasoning & Lineage agent
# -----------------------------------------------------------------------------
# Mosaic AI Agent Framework path (mirrors deploy_contract_agent.py):
#   log agents/vrr_reasoning/model.py "from code" (+ code_paths for the vrr_agent
#       package) -> UC registered model
#   agents.deploy(...) -> Model Serving endpoint (scale-to-zero) + review app
#
# PREREQ: 01_setup_schemas.sql + the curated tables (03/04) must exist in cdp_dev,
# and a SQL warehouse HTTP path must be provided (the served agent reads via
# databricks-sql-connector — Serving has no Spark).
#   databricks bundle run job_deploy_vrr_agent -t dev
# =============================================================================
# MAGIC %pip install --quiet -U mlflow databricks-agents databricks-sql-connector databricks-sdk
# MAGIC %restart_python

# COMMAND ----------
import os
import mlflow
from mlflow.models.resources import (
    DatabricksServingEndpoint, DatabricksFunction, DatabricksSQLWarehouse, DatabricksTable)

dbutils.widgets.text("catalog", "cdp_dev", "Target catalog")                     # noqa: F821
dbutils.widgets.text("gen_model", "databricks-claude-sonnet-5", "Gen model")     # noqa: F821
dbutils.widgets.text("warehouse_http_path", "", "SQL warehouse HTTP path")       # noqa: F821
dbutils.widgets.text("source_root", "", "Bundle files root (${workspace.file_path})")  # noqa: F821

CATALOG = dbutils.widgets.get("catalog")            # noqa: F821
GEN_MODEL = dbutils.widgets.get("gen_model")        # noqa: F821
HTTP_PATH = dbutils.widgets.get("warehouse_http_path")  # noqa: F821
ROOT = dbutils.widgets.get("source_root")           # noqa: F821

MODEL_FILE = os.path.join(ROOT, "agents", "vrr_reasoning", "model.py") if ROOT \
    else os.path.abspath("../../agents/vrr_reasoning/model.py")
# ship the deterministic VRR package with the model (physics/tools/agent/config)
VRR_PKG = os.path.join(ROOT, "src", "vrr_agent") if ROOT \
    else os.path.abspath("../../src/vrr_agent")
# mlflow execs model.py at LOG time to infer requirements — before code_paths takes
# effect (that's LOAD/serving time). Put src/ on sys.path now so model.py's
# `from vrr_agent import ...` resolves during that log-time exec too.
import sys
SRC_ROOT = os.path.join(ROOT, "src") if ROOT else os.path.abspath("../../src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)
UC_MODEL = f"{CATALOG}.vrr_agent.vrr_reasoning"
print("model:", MODEL_FILE, "\ncode_paths:", VRR_PKG, "\nsrc:", SRC_ROOT, "\nUC model:", UC_MODEL)

# COMMAND ----------
# ---- log the agent (from code) + register to Unity Catalog -------------------
mlflow.set_registry_uri("databricks-uc")

# WAREHOUSE_ID from the HTTP path (…/warehouses/<id>) — declaring the warehouse as
# a resource scopes the endpoint's auto-provisioned token to it (so _connect works).
WAREHOUSE_ID = HTTP_PATH.rstrip("/").split("/")[-1]
# The agent reads these curated tables via the warehouse; declaring them as
# resources auto-grants the endpoint's system service principal SELECT on them
# (fixes "USE SCHEMA on cdp_dev.vrr_curated" — automatic-auth passthrough only
# covers DECLARED resources, and a warehouse resource alone doesn't grant UC reads).
CURATED_TABLES = ["pattern_vrr_daily", "pattern_vrr_monthly", "completion_contrib", "pattern_target"]
# Value-level lineage graph: the impact/trace UC functions read these node/edge tables,
# so the endpoint SP needs EXECUTE on the functions AND SELECT on the tables.
GRAPH_TABLES = ["lineage_node", "lineage_edge", "pattern_vrr_log"]
GRAPH_FUNCTIONS = ["vrr_get", "vrr_lineage", "vrr_impact", "vrr_trace"]
resources = [
    DatabricksServingEndpoint(endpoint_name=GEN_MODEL),
    DatabricksSQLWarehouse(warehouse_id=WAREHOUSE_ID),
] + [DatabricksFunction(function_name=f"{CATALOG}.vrr_agent.{f}") for f in GRAPH_FUNCTIONS] \
  + [DatabricksTable(table_name=f"{CATALOG}.vrr_curated.{t}") for t in CURATED_TABLES] \
  + [DatabricksTable(table_name=f"{CATALOG}.vrr_agent.{t}") for t in GRAPH_TABLES]
print("warehouse:", WAREHOUSE_ID, "· curated:", CURATED_TABLES, "· graph:", GRAPH_TABLES)
# NB: no input_example — mlflow would run a predict at LOG time to infer the
# signature, which opens a SQL-warehouse connection before the serving env vars
# (CDP_WAREHOUSE_HTTP_PATH) exist and fails ("No valid connection settings"). The
# ChatAgent flavor supplies the schema; the agent is exercised at serving time.
with mlflow.start_run(run_name="vrr_reasoning_deploy"):
    logged = mlflow.pyfunc.log_model(
        name="agent",
        python_model=MODEL_FILE,                 # models-from-code
        code_paths=[VRR_PKG],                    # ship src/vrr_agent alongside
        resources=resources,
        pip_requirements=[
            "mlflow", "databricks-agents", "databricks-sql-connector", "databricks-sdk",
        ],
        registered_model_name=UC_MODEL,
    )
print("registered:", logged.registered_model_version, "uri:", logged.model_uri)

# COMMAND ----------
# ---- deploy to Model Serving (scale-to-zero) --------------------------------
from databricks import agents

deployment = agents.deploy(
    UC_MODEL, logged.registered_model_version, scale_to_zero=True,
    environment_vars={"CDP_CATALOG": CATALOG, "CDP_GEN_MODEL": GEN_MODEL,
                      "CDP_WAREHOUSE_HTTP_PATH": HTTP_PATH},
    tags={"platform": "commercial-data-platform", "domain": "vrr"},
)
print("VRR agent deployed.")
print("  Serving endpoint:", getattr(deployment, "endpoint_name", "(see Serving UI)"))
print("  Review app:", getattr(deployment, "review_app_url", "(see Serving UI)"))
