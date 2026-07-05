-- =============================================================================
-- governance/tags_classification.sql
-- -----------------------------------------------------------------------------
-- Data classification via Unity Catalog tags (SET TAGS). Applies the platform's
-- sensitivity taxonomy across the medallion layers. Run with USE CATALOG ${catalog}.
--
-- ⚠️ RECONCILED 2026-06-29 to deployed names (bronze.bronze_*, silver.silver_*,
--   gold.gold_*) and real columns. Split into:
--     PART A — objects that exist NOW (ERP bronze, reference, gold/silver tables)
--     PART B — CRM bronze (re-created when the CRM cutover reload runs)
--     PART C — silver/gold PII COLUMNS (created by the pipeline PII promotion; Track A)
--
-- GOVERNED TAG: key 'sensitivity' ∈ {public_reference, internal_only, pii,
--   financial_sensitive, restricted_free_text}. Masking binds to columns
--   tagged pii / financial_sensitive. Stewards own the taxonomy (APPLY TAG).
-- =============================================================================

USE CATALOG ${catalog};

-- ###########################################################################
-- PART A — EXISTS NOW
-- ###########################################################################
-- ERP bronze (source-faithful; carries PII/financial). tax_id is pre-masked at
-- source (tax_id_masked) and contact email is also tokenized — defense in depth.
ALTER TABLE bronze.bronze_erp_customers SET TAGS ('sensitivity'='pii',                 'layer'='bronze','domain'='erp');
ALTER TABLE bronze.bronze_erp_invoices  SET TAGS ('sensitivity'='financial_sensitive', 'layer'='bronze','domain'='erp');
ALTER TABLE bronze.bronze_erp_payments  SET TAGS ('sensitivity'='financial_sensitive', 'layer'='bronze','domain'='erp');
ALTER TABLE bronze.bronze_erp_vendors   SET TAGS ('sensitivity'='financial_sensitive', 'layer'='bronze','domain'='erp');

ALTER TABLE bronze.bronze_erp_customers ALTER COLUMN payment_contact_email SET TAGS ('sensitivity'='pii');
ALTER TABLE bronze.bronze_erp_customers ALTER COLUMN billing_address       SET TAGS ('sensitivity'='pii');
ALTER TABLE bronze.bronze_erp_customers ALTER COLUMN phone                 SET TAGS ('sensitivity'='pii');
ALTER TABLE bronze.bronze_erp_customers ALTER COLUMN tax_id_masked         SET TAGS ('sensitivity'='financial_sensitive');
ALTER TABLE bronze.bronze_erp_invoices  ALTER COLUMN payment_contact_email SET TAGS ('sensitivity'='pii');
ALTER TABLE bronze.bronze_erp_vendors   ALTER COLUMN tax_id_masked         SET TAGS ('sensitivity'='financial_sensitive');

-- Public reference / lookup data.
ALTER TABLE bronze.bronze_ref_country_codes  SET TAGS ('sensitivity'='public_reference','layer'='bronze','domain'='reference');
ALTER TABLE bronze.bronze_ref_currency_rates SET TAGS ('sensitivity'='public_reference','layer'='bronze','domain'='reference');

-- Gold serving marts — TABLE-level classification (column-level PII tags in PART C).
ALTER TABLE gold.gold_customer_360        SET TAGS ('sensitivity'='pii',                 'layer'='gold');
ALTER TABLE gold.gold_revenue_pipeline    SET TAGS ('sensitivity'='internal_only',       'layer'='gold');
ALTER TABLE gold.gold_bookings_vs_billings SET TAGS ('sensitivity'='financial_sensitive','layer'='gold');
ALTER TABLE gold.gold_collections_risk    SET TAGS ('sensitivity'='financial_sensitive', 'layer'='gold');
ALTER TABLE gold.gold_support_performance SET TAGS ('sensitivity'='internal_only',        'layer'='gold');
ALTER TABLE gold.gold_account_health      SET TAGS ('sensitivity'='internal_only',        'layer'='gold');
ALTER TABLE gold.gold_renewal_risk        SET TAGS ('sensitivity'='internal_only',        'layer'='gold');

-- Curated AI-safe views — explicitly certified, PII-free.
ALTER VIEW gold.customer_360_curated        SET TAGS ('sensitivity'='internal_only','certified'='true','audience'='ai');
ALTER VIEW gold.account_health_curated      SET TAGS ('sensitivity'='internal_only','certified'='true','audience'='ai');
ALTER VIEW gold.support_performance_curated SET TAGS ('sensitivity'='internal_only','certified'='true','audience'='ai');
ALTER VIEW gold.revenue_pipeline_curated    SET TAGS ('sensitivity'='internal_only','certified'='true','audience'='ai');
ALTER VIEW gold.collections_risk_curated    SET TAGS ('sensitivity'='internal_only','certified'='true','audience'='ai');

-- ###########################################################################
-- PART B — CRM BRONZE (after the CRM cutover reload recreates bronze_crm_*)
-- ###########################################################################
-- ALTER TABLE bronze.bronze_crm_accounts SET TAGS ('sensitivity'='internal_only','layer'='bronze','domain'='crm');
-- ALTER TABLE bronze.bronze_crm_contacts SET TAGS ('sensitivity'='pii',          'layer'='bronze','domain'='crm');
-- ALTER TABLE bronze.bronze_crm_contacts ALTER COLUMN work_email     SET TAGS ('sensitivity'='pii');
-- ALTER TABLE bronze.bronze_crm_contacts ALTER COLUMN mobile_phone   SET TAGS ('sensitivity'='pii');
-- ALTER TABLE bronze.bronze_crm_contacts ALTER COLUMN office_address SET TAGS ('sensitivity'='pii');
-- ALTER TABLE bronze.bronze_crm_accounts ALTER COLUMN phone          SET TAGS ('sensitivity'='pii');

-- ###########################################################################
-- PART C — SILVER/GOLD PII COLUMNS (after pipeline PII promotion; Track A)
-- ###########################################################################
-- ALTER TABLE silver.silver_contact      ALTER COLUMN work_email    SET TAGS ('sensitivity'='pii');
-- ALTER TABLE silver.silver_contact      ALTER COLUMN mobile_phone  SET TAGS ('sensitivity'='pii');
-- ALTER TABLE gold.gold_customer_360     ALTER COLUMN primary_email SET TAGS ('sensitivity'='pii');
-- ALTER TABLE gold.gold_customer_360     ALTER COLUMN primary_phone SET TAGS ('sensitivity'='pii');
-- ALTER TABLE gold.gold_customer_360     ALTER COLUMN tax_id        SET TAGS ('sensitivity'='financial_sensitive');

-- Inspect:  SELECT * FROM ${catalog}.information_schema.table_tags;
--           SELECT * FROM ${catalog}.information_schema.column_tags;
