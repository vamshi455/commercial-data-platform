-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 02 — Masking, Row Filters & Classification Tags
-- MAGIC Wraps `governance/masking_functions.sql`, `governance/row_filters.sql`,
-- MAGIC and `governance/tags_classification.sql`. Creates the masking + row-filter
-- MAGIC UDFs, binds them to silver/gold columns, and applies the `sensitivity` tag
-- MAGIC taxonomy.
-- MAGIC
-- MAGIC **Run after the first pipeline run** so the silver/gold tables that get
-- MAGIC `SET MASK` / `SET ROW FILTER` / `SET TAGS` exist.

-- COMMAND ----------

CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';
-- env is passed by job_platform_setup (= bundle target). Drives the prod-strict guard.
CREATE WIDGET TEXT env DEFAULT 'dev';
USE CATALOG IDENTIFIER(:catalog);
USE SCHEMA gold;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Environment guard — `gold.is_prod()`
-- MAGIC Every mask and row filter short-circuits on this function: **strict in
-- MAGIC `cdp_prod`, relaxed on synthetic dev/qa data** so engineers can iterate
-- MAGIC without fighting masks. The deploy target is *baked in as a literal* at
-- MAGIC create time (a column-mask UDF body can't read session params), so the
-- MAGIC guard cannot be flipped at query time.
-- MAGIC
-- MAGIC To make QA strict too, change the baked value to `env in ('qa','prod')`.

-- COMMAND ----------

-- MAGIC %python
-- MAGIC env = dbutils.widgets.get("env")
-- MAGIC catalog = dbutils.widgets.get("catalog")
-- MAGIC # Relax everywhere except prod. Flip to `env in ("qa", "prod")` for qa-strict.
-- MAGIC is_prod_literal = "true" if env == "prod" else "false"
-- MAGIC spark.sql(f"""
-- MAGIC   CREATE OR REPLACE FUNCTION {catalog}.gold.is_prod()
-- MAGIC     RETURNS BOOLEAN
-- MAGIC     COMMENT 'Environment guard: TRUE only in prod (baked at deploy time from the bundle target). Masks/row-filters enforce when TRUE and relax on synthetic dev/qa data.'
-- MAGIC     RETURN {is_prod_literal}
-- MAGIC """)
-- MAGIC print(f"gold.is_prod() = {is_prod_literal}  (env={env}, catalog={catalog})")

-- COMMAND ----------

-- MAGIC %md ## Masking UDFs
-- MAGIC Pattern: `WHEN NOT gold.is_prod() THEN <clear>` relaxes non-prod; the
-- MAGIC privileged-group and redaction branches only ever apply in prod.

-- COMMAND ----------

-- DBTITLE 1,mask_email
CREATE OR REPLACE FUNCTION gold.mask_email(email STRING)
  RETURNS STRING
  COMMENT 'Column mask: redacts the local part of an email unless caller is a privileged group. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN email          -- dev/qa: synthetic data, unmasked
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN email
      WHEN email IS NULL OR instr(email, '@') = 0 THEN '****'
      ELSE concat('****@', split_part(email, '@', 2))
    END;

-- COMMAND ----------

-- DBTITLE 1,mask_phone
CREATE OR REPLACE FUNCTION gold.mask_phone(phone STRING)
  RETURNS STRING
  COMMENT 'Column mask: shows only the last 4 digits of a phone number for non-privileged callers. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN phone          -- dev/qa: synthetic data, unmasked
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN phone
      WHEN phone IS NULL OR length(regexp_replace(phone, '[^0-9]', '')) < 4 THEN '***-****'
      ELSE concat('***-***-', right(regexp_replace(phone, '[^0-9]', ''), 4))
    END;

-- COMMAND ----------

-- DBTITLE 1,mask_tax_id
CREATE OR REPLACE FUNCTION gold.mask_tax_id(tax_id STRING)
  RETURNS STRING
  COMMENT 'Column mask: financial_sensitive — shows last 4 of a tax/EIN/SSN; full for finance & stewards. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN tax_id         -- dev/qa: synthetic data, unmasked
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_finance_analysts')
      THEN tax_id
      WHEN tax_id IS NULL OR length(tax_id) < 4 THEN '****'
      ELSE concat('***-**-', right(tax_id, 4))
    END;

-- COMMAND ----------

-- DBTITLE 1,mask_free_text
CREATE OR REPLACE FUNCTION gold.mask_free_text(txt STRING)
  RETURNS STRING
  COMMENT 'Column mask: restricted_free_text — redacts unstructured notes unless caller is a steward/platform. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN txt            -- dev/qa: synthetic data, unmasked
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
      THEN txt
      WHEN txt IS NULL THEN NULL
      ELSE '[REDACTED]'
    END;

-- COMMAND ----------

-- MAGIC %md ## Bind column masks (silver + gold)

-- COMMAND ----------

ALTER TABLE silver.crm_contacts  ALTER COLUMN email    SET MASK gold.mask_email;
ALTER TABLE silver.crm_contacts  ALTER COLUMN phone    SET MASK gold.mask_phone;
ALTER TABLE silver.crm_accounts  ALTER COLUMN tax_id   SET MASK gold.mask_tax_id;
ALTER TABLE silver.erp_invoices  ALTER COLUMN tax_id   SET MASK gold.mask_tax_id;

ALTER TABLE gold.customer_360 ALTER COLUMN primary_email SET MASK gold.mask_email;
ALTER TABLE gold.customer_360 ALTER COLUMN primary_phone SET MASK gold.mask_phone;
ALTER TABLE gold.customer_360 ALTER COLUMN tax_id        SET MASK gold.mask_tax_id;
ALTER TABLE gold.support_performance ALTER COLUMN last_case_notes SET MASK gold.mask_free_text;
ALTER TABLE gold.account_health      ALTER COLUMN steward_notes   SET MASK gold.mask_free_text;

-- COMMAND ----------

-- MAGIC %md ## Row filter — territory_filter

-- COMMAND ----------

CREATE OR REPLACE FUNCTION gold.territory_filter(territory STRING)
  RETURNS BOOLEAN
  COMMENT 'Row filter: unrestricted for finance/stewards/platform; sales_analysts see only mapped territories. Relaxed (all rows) in non-prod.'
  RETURN
    NOT gold.is_prod()                            -- dev/qa: synthetic data, no row scoping
    OR is_account_group_member('cdp_data_stewards')
    OR is_account_group_member('cdp_platform_engineers')
    OR is_account_group_member('cdp_finance_analysts')
    OR is_account_group_member('cdp_analytics_engineers')
    OR (
      is_account_group_member('cdp_sales_analysts')
      AND territory IN (
        SELECT m.territory FROM ops.user_territory_map m
        WHERE m.user_email = current_user()
      )
    );

-- COMMAND ----------

ALTER TABLE gold.revenue_pipeline SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.customer_360     SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.account_health   SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.renewal_risk     SET ROW FILTER gold.territory_filter ON (territory);

-- COMMAND ----------

-- MAGIC %md ## Classification tags (sensitivity taxonomy)

-- COMMAND ----------

-- DBTITLE 1,Bronze
ALTER TABLE bronze.crm_accounts SET TAGS ('sensitivity' = 'internal_only', 'layer' = 'bronze', 'domain' = 'crm');
ALTER TABLE bronze.crm_contacts SET TAGS ('sensitivity' = 'pii',           'layer' = 'bronze', 'domain' = 'crm');
ALTER TABLE bronze.erp_invoices SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'bronze', 'domain' = 'erp');
ALTER TABLE bronze.erp_payments SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'bronze', 'domain' = 'erp');
ALTER TABLE bronze.crm_contacts ALTER COLUMN email  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE bronze.crm_contacts ALTER COLUMN phone  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE bronze.crm_accounts ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE bronze.erp_invoices ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE bronze.ref_currency_rates SET TAGS ('sensitivity' = 'public_reference', 'layer' = 'bronze', 'domain' = 'reference');
ALTER TABLE bronze.ref_country_codes  SET TAGS ('sensitivity' = 'public_reference', 'layer' = 'bronze', 'domain' = 'reference');

-- COMMAND ----------

-- DBTITLE 1,Silver
ALTER TABLE silver.crm_contacts ALTER COLUMN email  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE silver.crm_contacts ALTER COLUMN phone  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE silver.crm_accounts ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE silver.erp_invoices ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');

-- COMMAND ----------

-- DBTITLE 1,Gold
ALTER TABLE gold.customer_360         SET TAGS ('sensitivity' = 'pii',                 'layer' = 'gold');
ALTER TABLE gold.revenue_pipeline     SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');
ALTER TABLE gold.bookings_vs_billings SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'gold');
ALTER TABLE gold.collections_risk     SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'gold');
ALTER TABLE gold.support_performance  SET TAGS ('sensitivity' = 'restricted_free_text', 'layer' = 'gold');
ALTER TABLE gold.account_health       SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');
ALTER TABLE gold.renewal_risk         SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');
ALTER TABLE gold.customer_360         ALTER COLUMN primary_email   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE gold.customer_360         ALTER COLUMN primary_phone   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE gold.customer_360         ALTER COLUMN tax_id          SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE gold.support_performance  ALTER COLUMN last_case_notes SET TAGS ('sensitivity' = 'restricted_free_text');
ALTER TABLE gold.account_health       ALTER COLUMN steward_notes   SET TAGS ('sensitivity' = 'restricted_free_text');
