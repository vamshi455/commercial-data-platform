-- =============================================================================
-- governance/masking_functions.sql
-- -----------------------------------------------------------------------------
-- Column-mask UDFs + ALTER COLUMN ... SET MASK bindings for PII/sensitive
-- fields across silver and gold. Run once per environment (USE CATALOG ${catalog}).
--
-- ⚠️ RECONCILED 2026-06-29. Two parts:
--   PART A — UDF definitions. Independent objects; SAFE TO APPLY NOW.
--   PART B — mask BINDINGS. Target the PII columns promoted into silver/gold by
--            the pipeline (Track A). Apply ONLY AFTER those columns exist
--            (silver.silver_contact.work_email/mobile_phone; gold.gold_customer_360
--            .primary_email/primary_phone/tax_id). Until then they ERROR (no column).
--
-- HOW MASKING WORKS: a column mask is a SQL UDF whose first arg is the column
--   value; bound via ALTER COLUMN ... SET MASK, UC calls it on every read.
--   is_account_group_member('<group>') lets privileged groups see clear text.
-- =============================================================================

USE CATALOG ${catalog};
USE SCHEMA gold;

-- ###########################################################################
-- PART A — UDF DEFINITIONS  (safe to apply now)
-- ###########################################################################

-- is_prod — environment guard. Masks short-circuit on this: STRICT in prod,
-- RELAXED on synthetic dev/qa data. ${env} is baked in at create time.
-- (To test masking in dev, deploy with env='prod' semantics or change predicate.)
CREATE OR REPLACE FUNCTION gold.is_prod()
  RETURNS BOOLEAN
  COMMENT 'Environment guard: TRUE only in prod (baked from bundle target). Masks/row-filters enforce when TRUE, relax otherwise.'
  RETURN '${env}' = 'prod';

-- mask_email — keep domain, redact local part. Clear for stewards/platform/CS.
CREATE OR REPLACE FUNCTION gold.mask_email(email STRING)
  RETURNS STRING
  COMMENT 'Column mask (pii): redacts local part of an email unless caller is steward/platform/customer_success. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN email
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN email
      WHEN email IS NULL OR instr(email, '@') = 0 THEN '****'
      ELSE concat('****@', split_part(email, '@', 2))
    END;

-- mask_phone — keep last 4 digits. Clear for stewards/platform/CS.
CREATE OR REPLACE FUNCTION gold.mask_phone(phone STRING)
  RETURNS STRING
  COMMENT 'Column mask (pii): shows only last 4 digits for non-privileged callers, clear for steward/platform/customer_success. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN phone
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_customer_success')
      THEN phone
      WHEN phone IS NULL OR length(regexp_replace(phone, '[^0-9]', '')) < 4 THEN '***-****'
      ELSE concat('***-***-', right(regexp_replace(phone, '[^0-9]', ''), 4))
    END;

-- mask_tax_id — show only last 4. Clear for finance + stewards/platform.
CREATE OR REPLACE FUNCTION gold.mask_tax_id(tax_id STRING)
  RETURNS STRING
  COMMENT 'Column mask (financial_sensitive): shows last 4 of a tax/EIN, full for finance & stewards/platform. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN tax_id
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
        OR is_account_group_member('cdp_finance_analysts')
      THEN tax_id
      WHEN tax_id IS NULL OR length(tax_id) < 4 THEN '****'
      ELSE concat('***-**-', right(tax_id, 4))
    END;

-- mask_free_text — fully redact restricted free text for non-stewards.
-- (No free-text columns are bound in the current model; kept for future notes fields.)
CREATE OR REPLACE FUNCTION gold.mask_free_text(txt STRING)
  RETURNS STRING
  COMMENT 'Column mask (restricted_free_text): redacts unstructured notes unless steward/platform. Relaxed in non-prod.'
  RETURN
    CASE
      WHEN NOT gold.is_prod() THEN txt
      WHEN is_account_group_member('cdp_data_stewards')
        OR is_account_group_member('cdp_platform_engineers')
      THEN txt
      WHEN txt IS NULL THEN NULL
      ELSE '[REDACTED]'
    END;

-- ###########################################################################
-- PART B — MASK BINDINGS  (apply ONLY AFTER the pipeline promotes these columns)
-- ###########################################################################
-- SILVER — conformed contact entity (added by the silver pipeline; Track A).
-- ALTER TABLE silver.silver_contact ALTER COLUMN work_email   SET MASK gold.mask_email;
-- ALTER TABLE silver.silver_contact ALTER COLUMN mobile_phone SET MASK gold.mask_phone;

-- GOLD — customer_360 carries the minimal action-need PII (email/phone for
-- outreach, tax_id for finance). NOTE: gold.gold_customer_360 is a DLT
-- materialized view; SET MASK on it must be declared in the pipeline (the MV
-- definition) so a full refresh does not drop the binding.
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN primary_email SET MASK gold.mask_email;
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN primary_phone SET MASK gold.mask_phone;
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN tax_id        SET MASK gold.mask_tax_id;

-- To remove a mask: ALTER TABLE ... ALTER COLUMN col DROP MASK;
