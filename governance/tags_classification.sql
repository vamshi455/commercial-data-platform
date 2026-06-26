-- =============================================================================
-- governance/tags_classification.sql
-- -----------------------------------------------------------------------------
-- Data classification via Unity Catalog tags (SET TAGS). Applies the platform's
-- sensitivity taxonomy to representative tables and columns across the medallion
-- layers. Run once per environment (USE CATALOG ${catalog}).
--
-- GOVERNED TAG POLICY
--   Tag key:   sensitivity
--   Allowed values (the platform's sensitivity classes):
--     public_reference      — non-sensitive reference/lookup data, freely shareable
--     internal_only         — internal business data, not for external sharing
--     pii                   — personal identifiers (name/email/phone/address)
--     financial_sensitive   — tax ids, bank/payment, invoice financials
--     restricted_free_text  — unstructured notes that may embed any of the above
--   Stewards own this taxonomy (APPLY TAG granted in grants.sql). Masking and
--   row-filter policies are bound to columns carrying pii / financial_sensitive
--   / restricted_free_text tags. Treat tags as the contract that drives policy.
--
-- PRIVILEGES: APPLY TAG on the object (data_stewards / platform_engineers).
-- =============================================================================

USE CATALOG ${catalog};

-- ---------------------------------------------------------------------------
-- BRONZE — source-faithful; tag tables + the raw sensitive columns.
-- ---------------------------------------------------------------------------
ALTER TABLE bronze.crm_accounts SET TAGS ('sensitivity' = 'internal_only', 'layer' = 'bronze', 'domain' = 'crm');
ALTER TABLE bronze.crm_contacts SET TAGS ('sensitivity' = 'pii',           'layer' = 'bronze', 'domain' = 'crm');
ALTER TABLE bronze.erp_invoices SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'bronze', 'domain' = 'erp');
ALTER TABLE bronze.erp_payments SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'bronze', 'domain' = 'erp');

ALTER TABLE bronze.crm_contacts ALTER COLUMN email   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE bronze.crm_contacts ALTER COLUMN phone   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE bronze.crm_accounts ALTER COLUMN tax_id  SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE bronze.erp_invoices ALTER COLUMN tax_id  SET TAGS ('sensitivity' = 'financial_sensitive');

-- ---------------------------------------------------------------------------
-- SILVER — conformed entities carrying PII (masked by policy).
-- ---------------------------------------------------------------------------
ALTER TABLE silver.crm_contacts ALTER COLUMN email  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE silver.crm_contacts ALTER COLUMN phone  SET TAGS ('sensitivity' = 'pii');
ALTER TABLE silver.crm_accounts ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE silver.erp_invoices ALTER COLUMN tax_id SET TAGS ('sensitivity' = 'financial_sensitive');

-- ---------------------------------------------------------------------------
-- GOLD — serving marts; tag tables + the sensitive serving columns.
-- ---------------------------------------------------------------------------
ALTER TABLE gold.customer_360        SET TAGS ('sensitivity' = 'pii',                 'layer' = 'gold');
ALTER TABLE gold.revenue_pipeline    SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');
ALTER TABLE gold.bookings_vs_billings SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'gold');
ALTER TABLE gold.collections_risk    SET TAGS ('sensitivity' = 'financial_sensitive', 'layer' = 'gold');
ALTER TABLE gold.support_performance SET TAGS ('sensitivity' = 'restricted_free_text', 'layer' = 'gold');
ALTER TABLE gold.account_health      SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');
ALTER TABLE gold.renewal_risk        SET TAGS ('sensitivity' = 'internal_only',       'layer' = 'gold');

ALTER TABLE gold.customer_360        ALTER COLUMN primary_email   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE gold.customer_360        ALTER COLUMN primary_phone   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE gold.customer_360        ALTER COLUMN tax_id          SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE gold.support_performance ALTER COLUMN last_case_notes SET TAGS ('sensitivity' = 'restricted_free_text');
ALTER TABLE gold.account_health      ALTER COLUMN steward_notes   SET TAGS ('sensitivity' = 'restricted_free_text');

-- ---------------------------------------------------------------------------
-- PUBLIC REFERENCE — lookup/dimension data with no sensitivity.
-- ---------------------------------------------------------------------------
ALTER TABLE bronze.ref_currency_rates SET TAGS ('sensitivity' = 'public_reference', 'layer' = 'bronze', 'domain' = 'reference');
ALTER TABLE bronze.ref_country_codes  SET TAGS ('sensitivity' = 'public_reference', 'layer' = 'bronze', 'domain' = 'reference');

-- To inspect applied tags:
--   SELECT * FROM ${catalog}.information_schema.table_tags;
--   SELECT * FROM ${catalog}.information_schema.column_tags;
