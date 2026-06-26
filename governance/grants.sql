-- =============================================================================
-- governance/grants.sql
-- -----------------------------------------------------------------------------
-- Persona RBAC matrix for the Commercial Data Platform, implemented with
-- Unity Catalog GRANT statements. Run once per environment with ${catalog}
-- bound to cdp_dev / cdp_qa / cdp_prod (USE CATALOG ${catalog}).
--
-- PRIVILEGE MODEL (UC three-level: catalog -> schema -> table/function)
--   To read a table a principal needs USE CATALOG + USE SCHEMA + SELECT.
--   To write a table they additionally need MODIFY (and CREATE on the schema
--   for new objects). EXECUTE governs UDFs (masking/row-filter functions).
--
-- RBAC MATRIX (summary)
--   platform_engineers   ALL PRIVILEGES on catalog (operate as admins/owners)
--   data_engineers       MODIFY bronze+silver, SELECT gold, CREATE in bronze/silver
--   analytics_engineers  MODIFY gold, SELECT silver, CREATE in gold
--   sales_analysts       SELECT gold (revenue/pipeline + masked customer views)
--   finance_analysts     SELECT gold (collections/billings) + invoice/payment
--   customer_success     SELECT gold (account_health/support/customer_360 masked)
--   data_stewards        SELECT everything + manage tags (privileged unmask)
--   ai_app_users         SELECT only on approved gold curated views
--
-- NOTE: column masks and row filters (see masking_functions.sql / row_filters.sql)
--   enforce field-level redaction on top of these table grants, so a persona can
--   hold SELECT on a table yet still see masked PII.
-- =============================================================================

USE CATALOG ${catalog};

-- ---------------------------------------------------------------------------
-- 1. PLATFORM ENGINEERS — full control / owners-of-record
-- ---------------------------------------------------------------------------
GRANT ALL PRIVILEGES ON CATALOG ${catalog} TO `cdp_platform_engineers`;
-- MANAGE lets them administer grants and govern objects they don't own.
GRANT MANAGE ON CATALOG ${catalog} TO `cdp_platform_engineers`;

-- ---------------------------------------------------------------------------
-- 2. DATA ENGINEERS — own bronze/silver ingest+transform, read gold
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_data_engineers`;

GRANT USE SCHEMA, CREATE TABLE, CREATE VOLUME, MODIFY, SELECT, REFRESH
  ON SCHEMA bronze TO `cdp_data_engineers`;
GRANT USE SCHEMA, CREATE TABLE, MODIFY, SELECT, REFRESH
  ON SCHEMA silver TO `cdp_data_engineers`;
-- Read-only into gold so they can validate downstream contracts.
GRANT USE SCHEMA, SELECT ON SCHEMA gold TO `cdp_data_engineers`;
-- Landing files + ops logging.
GRANT USE SCHEMA, READ VOLUME, WRITE VOLUME ON SCHEMA landing TO `cdp_data_engineers`;
GRANT USE SCHEMA, MODIFY, SELECT, CREATE TABLE ON SCHEMA ops TO `cdp_data_engineers`;

-- ---------------------------------------------------------------------------
-- 3. ANALYTICS ENGINEERS — own gold marts, read silver
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA silver TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, CREATE TABLE, CREATE MATERIALIZED VIEW, MODIFY, SELECT, REFRESH
  ON SCHEMA gold TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA ops TO `cdp_analytics_engineers`;

-- ---------------------------------------------------------------------------
-- 4. SALES ANALYSTS — gold revenue/pipeline + masked customer; territory-filtered
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_sales_analysts`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_sales_analysts`;
-- Object-level SELECT (not schema-wide) — analysts only see sales-relevant marts.
GRANT SELECT ON TABLE gold.revenue_pipeline      TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.bookings_vs_billings  TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.account_health        TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.renewal_risk          TO `cdp_sales_analysts`;
-- customer_360 is exposed masked + row-filtered by territory (see policies).
GRANT SELECT ON TABLE gold.customer_360          TO `cdp_sales_analysts`;

-- ---------------------------------------------------------------------------
-- 5. FINANCE ANALYSTS — gold collections/billings + ERP invoices/payments
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA gold   TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA silver TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.collections_risk      TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.bookings_vs_billings  TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.revenue_pipeline      TO `cdp_finance_analysts`;
-- Source-of-truth financial detail from silver (tax_id etc. masked by policy).
GRANT SELECT ON TABLE silver.erp_invoices        TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE silver.erp_payments        TO `cdp_finance_analysts`;

-- ---------------------------------------------------------------------------
-- 6. CUSTOMER SUCCESS — account_health / support / customer_360 (masked)
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_customer_success`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.account_health        TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.support_performance   TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.renewal_risk          TO `cdp_customer_success`;
-- customer_360 with PII masking applied (email/phone redacted for this group).
GRANT SELECT ON TABLE gold.customer_360          TO `cdp_customer_success`;

-- ---------------------------------------------------------------------------
-- 7. DATA STEWARDS — read everything, govern tags, privileged unmask
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA bronze TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA silver TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA ops    TO `cdp_data_stewards`;
-- Stewards curate classification metadata; APPLY TAG lets them set/edit tags.
GRANT APPLY TAG ON CATALOG ${catalog} TO `cdp_data_stewards`;
-- EXECUTE on masking/row-filter UDFs (they are in is_account_group_member()
-- allowlists, so they see clear text — see masking_functions.sql).
GRANT EXECUTE ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT EXECUTE ON SCHEMA silver TO `cdp_data_stewards`;

-- ---------------------------------------------------------------------------
-- 8. AI APP USERS — read ONLY approved gold curated/serving views
-- ---------------------------------------------------------------------------
-- This group backs AI/agent applications; it must never see raw PII tables.
-- Grant SELECT only on explicitly approved curated views (suffix _curated).
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_ai_app_users`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.customer_360_curated      TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.account_health_curated    TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.support_performance_curated TO `cdp_ai_app_users`;
-- EXECUTE so masking UDFs referenced by the curated views resolve.
GRANT EXECUTE ON SCHEMA gold TO `cdp_ai_app_users`;
