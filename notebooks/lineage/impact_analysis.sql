-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Lineage Impact Analysis — "What depends on X?"
-- MAGIC Uses Unity Catalog `system.access.table_lineage` and `column_lineage`
-- MAGIC to find downstream consumers (impact) and upstream sources (root cause)
-- MAGIC for a given table or column. Lineage requires UC system access tables
-- MAGIC to be enabled.

-- COMMAND ----------

CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';
CREATE WIDGET TEXT schema  DEFAULT 'silver';
CREATE WIDGET TEXT table   DEFAULT 'invoice';
CREATE WIDGET TEXT column  DEFAULT '';

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Direct downstream tables (1 hop) — immediate blast radius

-- COMMAND ----------

SELECT DISTINCT
  target_table_catalog AS catalog,
  target_table_schema  AS schema,
  target_table_name    AS table,
  entity_type,
  max(event_time)      AS last_seen
FROM system.access.table_lineage
WHERE source_table_catalog = :catalog
  AND source_table_schema  = :schema
  AND source_table_name    = :table
  AND target_table_name IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY schema, table;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Full downstream closure (multi-hop) — everything ultimately affected
-- MAGIC Recursively walks table_lineage from the source to all reachable targets.

-- COMMAND ----------

WITH RECURSIVE edges AS (
  SELECT DISTINCT
    source_table_catalog, source_table_schema, source_table_name,
    target_table_catalog, target_table_schema, target_table_name
  FROM system.access.table_lineage
  WHERE target_table_name IS NOT NULL
),
closure AS (
  SELECT
    target_table_catalog AS catalog, target_table_schema AS schema,
    target_table_name AS table, 1 AS hop
  FROM edges
  WHERE source_table_catalog = :catalog
    AND source_table_schema  = :schema
    AND source_table_name    = :table

  UNION ALL

  SELECT
    e.target_table_catalog, e.target_table_schema, e.target_table_name, c.hop + 1
  FROM edges e
  JOIN closure c
    ON e.source_table_catalog = c.catalog
   AND e.source_table_schema  = c.schema
   AND e.source_table_name    = c.table
  WHERE c.hop < 10
)
SELECT catalog, schema, table, min(hop) AS shortest_hop
FROM closure
GROUP BY catalog, schema, table
ORDER BY shortest_hop, schema, table;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Upstream sources (root-cause) for the target table

-- COMMAND ----------

SELECT DISTINCT
  source_table_catalog AS catalog,
  source_table_schema  AS schema,
  source_table_name    AS table,
  entity_type
FROM system.access.table_lineage
WHERE target_table_catalog = :catalog
  AND target_table_schema  = :schema
  AND target_table_name    = :table
  AND source_table_name IS NOT NULL
ORDER BY schema, table;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Column-level impact (set the `column` widget)
-- MAGIC Which downstream columns are derived from the chosen source column.

-- COMMAND ----------

SELECT DISTINCT
  target_table_catalog AS catalog,
  target_table_schema  AS schema,
  target_table_name    AS table,
  target_column_name   AS column
FROM system.access.column_lineage
WHERE source_table_catalog = :catalog
  AND source_table_schema  = :schema
  AND source_table_name    = :table
  AND (:column = '' OR source_column_name = :column)
  AND target_column_name IS NOT NULL
ORDER BY schema, table, column;
