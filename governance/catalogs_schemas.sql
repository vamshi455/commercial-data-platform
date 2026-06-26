-- =============================================================================
-- governance/catalogs_schemas.sql
-- -----------------------------------------------------------------------------
-- Creates the per-environment Unity Catalog, its schemas, and the landing
-- Volume for the Commercial Data Platform.
--
-- PARAMETERIZATION
--   This script is run once per environment (dev / qa / prod) by the
--   platform-setup job. The target catalog is supplied as ${catalog}
--   (e.g. cdp_dev, cdp_qa, cdp_prod) and the job runs:
--       USE CATALOG ${catalog};
--   The setup notebook (notebooks/setup/00_create_catalogs_schemas.sql) reads
--   a `catalog` widget and substitutes it for ${catalog} below.
--
-- PRIVILEGES REQUIRED
--   * CREATE CATALOG requires the METASTORE ADMIN role (or CREATE CATALOG on
--     the metastore). Run the catalog-creation block as a metastore admin.
--   * The remaining schema/volume DDL only needs ownership of the catalog.
--
-- SANDBOX
--   The `sandbox` schema is created ONLY in dev. The setup notebook guards it
--   behind a check on the catalog name; in raw SQL the sandbox block is at the
--   bottom and should be skipped for qa/prod.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Catalog (metastore admin)
-- ---------------------------------------------------------------------------
CREATE CATALOG IF NOT EXISTS ${catalog}
  COMMENT 'Commercial Data Platform — environment catalog (medallion: landing/bronze/silver/gold/ops).';

USE CATALOG ${catalog};

-- ---------------------------------------------------------------------------
-- 2. Schemas (medallion layers + ops)
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- 3. Landing Volume (source file drop zone)
-- ---------------------------------------------------------------------------
-- Managed volume backing ${var.landing_volume} = /Volumes/${catalog}/landing/files
CREATE VOLUME IF NOT EXISTS landing.files
  COMMENT 'Drop zone for synthetic/source CRM & ERP files consumed by Auto Loader ingestion pipelines.';

-- ---------------------------------------------------------------------------
-- 4. Sandbox (DEV ONLY)
-- ---------------------------------------------------------------------------
-- Run this block ONLY when ${catalog} = cdp_dev. The setup notebook gates it
-- on the widget value; do not execute against qa/prod.
CREATE SCHEMA IF NOT EXISTS sandbox
  COMMENT 'DEV ONLY — free experimentation area for engineers. Not promoted to qa/prod.';
