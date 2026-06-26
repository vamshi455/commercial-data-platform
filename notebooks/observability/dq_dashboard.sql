-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Data Quality — DLT Expectation Pass/Fail
-- MAGIC Reads the Lakeflow Declarative Pipelines (DLT) **event log** to report
-- MAGIC expectation outcomes by pipeline and rule. Point the `pipeline_id`
-- MAGIC widget at the pipeline whose event log you want, or query the published
-- MAGIC `event_log` table if your pipeline materializes one.

-- COMMAND ----------

CREATE WIDGET TEXT pipeline_id DEFAULT '';
CREATE WIDGET TEXT lookback_hours DEFAULT '168';

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Flatten expectation records from `flow_progress` events
-- MAGIC Each `flow_progress` event carries `data_quality.expectations`, an array
-- MAGIC of `{name, dataset, passed_records, failed_records}`.

-- COMMAND ----------

WITH events AS (
  SELECT
    timestamp,
    event_type,
    details:flow_progress.data_quality.expectations AS expectations
  FROM event_log(TABLE(IDENTIFIER(:pipeline_id)))
  WHERE event_type = 'flow_progress'
    AND timestamp >= current_timestamp() - make_interval(0, 0, 0, 0, int(:lookback_hours))
),
exploded AS (
  SELECT
    e.timestamp,
    x.name             AS expectation_name,
    x.dataset          AS dataset,
    coalesce(x.passed_records, 0) AS passed_records,
    coalesce(x.failed_records, 0) AS failed_records
  FROM events e
  LATERAL VIEW explode(from_json(e.expectations,
        'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) AS x
)
SELECT
  dataset,
  expectation_name,
  sum(passed_records)                                   AS passed,
  sum(failed_records)                                   AS failed,
  round(100.0 * sum(passed_records)
        / nullif(sum(passed_records) + sum(failed_records), 0), 2) AS pass_pct
FROM exploded
GROUP BY dataset, expectation_name
ORDER BY failed DESC, pass_pct ASC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Rules currently failing (failed_records > 0)

-- COMMAND ----------

WITH events AS (
  SELECT
    timestamp,
    details:flow_progress.data_quality.expectations AS expectations
  FROM event_log(TABLE(IDENTIFIER(:pipeline_id)))
  WHERE event_type = 'flow_progress'
    AND timestamp >= current_timestamp() - make_interval(0, 0, 0, 0, int(:lookback_hours))
),
exploded AS (
  SELECT
    e.timestamp,
    x.name AS expectation_name,
    x.dataset AS dataset,
    coalesce(x.failed_records, 0) AS failed_records
  FROM events e
  LATERAL VIEW explode(from_json(e.expectations,
        'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) AS x
)
SELECT dataset, expectation_name, max(timestamp) AS last_seen, sum(failed_records) AS failed_records
FROM exploded
WHERE failed_records > 0
GROUP BY dataset, expectation_name
ORDER BY failed_records DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Pipeline-level error events (last lookback window)

-- COMMAND ----------

SELECT timestamp, event_type, level, message
FROM event_log(TABLE(IDENTIFIER(:pipeline_id)))
WHERE level IN ('ERROR', 'WARN')
  AND timestamp >= current_timestamp() - make_interval(0, 0, 0, 0, int(:lookback_hours))
ORDER BY timestamp DESC;
