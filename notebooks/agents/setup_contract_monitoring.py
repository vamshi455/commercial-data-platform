# Databricks notebook source
# =============================================================================
# setup_contract_monitoring — enable MLflow 3 / Lakehouse Monitoring for GenAI on
# the contract_intelligence agent endpoint. Registers production scorers (safety +
# grounded-citation) as continuous judges over the endpoint's live traces. If the
# beta isn't available in this workspace, the calls raise a clear error (job fails,
# CLI shows why).
#   databricks bundle run job_setup_contract_monitoring -t dev
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

# Register scorers on the experiment the ENDPOINT actually logs traces to. agents.deploy()
# ties the endpoint's trace store to the experiment the MODEL was logged under — the
# deploy notebook sets that to `/Users/<me>/contract_agent_traces` before log_model, so
# resolve it by NAME here (robust across re-deploys, no hardcoded id). create_monitor is
# deprecated for Agent-Framework endpoints; the MLflow 3 scorer API is the path.
import mlflow
from mlflow.genai.scorers import Safety, Guidelines, ScorerSamplingConfig

_user = spark.sql("SELECT current_user()").collect()[0][0]                # noqa: F821
TRACE_EXPERIMENT = f"/Users/{_user}/contract_agent_traces"
exp = mlflow.get_experiment_by_name(TRACE_EXPERIMENT)
if exp is None:
    raise RuntimeError(
        f"No experiment {TRACE_EXPERIMENT}; run job_deploy_contract_agent first "
        "(it sets this experiment before log_model, wiring the endpoint's trace store).")
res["endpoint_experiment_id"] = exp.experiment_id
mlflow.set_experiment(experiment_id=exp.experiment_id)


def _reg(scorer, name, rate):
    try:
        scorer.register(name=name).start(sampling_config=ScorerSamplingConfig(sample_rate=rate))
        return f"OK (sample={rate})"
    except Exception as e:                                    # already-registered or unavailable
        return f"{type(e).__name__}: {str(e)[:200]}"


# built-in safety on every trace
res["safety"] = _reg(Safety(), "contract_safety", 1.0)
# on-brand: contract answers must be grounded in retrieved chunks and cite them
res["grounded"] = _reg(
    Guidelines(name="grounded", guidelines=[
        "Every claim about contract terms must be supported by a retrieved chunk in the "
        "tool/context; the assistant must not invent clauses, dates, or figures.",
        "Answers should cite the source contract/section they draw from."]),
    "contract_grounded", 0.5)

dbutils.notebook.exit(json.dumps(res, indent=2))          # noqa: F821
