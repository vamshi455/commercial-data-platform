-- =============================================================================
-- governance/grants.sql
-- -----------------------------------------------------------------------------
-- Persona RBAC matrix for the Commercial Data Platform, implemented with
-- Unity Catalog GRANT statements. Run once per environment with ${catalog}
-- bound to cdp_dev / cdp_qa / cdp_prod (USE CATALOG ${catalog}).
--
-- ⚠️ NAMES RECONCILED 2026-06-29 to the DEPLOYED DLT schema:
--   gold marts are  gold.gold_*      (e.g. gold.gold_customer_360)
--   silver entities are silver.silver_*  (e.g. silver.silver_invoice)
--   AI-safe curated views are gold.*_curated (see governance/semantics.sql)
--
-- LAYERED SECURITY MODEL (what each principal reads):
--   bronze            LOCKED — engineers only (raw, carries PII). Not a query surface.
--   silver/gold base  analysts/stewards read these; PII columns are MASKED per
--                     persona (see masking_functions.sql) + row-filtered by territory.
--   gold *_curated    AI/agents read ONLY these — PII-free by construction.
--
-- PRIVILEGE MODEL (UC three-level): USE CATALOG + USE SCHEMA + SELECT to read;
--   + MODIFY/CREATE to write; EXECUTE governs masking/row-filter UDFs.
-- =============================================================================

USE CATALOG ${catalog};

-- ---------------------------------------------------------------------------
-- 1. PLATFORM ENGINEERS — full control / owners-of-record (incl. locked bronze)
-- ---------------------------------------------------------------------------
GRANT ALL PRIVILEGES ON CATALOG ${catalog} TO `cdp_platform_engineers`;
GRANT MANAGE         ON CATALOG ${catalog} TO `cdp_platform_engineers`;

-- ---------------------------------------------------------------------------
-- 2. DATA ENGINEERS — own bronze/silver ingest+transform, read gold.
--    Bronze is locked to this group (+ platform): the only principals on raw PII.
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_data_engineers`;
GRANT USE SCHEMA, CREATE TABLE, CREATE VOLUME, MODIFY, SELECT, REFRESH
  ON SCHEMA bronze TO `cdp_data_engineers`;
GRANT USE SCHEMA, CREATE TABLE, MODIFY, SELECT, REFRESH
  ON SCHEMA silver TO `cdp_data_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gold TO `cdp_data_engineers`;
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
--    Reads the BASE marts (PII masked, rows filtered by territory).
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_sales_analysts`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.gold_revenue_pipeline     TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.gold_bookings_vs_billings TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.gold_account_health       TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.gold_renewal_risk         TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.gold_customer_360         TO `cdp_sales_analysts`;

-- ---------------------------------------------------------------------------
-- 5. FINANCE ANALYSTS — gold collections/billings + ERP invoices/payments.
--    Finance is the persona allowed to UNMASK tax_id (see masking_functions.sql).
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA gold   TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA silver TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.gold_collections_risk     TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.gold_bookings_vs_billings TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.gold_revenue_pipeline     TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.gold_customer_360         TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE silver.silver_invoice          TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE silver.silver_payment          TO `cdp_finance_analysts`;

-- ---------------------------------------------------------------------------
-- 6. CUSTOMER SUCCESS — account_health / support / customer_360.
--    The persona allowed to UNMASK contact email/phone (for outreach).
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_customer_success`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.gold_account_health       TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.gold_support_performance  TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.gold_renewal_risk         TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.gold_customer_360         TO `cdp_customer_success`;

-- ---------------------------------------------------------------------------
-- 7. DATA STEWARDS — read everything, govern tags, privileged unmask (all PII)
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA bronze TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA silver TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA ops    TO `cdp_data_stewards`;
GRANT APPLY TAG ON CATALOG ${catalog} TO `cdp_data_stewards`;
GRANT EXECUTE ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT EXECUTE ON SCHEMA silver TO `cdp_data_stewards`;

-- ---------------------------------------------------------------------------
-- 8. AI APP USERS — read ONLY the PII-free curated views (governance/semantics.sql)
-- ---------------------------------------------------------------------------
GRANT USE CATALOG ON CATALOG ${catalog} TO `cdp_ai_app_users`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.customer_360_curated        TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.account_health_curated      TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.support_performance_curated TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.revenue_pipeline_curated    TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.collections_risk_curated    TO `cdp_ai_app_users`;
GRANT EXECUTE ON SCHEMA gold TO `cdp_ai_app_users`;
