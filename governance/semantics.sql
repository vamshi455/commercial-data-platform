-- =============================================================================
-- governance/semantics.sql
-- -----------------------------------------------------------------------------
-- AI-facing SEMANTIC LAYER for the Commercial Data Platform.
--
-- Purpose: give Genie / agents enough metadata to infer correctly — business
-- definitions, units, grain, synonyms, a freshness signal, and a stable
-- AI-safe surface — WITHOUT touching the DLT-managed base materialized views.
--
-- These are independent, owned Unity Catalog objects (curated views, metric
-- views, trusted functions). They are non-destructive: CREATE OR REPLACE only,
-- no data rewrite, safe to run on a live catalog. Run with USE CATALOG ${catalog}.
--
-- NAMING: deployed base objects are gold.gold_* and silver.silver_* (DLT MV
-- naming). The curated/metric/function objects below intentionally drop the
-- redundant prefix so the AI-facing names read as business concepts.
--
-- NOTE: the deployed silver/gold layers carry NO PII (email/phone/tax_id live
-- only in bronze). So curated views here expose PII-free aggregates and need no
-- column masks; the value added is documentation + a clean, approved surface.
-- =============================================================================

USE CATALOG ${catalog};
USE SCHEMA gold;

-- ===========================================================================
-- 1. CUSTOMER 360 (curated) — one row per unified customer (account)
-- ===========================================================================
CREATE OR REPLACE VIEW gold.customer_360_curated (
  customer_sk            COMMENT 'Surrogate key for the unified customer/account. GRAIN: exactly one row per customer. Use to join to other gold marts. aka account key, customer key.',
  crm_account_id         COMMENT 'Source CRM account identifier (Salesforce-style). aka account id.',
  company_name           COMMENT 'Customer company/legal account name. aka account name, customer name, company.',
  country                COMMENT 'Customer country (ISO-ish name as mastered in CRM). aka geo, region country.',
  contract_count         COMMENT 'Number of contracts associated with the customer.',
  total_contract_amount  COMMENT 'Total contracted value across all contracts, in USD. aka total contract value, TCV.',
  latest_contract_date   COMMENT 'Date of the most recent contract start. aka last contract date.',
  invoice_count          COMMENT 'Number of invoices issued to the customer.',
  total_invoiced         COMMENT 'Total amount invoiced, in USD. aka billings to date.',
  total_paid             COMMENT 'Total amount paid by the customer, in USD. aka cash collected.',
  total_open_ar          COMMENT 'Open accounts-receivable balance, in USD (invoiced minus paid, unpaid). aka outstanding receivables, AR balance, open balance.',
  late_invoice_count     COMMENT 'Number of invoices currently past due.',
  max_days_past_due      COMMENT 'Worst days-past-due across the customer''s open invoices. aka DPD, max DPD.',
  case_count             COMMENT 'Total support cases ever opened for the customer.',
  open_case_count        COMMENT 'Support cases currently open. aka open tickets.',
  avg_resolution_hours   COMMENT 'Average support case resolution time, in hours.',
  activity_count         COMMENT 'Count of CRM activities (calls/emails/meetings) logged for the customer.',
  last_activity_date     COMMENT 'Date of the most recent CRM activity. aka last touch date.',
  data_as_of             COMMENT 'FRESHNESS: timestamp this row was last refreshed in gold. Use to caveat how current the answer is.'
)
COMMENT 'CERTIFIED AI-safe 360-degree customer view: one row per customer with contract, billing, AR, support and activity rollups. PII-free. Source: gold.gold_customer_360. Use this (not the base table) for customer-level questions.'
AS SELECT
  customer_sk, crm_account_id, company_name, country,
  contract_count, total_contract_amount, latest_contract_date,
  invoice_count, total_invoiced, total_paid, total_open_ar,
  late_invoice_count, max_days_past_due,
  case_count, open_case_count, avg_resolution_hours,
  activity_count, last_activity_date,
  _gold_loaded_at AS data_as_of
FROM gold.gold_customer_360;

-- ===========================================================================
-- 2. ACCOUNT HEALTH (curated) — one row per customer
-- ===========================================================================
CREATE OR REPLACE VIEW gold.account_health_curated (
  customer_sk              COMMENT 'Customer surrogate key. GRAIN: one row per customer. Joins to customer_360_curated.',
  company_name             COMMENT 'Customer company name. aka account name.',
  country                  COMMENT 'Customer country.',
  open_case_count          COMMENT 'Currently open support cases. aka open tickets.',
  high_priority_case_count COMMENT 'Currently open high-priority support cases.',
  avg_resolution_hours     COMMENT 'Average support resolution time, in hours.',
  risk_tier                COMMENT 'Categorical support/operational risk tier. aka case risk tier.',
  total_open_ar            COMMENT 'Open accounts-receivable balance, in USD. aka outstanding balance.',
  last_activity_date       COMMENT 'Date of the most recent CRM activity. aka last touch.',
  activity_count           COMMENT 'Count of CRM activities logged.',
  health_score             COMMENT 'Composite account-health score (higher = healthier). aka customer health score.',
  health_tier              COMMENT 'Health tier bucket derived from health_score (e.g. healthy/at-risk/critical).',
  days_since_last_activity COMMENT 'Days since the last CRM activity. High values signal disengagement.',
  data_as_of               COMMENT 'FRESHNESS: timestamp this row was last refreshed in gold.'
)
COMMENT 'CERTIFIED AI-safe account-health view: support load, AR exposure, engagement recency and a composite health score per customer. Source: gold.gold_account_health.'
AS SELECT
  customer_sk, company_name, country, open_case_count, high_priority_case_count,
  avg_resolution_hours, risk_tier, total_open_ar, last_activity_date, activity_count,
  health_score, health_tier, days_since_last_activity,
  _gold_loaded_at AS data_as_of
FROM gold.gold_account_health;

-- ===========================================================================
-- 3. SUPPORT PERFORMANCE (curated) — one row per customer
-- ===========================================================================
CREATE OR REPLACE VIEW gold.support_performance_curated (
  customer_sk              COMMENT 'Customer surrogate key. GRAIN: one row per customer.',
  case_count               COMMENT 'Total support cases ever opened.',
  open_case_count          COMMENT 'Support cases currently open. aka open tickets.',
  avg_resolution_hours     COMMENT 'Average case resolution time, in hours. aka mean time to resolve, MTTR.',
  last_case_date           COMMENT 'Date the most recent support case was opened.',
  high_priority_case_count COMMENT 'Count of high-priority cases.',
  data_as_of               COMMENT 'FRESHNESS: timestamp this row was last refreshed in gold.'
)
COMMENT 'CERTIFIED AI-safe support-performance view: case volumes and resolution speed per customer. Source: gold.gold_support_performance.'
AS SELECT
  customer_sk, case_count, open_case_count, avg_resolution_hours,
  last_case_date, high_priority_case_count,
  _gold_loaded_at AS data_as_of
FROM gold.gold_support_performance;

-- ===========================================================================
-- 4. REVENUE PIPELINE (curated) — one row per customer per month
-- ===========================================================================
CREATE OR REPLACE VIEW gold.revenue_pipeline_curated (
  customer_sk     COMMENT 'Customer surrogate key. Joins to customer_360_curated.',
  period_month    COMMENT 'Calendar month (first day of month, DATE) the amounts belong to. GRAIN: one row per customer per month. aka month, reporting month.',
  booked_amount   COMMENT 'Bookings (new contracted value) in the month, USD. aka bookings, new business.',
  booking_count   COMMENT 'Number of bookings in the month.',
  ordered_amount  COMMENT 'Order value placed in the month, USD. aka orders.',
  order_count     COMMENT 'Number of orders in the month.',
  billed_amount   COMMENT 'Amount invoiced/billed in the month, USD. aka billings.',
  invoice_count   COMMENT 'Number of invoices in the month.',
  data_as_of      COMMENT 'FRESHNESS: timestamp this row was last refreshed in gold.'
)
COMMENT 'CERTIFIED AI-safe revenue pipeline at customer-by-month grain: bookings, orders and billings. Re-aggregate freely by customer or month. Source: gold.gold_revenue_pipeline.'
AS SELECT
  customer_sk, period_month, booked_amount, booking_count,
  ordered_amount, order_count, billed_amount, invoice_count,
  _gold_loaded_at AS data_as_of
FROM gold.gold_revenue_pipeline;

-- ===========================================================================
-- 5. COLLECTIONS RISK (curated) — one row per customer
-- ===========================================================================
CREATE OR REPLACE VIEW gold.collections_risk_curated (
  customer_sk            COMMENT 'Customer surrogate key. GRAIN: one row per customer.',
  company_name           COMMENT 'Customer company name.',
  country                COMMENT 'Customer country.',
  ar_current             COMMENT 'AR not yet past due, USD. aka current receivables.',
  ar_1_30                COMMENT 'AR 1-30 days past due, USD.',
  ar_31_60               COMMENT 'AR 31-60 days past due, USD.',
  ar_61_90               COMMENT 'AR 61-90 days past due, USD.',
  ar_90_plus             COMMENT 'AR over 90 days past due, USD. aka severely delinquent AR.',
  total_open_ar          COMMENT 'Total open accounts-receivable balance, USD. aka outstanding receivables.',
  max_days_past_due      COMMENT 'Worst days-past-due across open invoices. aka DPD.',
  weighted_days_past_due COMMENT 'AR-weighted average days past due. aka weighted DPD.',
  disputed_invoice_count COMMENT 'Number of invoices flagged as disputed.',
  risk_tier              COMMENT 'Collections risk tier (e.g. low/medium/high). aka credit risk tier.',
  data_as_of             COMMENT 'FRESHNESS: timestamp this row was last refreshed in gold.'
)
COMMENT 'CERTIFIED AI-safe collections-risk view: AR aging buckets, delinquency and dispute signals per customer. Source: gold.gold_collections_risk.'
AS SELECT
  customer_sk, company_name, country, ar_current, ar_1_30, ar_31_60, ar_61_90,
  ar_90_plus, total_open_ar, max_days_past_due, weighted_days_past_due,
  disputed_invoice_count, risk_tier,
  _gold_loaded_at AS data_as_of
FROM gold.gold_collections_risk;
