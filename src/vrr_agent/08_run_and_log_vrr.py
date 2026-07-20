# Databricks notebook source
# MAGIC %md
# MAGIC # VRR — run the build AND log the SQL (executor + logger)
# MAGIC
# MAGIC Databricks port of the Snowflake **executor → logger** flow (vrr_executor.sql +
# MAGIC vrr_logger.sql): run `vrr_build.sql`, then write the **actual SQL that ran** into
# MAGIC `vrr_agent.pattern_vrr_log` (per asset + grain + run_id) — so the agent can later
# MAGIC retrieve it (VRR_EXPLAIN_CALC) and explain "how VRR is calculated" from source.
# MAGIC Idempotent; retains 1 month of logs (like the Snowflake logger).

# COMMAND ----------
import datetime as dt, json, os
from src.vrr_agent.config import from_widgets

cfg = from_widgets(dbutils)                                   # noqa: F821
def _w(name, default=""):
    try:
        dbutils.widgets.text(name, default)                   # noqa: F821
        return dbutils.widgets.get(name) or default           # noqa: F821
    except Exception:
        return default

ASSET = _w("asset_name", "CDP_VRR")
RUN_ID = _w("run_id", "") or f"build-{dt.datetime.utcnow().isoformat(timespec='seconds')}"
ROOT = _w("source_root", "")

BUILD_SQL = os.path.join(ROOT, "src", "vrr_agent", "vrr_build.sql") if ROOT \
    else os.path.abspath("vrr_build.sql")

# COMMAND ----------
# --- read + run the build (substitute catalog/run_id, split, execute) ----------
sql = open(BUILD_SQL).read().replace("${catalog}", cfg.catalog).replace("${run_id}", RUN_ID)


def split_sql(text):
    lines, out = [], []
    for ln in text.splitlines():
        i = ln.find("--")
        lines.append(ln[:i] if i >= 0 else ln)
    buf, instr = [], False
    for ch in "\n".join(lines):
        if ch == "'":
            instr = not instr
        if ch == ";" and not instr:
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


for stmt in split_sql(sql):
    spark.sql(stmt)                                           # noqa: F821
print("VRR build complete · run", RUN_ID)

# --- also rebuild the value-level lineage graph (06) from the fresh curated data --
GRAPH_SQL = os.path.join(ROOT, "src", "vrr_agent", "06_build_lineage_graph.sql") if ROOT \
    else os.path.abspath("06_build_lineage_graph.sql")
gsql = open(GRAPH_SQL).read().replace("${catalog}", cfg.catalog).replace("${run_id}", RUN_ID)
for stmt in split_sql(gsql):
    spark.sql(stmt)                                           # noqa: F821
print("lineage graph rebuilt")

# COMMAND ----------
# --- log the SQL used, one row per grain (mirrors PATTERN_VRR_LOG) --------------
from pyspark.sql import Row  # noqa: E402

now = dt.datetime.utcnow()
rows = []
for agg, tbl in (("Monthly", cfg.pattern_vrr_monthly), ("Daily", cfg.pattern_vrr_daily)):
    rc = spark.table(tbl).count()                            # noqa: F821
    rows.append(Row(log_ts=now, log_date=now.date(), run_id=RUN_ID, step="SQL_GENERATED",
                    row_count=rc, error_text=None, load_type="full", history_months=12,
                    aggregation_type=agg, uom="OilField", asset_name=ASSET,
                    params_json=json.dumps({"catalog": cfg.catalog, "grain": agg}),
                    sql_text=sql))
spark.createDataFrame(rows).write.mode("append").saveAsTable(f"{cfg.catalog}.vrr_agent.pattern_vrr_log")  # noqa: F821

# retain 1 month (Snowflake logger parity)
spark.sql(f"DELETE FROM {cfg.catalog}.vrr_agent.pattern_vrr_log "                # noqa: F821
          "WHERE log_ts < current_timestamp() - INTERVAL 1 MONTH")
print("logged transformation SQL for", ASSET, "· grains: Monthly, Daily")
