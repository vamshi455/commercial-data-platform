# Databricks notebook source
# =============================================================================
# setup_vrr_monitoring — enable MLflow 3 / Lakehouse Monitoring for GenAI on the
# VRR agent endpoint. Tries the databricks.agents.monitoring API, then the MLflow 3
# scorer API as fallback. If the beta isn't available in this workspace, the calls
# raise a clear error (job fails, CLI shows why).
#   databricks bundle run job_setup_vrr_monitoring -t dev
# =============================================================================
# MAGIC %pip install --quiet -U "mlflow>=3.1.3" "databricks-agents>=1.2.0"
# MAGIC %restart_python

# COMMAND ----------
import json, importlib.metadata as md
res = {}
for p in ("databricks-agents", "mlflow"):
    try:
        res[p] = md.version(p)
    except Exception as e:
        res[p] = f"?({e})"

# Register scorers on the experiment the ENDPOINT actually logs traces to. NOTE:
# agents.deploy() ties the endpoint's trace store to the DEPLOY NOTEBOOK's experiment
# (verified stable: /Users/<me>/.bundle/.../deploy_vrr_agent), NOT the active mlflow
# experiment — so target that id directly. create_monitor is deprecated for
# Agent-Framework endpoints; the MLflow 3 scorer API is the path.
import mlflow
from mlflow.genai.scorers import Safety, Guidelines, ScorerSamplingConfig

EXPERIMENT_ID = "881736705963498"   # endpoint's trace experiment (deploy_vrr_agent)
res["endpoint_experiment_id"] = EXPERIMENT_ID
mlflow.set_experiment(experiment_id=EXPERIMENT_ID)


def _reg(scorer, name, rate):
    try:
        scorer.register(name=name).start(sampling_config=ScorerSamplingConfig(sample_rate=rate))
        return f"OK (sample={rate})"
    except Exception as e:                                    # already-registered or unavailable
        return f"{type(e).__name__}: {str(e)[:200]}"


# built-in safety on every trace
res["safety"] = _reg(Safety(), "vrr_safety", 1.0)
# on-brand: our no-arithmetic / grounded principle as a continuous production judge
res["grounded"] = _reg(
    Guidelines(name="grounded", guidelines=[
        "Every number in the response must come from a tool result; the assistant must not "
        "perform free-form arithmetic or invent figures.",
        "Any driver or cause named must be supported by the VRR_DECOMPOSE result."]),
    "vrr_grounded", 0.5)

dbutils.notebook.exit(json.dumps(res, indent=2))          # noqa: F821
