-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 01 — Persona RBAC Grants
-- MAGIC Wraps `governance/grants.sql`. Applies the persona RBAC matrix for the
-- MAGIC `cdp_*` UC groups against the catalog passed in the `catalog` widget.
-- MAGIC Run by `job_platform_setup` after `00_create_catalogs_schemas`.
-- MAGIC
-- MAGIC Requires catalog owner / `MANAGE` on the catalog.

-- COMMAND ----------

CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';
USE CATALOG IDENTIFIER(:catalog);

-- COMMAND ----------

-- DBTITLE 1,Platform engineers — full control
GRANT ALL PRIVILEGES ON CATALOG IDENTIFIER(:catalog) TO `cdp_platform_engineers`;
GRANT MANAGE ON CATALOG IDENTIFIER(:catalog) TO `cdp_platform_engineers`;

-- COMMAND ----------

-- DBTITLE 1,Data engineers — own bronze/silver, read gold
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_data_engineers`;
GRANT USE SCHEMA, CREATE TABLE, CREATE VOLUME, MODIFY, SELECT, REFRESH ON SCHEMA bronze TO `cdp_data_engineers`;
GRANT USE SCHEMA, CREATE TABLE, MODIFY, SELECT, REFRESH ON SCHEMA silver TO `cdp_data_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gold TO `cdp_data_engineers`;
GRANT USE SCHEMA, READ VOLUME, WRITE VOLUME ON SCHEMA landing TO `cdp_data_engineers`;
GRANT USE SCHEMA, MODIFY, SELECT, CREATE TABLE ON SCHEMA ops TO `cdp_data_engineers`;

-- COMMAND ----------

-- DBTITLE 1,Analytics engineers — own gold, read silver
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA silver TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, CREATE TABLE, CREATE MATERIALIZED VIEW, MODIFY, SELECT, REFRESH ON SCHEMA gold TO `cdp_analytics_engineers`;
GRANT USE SCHEMA, SELECT, MODIFY ON SCHEMA ops TO `cdp_analytics_engineers`;

-- COMMAND ----------

-- DBTITLE 1,Sales analysts — gold revenue/pipeline + masked customer
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_sales_analysts`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.revenue_pipeline      TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.bookings_vs_billings  TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.account_health        TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.renewal_risk          TO `cdp_sales_analysts`;
GRANT SELECT ON TABLE gold.customer_360          TO `cdp_sales_analysts`;

-- COMMAND ----------

-- DBTITLE 1,Finance analysts — collections/billings + invoices/payments
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA gold   TO `cdp_finance_analysts`;
GRANT USE SCHEMA ON SCHEMA silver TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.collections_risk      TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.bookings_vs_billings  TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE gold.revenue_pipeline      TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE silver.erp_invoices        TO `cdp_finance_analysts`;
GRANT SELECT ON TABLE silver.erp_payments        TO `cdp_finance_analysts`;

-- COMMAND ----------

-- DBTITLE 1,Customer success — account_health/support/customer_360 (masked)
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_customer_success`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.account_health        TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.support_performance   TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.renewal_risk          TO `cdp_customer_success`;
GRANT SELECT ON TABLE gold.customer_360          TO `cdp_customer_success`;

-- COMMAND ----------

-- DBTITLE 1,Data stewards — read all + manage tags
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA bronze TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA silver TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA ops    TO `cdp_data_stewards`;
GRANT APPLY TAG ON CATALOG IDENTIFIER(:catalog) TO `cdp_data_stewards`;
GRANT EXECUTE ON SCHEMA gold   TO `cdp_data_stewards`;
GRANT EXECUTE ON SCHEMA silver TO `cdp_data_stewards`;

-- COMMAND ----------

-- DBTITLE 1,AI app users — approved gold curated views only
GRANT USE CATALOG ON CATALOG IDENTIFIER(:catalog) TO `cdp_ai_app_users`;
GRANT USE SCHEMA ON SCHEMA gold TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.customer_360_curated        TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.account_health_curated      TO `cdp_ai_app_users`;
GRANT SELECT ON VIEW gold.support_performance_curated TO `cdp_ai_app_users`;
GRANT EXECUTE ON SCHEMA gold TO `cdp_ai_app_users`;
