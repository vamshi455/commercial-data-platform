# Databricks notebook source
# =============================================================================
# deploy_contract_agent — log + register + deploy the contract_intelligence agent
# -----------------------------------------------------------------------------
# Mosaic AI Agent Framework path (see docs/agents.md / docs/agent-evals.md):
#   log model.py "from code"  -> UC registered model (Models)
#   agents.deploy(...)        -> Model Serving endpoint + review app (Serving)
#   traces/eval               -> Experiments
#
# PREREQ: the VS index cdp_dev.contracts.contract_chunks_index must exist and its
# endpoint be ONLINE for the agent to retrieve (recreate + index_sync if deleted).
# The served endpoint uses scale_to_zero, so it costs ~nothing idle; the always-on
# cost is the Vector Search endpoint.
#   databricks bundle run job_deploy_contract_agent -t dev
# =============================================================================
# MAGIC %pip install --quiet -U mlflow databricks-agents databricks-vectorsearch databricks-sdk
# MAGIC %restart_python

# COMMAND ----------
import os
import mlflow
from mlflow.models.resources import DatabricksVectorSearchIndex, DatabricksServingEndpoint

dbutils.widgets.text("catalog", "cdp_dev", "Target catalog")              # noqa: F821
dbutils.widgets.text("vs_endpoint", "cdp_contracts_vs", "VS endpoint")     # noqa: F821
dbutils.widgets.text("gen_model", "databricks-claude-sonnet-5", "Gen model")  # noqa: F821
dbutils.widgets.text("source_root", "", "Bundle files root (job sets ${workspace.file_path})")  # noqa: F821

CATALOG = dbutils.widgets.get("catalog")          # noqa: F821
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")  # noqa: F821
GEN_MODEL = dbutils.widgets.get("gen_model")      # noqa: F821
ROOT = dbutils.widgets.get("source_root")         # noqa: F821

MODEL_FILE = os.path.join(ROOT, "agents", "contract_intelligence", "model.py") if ROOT \
    else os.path.abspath("../../agents/contract_intelligence/model.py")
UC_MODEL = f"{CATALOG}.contracts.contract_intelligence"
INDEX = f"{CATALOG}.contracts.contract_chunks_index"
print("model file:", MODEL_FILE, "\nUC model:", UC_MODEL, "\nindex:", INDEX)

# COMMAND ----------
# ---- log the agent (from code) + register to Unity Catalog -------------------
mlflow.set_registry_uri("databricks-uc")

resources = [
    DatabricksVectorSearchIndex(index_name=INDEX),
    DatabricksServingEndpoint(endpoint_name=GEN_MODEL),
]
input_example = {"messages": [
    {"role": "user", "content": "What are the termination terms of the spot purchase contract?"}
]}

with mlflow.start_run(run_name="contract_intelligence_deploy"):
    logged = mlflow.pyfunc.log_model(
        name="agent",
        python_model=MODEL_FILE,               # models-from-code
        resources=resources,
        input_example=input_example,
        registered_model_name=UC_MODEL,
        pip_requirements=[
            "mlflow", "databricks-agents", "databricks-vectorsearch", "databricks-sdk",
        ],
    )
print("registered:", logged.registered_model_version, "uri:", logged.model_uri)

# COMMAND ----------
# ---- deploy to Model Serving (scale-to-zero) --------------------------------
from databricks import agents

deployment = agents.deploy(
    UC_MODEL,
    logged.registered_model_version,
    scale_to_zero=True,               # ~no idle cost on the agent endpoint
    tags={"platform": "commercial-data-platform", "domain": "contracts"},
)
print("Agent deployed.")
print("  Serving endpoint:", getattr(deployment, "endpoint_name", "(see Serving UI)"))
print("  Review app:", getattr(deployment, "review_app_url", "(see Serving UI)"))
print("Now visible under: Models (UC) · Serving · Experiments (traces).")
