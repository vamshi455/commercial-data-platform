# AI Agents — Commercial Data Platform

The platform exposes five domain agents that answer natural-language questions over the
**governed gold/silver curated layer** only. Agents are built on the current Databricks AI
stack and are bound by Unity Catalog (UC) so they **never read raw bronze and never see
unmasked PII**.

> **UC group for agents:** `cdp_ai_app_users`. Agents run as this identity (or a dedicated
> service principal that is a member of it) and inherit only its grants.
>
> **Agent code/config:** `agents/{revenue_insights,customer_health,data_steward,platform_ops,finance_reconciliation}/`.

---

## 1. Architecture options

```
   User / app
      │  natural language
      ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Agent runtime (one of):                                              │
 │   (a) Databricks Genie / AI-BI  — NL→SQL over a curated Genie space   │
 │   (b) Agent Bricks / Mosaic AI agent framework — multi-tool agents    │
 │   (c) Function-calling over governed SQL UDFs / UC functions          │
 │   (d) (optional) custom LLM via MLflow + Mosaic AI Model Serving      │
 └───────────────────────────────┬──────────────────────────────────────┘
                                 │  tools = governed SQL functions / views
                                 ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Unity Catalog  — enforces grants, row/column masking, audit          │
 │     gold.*  (data products)      silver.* curated views (no PII raw)   │
 │     system.access / system.lineage (for steward / ops agents)         │
 └──────────────────────────────────────────────────────────────────────┘
```

| Option | Best for | How it appears here |
|---|---|---|
| **Genie / AI-BI** | self-service NL analytics over a defined table set | Each business agent backed by a Genie space scoped to its gold tables + KPI definitions |
| **Agent Bricks / Mosaic AI agent framework** | multi-step, multi-tool reasoning, evaluation, deployment | Steward / Platform Ops / Finance Recon agents that combine SQL + system-table tools |
| **Function-calling over governed SQL** | deterministic, auditable answers | UC SQL functions (e.g. `gold.fn_open_ar(customer)`) exposed as agent tools |
| **MLflow model serving (optional)** | custom/finetuned LLM or scoring endpoint | Pluggable serving endpoint behind the agent framework |

All four enforce governance the same way: **the agent can only touch what
`cdp_ai_app_users` is granted**, and grants point at curated views, not base PII tables.

---

## 2. Global guardrails

| Guardrail | Implementation |
|---|---|
| Governed views only | Agents granted `SELECT` on `gold.*` + designated `silver.*` curated views; **no grant** on `bronze.*` |
| No unmasked PII | UC **column masks** + masking functions on email/phone/tax_id/address; agents see masked outputs |
| No raw free-text leakage | Activity/case text columns exposed only via masked/redacted curated views |
| Least privilege | `cdp_ai_app_users` has `USE CATALOG`/`USE SCHEMA` + `SELECT` on an allowlist; never `MODIFY` |
| Row-level scope | Optional UC **row filters** (e.g. territory/region) per consuming group |
| Auditability | All agent queries captured in `system.access.audit`; tool calls logged to `ops.agent_audit` |
| Deterministic finance | Finance answers use SQL functions over reconciled tables, not free-form generation |
| Prompt-injection defense | Agents restricted to whitelisted tools; no arbitrary SQL execution against base tables |

Example UC grants and a mask:

```sql
GRANT USE CATALOG ON CATALOG cdp_prod TO `cdp_ai_app_users`;
GRANT USE SCHEMA  ON SCHEMA  cdp_prod.gold TO `cdp_ai_app_users`;
GRANT SELECT ON TABLE cdp_prod.gold.customer_360       TO `cdp_ai_app_users`;
GRANT SELECT ON TABLE cdp_prod.gold.collections_risk   TO `cdp_ai_app_users`;
-- No grant on cdp_prod.bronze.* — by design.

-- Column mask applied to PII so agents (and dashboards) see masked values:
ALTER TABLE cdp_prod.silver.dim_customer
  ALTER COLUMN email SET MASK cdp_prod.gov.mask_email;
```

---

## 3. The five agents

### 3.1 Revenue Insights — `agents/revenue_insights/`

| | |
|---|---|
| **Purpose** | Pipeline, bookings, and revenue trends for sales leadership / RevOps |
| **Persona / readers** | `cdp_sales_analysts`, `cdp_analytics_engineers` |
| **Data sources** | `gold.revenue_pipeline`, `gold.bookings_vs_billings`, `gold.customer_360` (rollups), `silver.dim_territory`, `silver.dim_product` (curated) |
| **Tools / functions** | `fn_pipeline_by_stage(period, territory)`, `fn_bookings_vs_billings(period)`, `fn_top_opportunities(n)` (governed SQL) + Genie NL→SQL |
| **Sample prompts** | "What's the weighted pipeline for EMEA this quarter?" · "Show bookings vs billings gap by product family." · "Top 10 open opportunities by amount." |
| **Guardrails** | Gold only; no contact PII; territory row filter optional |

### 3.2 Customer Health — `agents/customer_health/`

| | |
|---|---|
| **Purpose** | Account health, churn/renewal risk, engagement for Customer Success |
| **Persona / readers** | `cdp_customer_success` |
| **Data sources** | `gold.account_health`, `gold.renewal_risk`, `gold.support_performance`, `gold.customer_360` |
| **Tools / functions** | `fn_health_score(customer)`, `fn_renewals_at_risk(window_days)`, `fn_engagement_summary(customer)` |
| **Sample prompts** | "Which accounts renew in 90 days and are at risk?" · "Why is Acme's health score down?" · "Accounts with declining engagement and open cases." |
| **Guardrails** | Gold only; contact details masked; no raw activity text (uses redacted summary view) |

### 3.3 Data Steward — `agents/data_steward/`

| | |
|---|---|
| **Purpose** | Data quality, MDM/identity review, lineage, governance posture |
| **Persona / readers** | `cdp_data_stewards` |
| **Data sources** | `ops.dq_results`, `ops.mdm_review`, `ops.reconciliation_exceptions`, **`system.lineage.*`**, `system.information_schema.*` |
| **Tools / functions** | `fn_dq_failures(entity, since)`, `fn_lineage_upstream(table)`, `fn_mdm_review_queue(min_conf, max_conf)`, `fn_pii_coverage()` |
| **Sample prompts** | "What DQ rules failed last night and on which tables?" · "Show upstream lineage of gold.customer_360." · "List MDM matches awaiting steward review." · "Which PII columns lack a mask?" |
| **Guardrails** | Reads metadata + ops only; PII shown as coverage metrics, never values |

### 3.4 Platform Operations — `agents/platform_ops/`

| | |
|---|---|
| **Purpose** | Pipeline health, freshness/SLA, cost & performance, run failures |
| **Persona / readers** | `cdp_platform_engineers`, `cdp_data_engineers` |
| **Data sources** | **`system.lakeflow.*` / job & pipeline system tables**, `system.billing.usage`, `system.access.audit`, `ops.sla_tracking` |
| **Tools / functions** | `fn_pipeline_status(since)`, `fn_freshness_breaches()`, `fn_cost_by_pipeline(period)`, `fn_failed_runs(env)` |
| **Sample prompts** | "Did any pipeline miss its freshness SLA today?" · "DBU cost by pipeline this month." · "Show failed job runs in prod in the last 24h." |
| **Guardrails** | Operational/system tables only; no business PII; scoped to ops + system schemas |

### 3.5 Finance Reconciliation — `agents/finance_reconciliation/`

| | |
|---|---|
| **Purpose** | AR, collections risk, bookings-vs-billings, invoice/payment reconciliation |
| **Persona / readers** | `cdp_finance_analysts` |
| **Data sources** | `gold.collections_risk`, `gold.bookings_vs_billings`, `silver.reconciliation_invoice_payment` (curated), `gold.customer_360` (AR rollups) |
| **Tools / functions** | `fn_open_ar(customer)`, `fn_aging_buckets(period)`, `fn_recon_exceptions(since)`, `fn_collections_risk(min_score)` |
| **Sample prompts** | "Which customers have >$50k past 90 days?" · "Reconciliation exceptions this week." · "Bookings vs billings gap for the German entity." |
| **Guardrails** | Deterministic SQL functions over **reconciled** tables; amounts not generated; bank/payment identifiers masked |

---

## 4. Agent ↔ data-source matrix

| Agent | gold.* | silver curated | ops.* | system.* | Sees PII? |
|---|---|---|---|---|---|
| Revenue Insights | revenue_pipeline, bookings_vs_billings, customer_360 | dim_territory, dim_product | — | — | No |
| Customer Health | account_health, renewal_risk, support_performance, customer_360 | — | — | — | No (masked) |
| Data Steward | — | — | dq_results, mdm_review, reconciliation_exceptions | lineage, information_schema | No (metrics only) |
| Platform Ops | — | — | sla_tracking | lakeflow, billing, access.audit | No |
| Finance Reconciliation | collections_risk, bookings_vs_billings, customer_360 | reconciliation_invoice_payment | — | — | No (masked) |

**No agent has any grant on `bronze.*`.**

---

## 5. Lineage & metadata via system tables (Steward + Platform Ops)

The Data Steward and Platform Ops agents reason over UC **system tables** rather than business
data:

```sql
-- Upstream lineage of a gold product (Data Steward)
SELECT source_table_full_name, target_table_full_name, event_time
FROM   system.lineage.table_lineage
WHERE  target_table_full_name = 'cdp_prod.gold.customer_360'
ORDER BY event_time DESC;

-- Pipeline run health / failures (Platform Ops)
SELECT pipeline_id, update_id, state, start_time
FROM   system.lakeflow.pipeline_updates       -- (Lakeflow/DLT system tables)
WHERE  state IN ('FAILED','STALLED') AND start_time > now() - INTERVAL 24 HOURS;

-- Cost attribution (Platform Ops)
SELECT custom_tags['pipeline'] AS pipeline, sum(usage_quantity) AS dbus
FROM   system.billing.usage
WHERE  usage_date >= date_trunc('month', current_date)
GROUP BY 1 ORDER BY 2 DESC;

-- Who queried what (audit, both)
SELECT user_identity.email, action_name, request_params
FROM   system.access.audit
WHERE  service_name = 'unityCatalog' AND event_time > now() - INTERVAL 1 DAY;
```

These power answers like "what feeds customer_360?", "which pipeline failed?", and "what did
this DBU spend go to?" — without touching customer data.

---

## 6. Per-agent file layout

Each `agents/<name>/` folder is expected to contain:

| File | Purpose |
|---|---|
| `agent.yml` / `config.yml` | Runtime config: framework (Genie/Mosaic), model endpoint, allowed tables |
| `tools.sql` | Governed UC SQL functions exposed as tools |
| `prompts/` | System prompt + few-shot examples + guardrail instructions |
| `eval/` | Evaluation set + expected behaviors (Mosaic AI agent evaluation) |
| `grants.sql` | UC grants for `cdp_ai_app_users` scoped to this agent's tables |

| Agent | Folder |
|---|---|
| Revenue Insights | `agents/revenue_insights/` |
| Customer Health | `agents/customer_health/` |
| Data Steward | `agents/data_steward/` |
| Platform Operations | `agents/platform_ops/` |
| Finance Reconciliation | `agents/finance_reconciliation/` |
