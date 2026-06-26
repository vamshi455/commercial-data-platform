-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Executive Summary — Gold KPIs
-- MAGIC Sample executive analytics across the gold layer: revenue pipeline,
-- MAGIC collections risk, and account health. Reads curated `gold.*` products
-- MAGIC only (no bronze, no PII). Set the catalog widget per environment.

-- COMMAND ----------

CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';

-- COMMAND ----------

USE CATALOG IDENTIFIER(:catalog);

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Pipeline by stage (open) — weighted forecast

-- COMMAND ----------

SELECT
  stage,
  count(*)                  AS deals,
  round(sum(amount), 0)     AS total_amount,
  round(sum(amount * probability), 0) AS weighted_amount
FROM gold.revenue_pipeline
WHERE status = 'Open'
GROUP BY stage
ORDER BY total_amount DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Bookings vs billings — latest periods

-- COMMAND ----------

SELECT
  period,
  round(sum(bookings_amount), 0) AS bookings,
  round(sum(billings_amount), 0) AS billings,
  round(sum(bookings_amount - billings_amount), 0) AS variance
FROM gold.bookings_vs_billings
GROUP BY period
ORDER BY period DESC
LIMIT 6;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Collections risk — top overdue exposure

-- COMMAND ----------

SELECT
  account_id,
  account_name,
  round(ar_balance, 0)     AS ar_balance,
  round(overdue_amount, 0) AS overdue_amount,
  days_overdue,
  round(risk_score, 2)     AS risk_score
FROM gold.collections_risk
ORDER BY overdue_amount DESC
LIMIT 15;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Account health distribution

-- COMMAND ----------

SELECT
  CASE
    WHEN health_score >= 80 THEN 'Healthy (80+)'
    WHEN health_score >= 60 THEN 'Watch (60-79)'
    WHEN health_score >= 40 THEN 'At Risk (40-59)'
    ELSE 'Critical (<40)'
  END                       AS health_band,
  count(*)                  AS accounts,
  round(avg(health_score), 1) AS avg_score
FROM gold.account_health
GROUP BY 1
ORDER BY min(health_score) DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## One-line KPI snapshot

-- COMMAND ----------

SELECT
  (SELECT round(sum(amount * probability), 0) FROM gold.revenue_pipeline WHERE status = 'Open')
                                                       AS weighted_pipeline,
  (SELECT round(sum(overdue_amount), 0) FROM gold.collections_risk)        AS total_overdue,
  (SELECT count(*) FROM gold.account_health WHERE health_score < 40)       AS critical_accounts,
  (SELECT count(*) FROM gold.renewal_risk WHERE risk_tier = 'High')        AS high_renewal_risk;
