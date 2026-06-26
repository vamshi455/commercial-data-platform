-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Table Freshness vs SLA
-- MAGIC Tracks when each curated table was last updated and flags tables that
-- MAGIC have breached their domain freshness SLA. Sourced from Unity Catalog
-- MAGIC `information_schema` (last_altered) for the current target catalog.
-- MAGIC
-- MAGIC Set the catalog widget to cdp_dev / cdp_qa / cdp_prod.

-- COMMAND ----------

-- Catalog parameter (defaults to dev). Override via the notebook widget.
CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Per-table last-altered timestamp and age (hours)

-- COMMAND ----------

USE CATALOG IDENTIFIER(:catalog);

SELECT
  table_schema                                                AS domain,
  table_name,
  table_type,
  last_altered,
  round((unix_timestamp(current_timestamp()) - unix_timestamp(last_altered)) / 3600.0, 1)
                                                              AS age_hours
FROM information_schema.tables
WHERE table_schema IN ('bronze', 'silver', 'gold', 'ops')
ORDER BY age_hours DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Freshness SLA breach by domain
-- MAGIC SLA hours per domain are expressed inline; adjust to your contracts.

-- COMMAND ----------

WITH sla(domain, sla_hours) AS (
  VALUES ('bronze', 6), ('silver', 12), ('gold', 24), ('ops', 24)
),
t AS (
  SELECT
    table_schema AS domain,
    table_name,
    last_altered,
    (unix_timestamp(current_timestamp()) - unix_timestamp(last_altered)) / 3600.0 AS age_hours
  FROM information_schema.tables
  WHERE table_schema IN ('bronze', 'silver', 'gold', 'ops')
)
SELECT
  t.domain,
  t.table_name,
  round(t.age_hours, 1)             AS age_hours,
  sla.sla_hours,
  CASE WHEN t.age_hours > sla.sla_hours THEN 'BREACH' ELSE 'OK' END AS sla_status
FROM t
JOIN sla USING (domain)
ORDER BY (t.age_hours - sla.sla_hours) DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Domain rollup: how many tables are stale?

-- COMMAND ----------

WITH sla(domain, sla_hours) AS (
  VALUES ('bronze', 6), ('silver', 12), ('gold', 24), ('ops', 24)
)
SELECT
  it.table_schema AS domain,
  count(*)        AS tables,
  sum(CASE
        WHEN (unix_timestamp(current_timestamp()) - unix_timestamp(it.last_altered)) / 3600.0
             > sla.sla_hours THEN 1 ELSE 0 END) AS breaching,
  max(it.last_altered) AS most_recent_update
FROM information_schema.tables it
JOIN sla ON sla.domain = it.table_schema
GROUP BY it.table_schema
ORDER BY breaching DESC;
