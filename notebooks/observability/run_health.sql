-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Job / Pipeline Run Health & SLA Breaches
-- MAGIC Reads `system.lakeflow.job_run_timeline` (and task timeline) to show run
-- MAGIC status, durations, failures, and SLA breaches. Requires the system
-- MAGIC `lakeflow` schema to be enabled for the workspace.

-- COMMAND ----------

CREATE WIDGET TEXT lookback_days DEFAULT '7';
CREATE WIDGET TEXT sla_minutes DEFAULT '60';

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Recent run outcomes

-- COMMAND ----------

SELECT
  job_id,
  run_id,
  run_name,
  result_state,
  termination_code,
  period_start_time,
  period_end_time,
  timestampdiff(MINUTE, period_start_time, period_end_time) AS duration_min
FROM system.lakeflow.job_run_timeline
WHERE period_end_time >= current_timestamp() - make_interval(0, 0, 0, int(:lookback_days))
ORDER BY period_end_time DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Failed runs only

-- COMMAND ----------

SELECT
  job_id, run_id, run_name, result_state, termination_code,
  period_start_time, period_end_time
FROM system.lakeflow.job_run_timeline
WHERE period_end_time >= current_timestamp() - make_interval(0, 0, 0, int(:lookback_days))
  AND result_state IN ('FAILED', 'TIMEDOUT', 'ERROR', 'CANCELED')
ORDER BY period_end_time DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## SLA breaches — runs longer than the SLA threshold

-- COMMAND ----------

SELECT
  job_id,
  run_name,
  run_id,
  result_state,
  period_start_time,
  period_end_time,
  timestampdiff(MINUTE, period_start_time, period_end_time) AS duration_min,
  int(:sla_minutes)                                         AS sla_minutes
FROM system.lakeflow.job_run_timeline
WHERE period_end_time >= current_timestamp() - make_interval(0, 0, 0, int(:lookback_days))
  AND timestampdiff(MINUTE, period_start_time, period_end_time) > int(:sla_minutes)
ORDER BY duration_min DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Per-job reliability rollup (success rate + p95 duration)

-- COMMAND ----------

SELECT
  job_id,
  count(*)                                                       AS runs,
  sum(CASE WHEN result_state = 'SUCCEEDED' THEN 1 ELSE 0 END)    AS succeeded,
  round(100.0 * sum(CASE WHEN result_state = 'SUCCEEDED' THEN 1 ELSE 0 END)
        / nullif(count(*), 0), 2)                                AS success_pct,
  round(percentile(timestampdiff(MINUTE, period_start_time, period_end_time), 0.95), 1)
                                                                 AS p95_duration_min
FROM system.lakeflow.job_run_timeline
WHERE period_end_time >= current_timestamp() - make_interval(0, 0, 0, int(:lookback_days))
GROUP BY job_id
ORDER BY success_pct ASC;
