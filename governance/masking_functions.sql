-- =============================================================================
-- governance/masking_functions.sql
-- -----------------------------------------------------------------------------
-- Column-mask UDFs + ALTER COLUMN ... SET MASK bindings for PII/sensitive
-- fields across silver and gold. Run once per environment (USE CATALOG ${catalog}).
--
-- HOW MASKING WORKS
--   A column mask is a SQL UDF whose FIRST argument is the column value. When
--   bound via ALTER TABLE ... ALTER COLUMN col SET MASK fn, UC calls the UDF on
--   every read and substitutes its return value. The UDF uses
--   is_account_group_member('<group>') to let privileged groups (data_stewards,
--   platform_engineers, plus role-appropriate groups) see clear text while
--   everyone else gets a redacted value.
--
-- PRIVILEGES
--   Functions are created in the gold schema and reused by silver/gold tables.
--   Personas that read masked tables need EXECUTE on these functions (granted
--   at schema level in grants.sql).
-- =============================================================================

USE CATALOG ${catalog};
USE SCHEMA gold;

-- ---------------------------------------------------------------------------
-- 1. mask_email — keep domain, redact local part. Clear for stewards/platform.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.mask_email(email STRING)
  RETURNS STRING
  COMMENT 'Column mask: redacts the local part of an email unless caller is a privileged group.'
  RETURN
    CASE
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN email
      WHEN email IS NULL OR instr(email, '@') = 0 THEN '****'
      ELSE concat('****@', split_part(email, '@', 2))
    END;

-- ---------------------------------------------------------------------------
-- 2. mask_phone — keep last 4 digits, redact the rest.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.mask_phone(phone STRING)
  RETURNS STRING
  COMMENT 'Column mask: shows only the last 4 digits of a phone number for non-privileged callers.'
  RETURN
    CASE
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN phone
      WHEN phone IS NULL OR length(regexp_replace(phone, '[^0-9]', '')) < 4 THEN '***-****'
      ELSE concat('***-***-', right(regexp_replace(phone, '[^0-9]', ''), 4))
    END;

-- ---------------------------------------------------------------------------
-- 3. mask_tax_id — show only last 4. Finance + stewards see full.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.mask_tax_id(tax_id STRING)
  RETURNS STRING
  COMMENT 'Column mask: financial_sensitive — shows last 4 of a tax/EIN/SSN; full for finance & stewards.'
  RETURN
    CASE
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_finance_analysts')
      THEN tax_id
      WHEN tax_id IS NULL OR length(tax_id) < 4 THEN '****'
      ELSE concat('***-**-', right(tax_id, 4))
    END;

-- ---------------------------------------------------------------------------
-- 4. mask_free_text — fully redact restricted free text for non-stewards.
-- ---------------------------------------------------------------------------
-- Free-text fields (support notes, account comments) may contain unstructured
-- PII; only data_stewards (and platform engineers) may read them in the clear.
CREATE OR REPLACE FUNCTION gold.mask_free_text(txt STRING)
  RETURNS STRING
  COMMENT 'Column mask: restricted_free_text — redacts unstructured notes unless caller is a steward/platform.'
  RETURN
    CASE
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
      THEN txt
      WHEN txt IS NULL THEN NULL
      ELSE '[REDACTED]'
    END;

-- ===========================================================================
-- BIND MASKS — ALTER COLUMN ... SET MASK examples
-- ---------------------------------------------------------------------------
-- silver layer (source-of-truth entities)
-- ---------------------------------------------------------------------------
ALTER TABLE silver.crm_contacts  ALTER COLUMN email    SET MASK gold.mask_email;
ALTER TABLE silver.crm_contacts  ALTER COLUMN phone    SET MASK gold.mask_phone;
ALTER TABLE silver.crm_accounts  ALTER COLUMN tax_id   SET MASK gold.mask_tax_id;
ALTER TABLE silver.erp_invoices  ALTER COLUMN tax_id   SET MASK gold.mask_tax_id;

-- ---------------------------------------------------------------------------
-- gold layer (serving marts)
-- ---------------------------------------------------------------------------
ALTER TABLE gold.customer_360 ALTER COLUMN primary_email SET MASK gold.mask_email;
ALTER TABLE gold.customer_360 ALTER COLUMN primary_phone SET MASK gold.mask_phone;
ALTER TABLE gold.customer_360 ALTER COLUMN tax_id        SET MASK gold.mask_tax_id;
ALTER TABLE gold.support_performance ALTER COLUMN last_case_notes SET MASK gold.mask_free_text;
ALTER TABLE gold.account_health      ALTER COLUMN steward_notes   SET MASK gold.mask_free_text;

-- To remove a mask (e.g. when refactoring a column):
--   ALTER TABLE gold.customer_360 ALTER COLUMN primary_email DROP MASK;
