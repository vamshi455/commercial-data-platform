-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 00 — Create Catalog, Schemas & Volume
-- MAGIC Wraps `governance/catalogs_schemas.sql`. Reads a `catalog` widget
-- MAGIC (passed by `job_platform_setup` from `${var.catalog}`) and provisions the
-- MAGIC medallion schemas + landing volume for the target environment.
-- MAGIC
-- MAGIC **Requires metastore-admin** for `CREATE CATALOG`. The `sandbox` schema is
-- MAGIC created only when the catalog is `cdp_dev`.

-- COMMAND ----------

-- Widget so the notebook is environment-agnostic; default to dev.
CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';

-- COMMAND ----------

-- DBTITLE 1,Catalog (metastore admin)
CREATE CATALOG IF NOT EXISTS IDENTIFIER(:catalog)
  COMMENT 'Commercial Data Platform — environment catalog (medallion: landing/bronze/silver/gold/ops).';

-- COMMAND ----------

USE CATALOG IDENTIFIER(:catalog);

-- COMMAND ----------

-- DBTITLE 1,Schemas
CREATE SCHEMA IF NOT EXISTS landing
  COMMENT 'Raw source files and external/volume-backed landing tables. Pre-validation, transient.';
CREATE SCHEMA IF NOT EXISTS bronze
  COMMENT 'Raw ingested CRM/ERP/reference data as Delta. Append-only, source-faithful.';
CREATE SCHEMA IF NOT EXISTS silver
  COMMENT 'Cleansed, conformed, deduplicated entities. Business keys enforced, PII present (masked via policies).';
CREATE SCHEMA IF NOT EXISTS gold
  COMMENT 'Curated analytics marts and serving views: customer_360, revenue_pipeline, collections_risk, etc.';
CREATE SCHEMA IF NOT EXISTS ops
  COMMENT 'Operational metadata: pipeline audit, data-quality results, run logs, governance bookkeeping.';

-- COMMAND ----------

-- DBTITLE 1,Landing volume
CREATE VOLUME IF NOT EXISTS landing.files
  COMMENT 'Drop zone for synthetic/source CRM & ERP files consumed by Auto Loader ingestion pipelines.';

-- COMMAND ----------

-- DBTITLE 1,Sandbox (DEV ONLY)
-- MAGIC %python
-- MAGIC # Gate the sandbox schema on the dev catalog only.
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC if catalog == "cdp_dev":
-- MAGIC     spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.sandbox "
-- MAGIC               f"COMMENT 'DEV ONLY — free experimentation area for engineers. Not promoted to qa/prod.'")
-- MAGIC     print(f"Created sandbox schema in {catalog}.")
-- MAGIC else:
-- MAGIC     print(f"Skipping sandbox schema for non-dev catalog: {catalog}.")
