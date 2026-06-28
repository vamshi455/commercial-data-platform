-- =============================================================================
-- governance/row_filters.sql
-- -----------------------------------------------------------------------------
-- Row-level security via row-filter UDFs + ALTER TABLE ... SET ROW FILTER.
-- Run once per environment (USE CATALOG ${catalog}).
--
-- HOW ROW FILTERS WORK
--   A row filter is a SQL UDF that returns BOOLEAN. Its arguments are columns
--   of the table; UC evaluates it per row and keeps rows where it returns TRUE.
--   We use is_account_group_member() so that finance/stewards/platform see ALL
--   rows, while sales_analysts are constrained to their own territory.
--
--   Sales-analyst -> territory mapping is held in ops.user_territory_map
--   (user_email STRING, territory STRING). current_user() identifies the caller.
-- =============================================================================

USE CATALOG ${catalog};
USE SCHEMA gold;

-- ---------------------------------------------------------------------------
-- territory_filter — TRUE if caller may see the row's territory.
--   Depends on gold.is_prod() (defined in masking_functions.sql, which runs
--   first). In non-prod the filter is relaxed to all rows so engineers can test
--   against the full synthetic dataset; row scoping is enforced only in prod.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gold.territory_filter(territory STRING)
  RETURNS BOOLEAN
  COMMENT 'Row filter: unrestricted for finance/stewards/platform; sales_analysts see only mapped territories. Relaxed (all rows) in non-prod.'
  RETURN
    -- Non-prod: synthetic data, no row scoping (see gold.is_prod()).
    NOT gold.is_prod()
    -- Unrestricted personas: full visibility across all territories.
    OR is_account_group_member('cdp_data_stewards')
    OR is_account_group_member('cdp_platform_engineers')
    OR is_account_group_member('cdp_finance_analysts')
    OR is_account_group_member('cdp_analytics_engineers')
    -- Sales analysts: only rows whose territory is mapped to the caller.
    OR (
      is_account_group_member('cdp_sales_analysts')
      AND territory IN (
        SELECT m.territory
        FROM ops.user_territory_map m
        WHERE m.user_email = current_user()
      )
    );

-- ---------------------------------------------------------------------------
-- BIND ROW FILTERS — ALTER TABLE ... SET ROW FILTER ... ON (col)
-- ---------------------------------------------------------------------------
-- The column list passed in ON(...) is forwarded to the UDF arguments in order.
ALTER TABLE gold.revenue_pipeline SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.customer_360     SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.account_health   SET ROW FILTER gold.territory_filter ON (territory);
ALTER TABLE gold.renewal_risk     SET ROW FILTER gold.territory_filter ON (territory);

-- To remove a row filter:
--   ALTER TABLE gold.revenue_pipeline DROP ROW FILTER;
