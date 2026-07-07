# Project Plan — Commercial Data Platform

A phased plan to build the Commercial Data Platform: a Salesforce-like **CRM** + SAP-like
**ERP** integrated into a governed **medallion lakehouse** on Databricks, with CI/CD,
governance, and AI agents. Each phase lists **goals**, **deliverables**, **acceptance
criteria**, and the **repo files/folders** that implement it.

> **Workspace:** `https://adb-7405618019865738.18.azuredatabricks.net` · **Catalogs:**
> `cdp_dev / cdp_qa / cdp_prod` · **Schemas:** `landing, bronze, silver, gold, ops` (+
> `sandbox` in dev).

---

## 1. Phases

### Phase 1 — Foundation

| | |
|---|---|
| **Goals** | Stand up UC governance, catalogs/schemas, volumes, groups, and the deployable bundle skeleton |
| **Deliverables** | `databricks.yml` (dev/qa/prod targets + variables); UC catalogs/schemas; landing **Volumes**; UC groups (`cdp_*`); base grants; `resources/` skeleton |
| **Acceptance** | `databricks bundle validate -t dev/qa/prod` passes; catalogs + schemas + volumes exist; groups created and grantable |
| **Implements** | `databricks.yml`, `resources/`, `governance/`, `scripts/` |

### Phase 2 — Synthetic source creation

| | |
|---|---|
| **Goals** | Generate realistic CRM + ERP + reference data with referential integrity and intentional DQ defects |
| **Deliverables** | Generators for all CRM/ERP entities; reference data (currency_rates, hierarchies); files landed to `landing/files/{crm,erp,ref}` |
| **Acceptance** | Files land in the UC volume; FK integrity across entities; seeded duplicates/PII/edge cases present for DQ + MDM to exercise |
| **Implements** | `data_gen/`, `scripts/` |

### Phase 3 — Bronze ingestion

| | |
|---|---|
| **Goals** | Incrementally ingest landing files into audited, append-only Delta bronze |
| **Deliverables** | Auto Loader streaming tables per entity; audit columns (`_ingested_at,_source_file,_batch_id,_rescued_data`); schema evolution + rescued data |
| **Acceptance** | All landing files appear in `bronze.*`; audit columns populated; schema drift captured in `_rescued_data`; idempotent re-runs |
| **Implements** | `src/pipelines/ingestion/`, `src/pipelines/bronze/`, `resources/pipeline_ingestion.yml` |

### Phase 4 — Silver conformance

| | |
|---|---|
| **Goals** | Cleanse, deduplicate (SCD), reconcile, enrich, master identities, enforce DQ |
| **Deliverables** | Customer MDM/identity resolution + `customer_key`; contract/order conformance; invoice/payment reconciliation; product/territory standardization; activity/case enrichment + free-text masking; DLT expectations |
| **Acceptance** | `silver.dim_customer` unique mastered keys; reconciliation status populated; DQ expectations enforced; PII masked; MDM review queue produced |
| **Implements** | `src/pipelines/silver/`, `resources/pipeline_silver.yml`, `governance/` (masks) |

### Phase 5 — Gold publication

| | |
|---|---|
| **Goals** | Publish business data products with clear KPI semantics |
| **Deliverables** | `customer_360, revenue_pipeline, bookings_vs_billings, collections_risk, support_performance, account_health, renewal_risk`; selective Managed Iceberg; SQL dashboards |
| **Acceptance** | All 7 products materialize and reconcile to source totals; Iceberg products queryable; dashboards render KPIs |
| **Implements** | `src/pipelines/gold/`, `resources/pipeline_gold.yml`, `notebooks/` (dashboards) |

### Phase 6 — Governance & operations

| | |
|---|---|
| **Goals** | Operationalize: orchestration, CI/CD, lineage, DQ/SLA monitoring, security |
| **Deliverables** | Orchestration job; GitHub Actions (`ci`, `deploy-qa`, `deploy-prod`); SP OAuth; lineage via system tables; `ops.dq_results`/`sla_tracking`; PII + finance grants/masks; data contracts/SLAs |
| **Acceptance** | PR→dev→qa→prod promotion works with approval gate; lineage visible; DQ/SLA tracked; least-privilege grants verified |
| **Implements** | `.github/workflows/`, `resources/job_orchestration_daily.yml`, `governance/`, `ops.*`, `docs/cicd.md` |

### Phase 7 — AI & agent enablement

| | |
|---|---|
| **Goals** | Expose governed NL access via 5 domain agents over curated views only |
| **Deliverables** | Revenue Insights, Customer Health, Data Steward, Platform Ops, Finance Reconciliation agents; governed SQL tools; `cdp_ai_app_users` grants; eval sets |
| **Acceptance** | Agents answer sample prompts using only governed gold/silver/system tables; no bronze/PII access; queries audited |
| **Implements** | `agents/*`, `docs/agents.md` |

---

## 2. Milestones

| Phase | Key outputs | Status (2026-07-04, dev only) |
|---|---|---|
| 1 Foundation | bundle + targets, UC catalogs/schemas/volumes, groups | ☑ Done (dev) |
| 2 Synthetic sources | CRM/ERP/reference generators, landed files | ◐ ERP/ref done; CRM via Postgres (cutover half-done) |
| 3 Bronze ingestion | Auto Loader streaming tables + audit columns | ◐ 17 tables (ERP+ref); **CRM bronze missing** |
| 4 Silver conformance | MDM, reconciliation, standardization, DQ | ◐ 9 objects live; CRM-dependent ones stale |
| 5 Gold publication | 7 data products + Iceberg + dashboards | ◐ 7 products + 5 curated views live; dashboards pending |
| 6 Governance & ops | CI/CD, lineage, DQ/SLA, security, contracts | ◐ Governance applied; **ops DQ/SLA + qa/prod not deployed** |
| 7 AI & agents | 5 governed agents + eval | ☐ Not started (curated views = groundwork) |

> Status legend: ☐ Not started · ◐ In progress · ☑ Done. Only **dev** is deployed;
> qa/prod workspaces torn down 2026-07-04 (cost). Live-status detail in `docs/checkpoint.md`.

---

## 3. Skills demonstrated

| Job-market skill | Where it shows up in the repo |
|---|---|
| **PySpark** | `src/pipelines/silver/*` transforms (joins, window funcs, fuzzy matching), `data_gen/` |
| **Spark SQL** | gold materialized views, `agents/*/tools.sql`, KPI definitions |
| **Delta / medallion** | `src/pipelines/{bronze,silver,gold}/`, time travel/`RESTORE` in rollback |
| **Unity Catalog governance** | `databricks.yml` permissions, `governance/` masks/grants, system-table lineage |
| **Batch + streaming ingestion** | Auto Loader streaming tables (`src/pipelines/ingestion/`), reference batch MVs |
| **Performance tuning** | `cloudFiles.maxFilesPerTrigger`, partitioning/Z-order/clustering, channel choice, full-refresh-select |
| **Cloud awareness (Azure)** | Azure Databricks workspace, UC Volumes on ADLS Gen2, OIDC federation (WIF), system.billing usage |
| **DQ / reconciliation** | DLT expectations catalog, invoice/payment recon, `ops.dq_results`, `tests/dq` |
| **GenAI** | `agents/*`, Genie/Mosaic AI, governed SQL function-calling, MLflow serving (optional) |
| **CRM/ERP integration** | identity resolution CRM accounts ↔ ERP customers, bookings vs billings |
| **CI/CD** | DABs + `.github/workflows/*`, `docs/cicd.md` |

---

## 4. Important-not-to-miss checklist

| Item | Covered by |
|---|---|
| **MDM / identity resolution** | Deterministic + fuzzy matching, surrogate `customer_key`, steward review (Phase 4) |
| **Reference / master data** | `landing/ref`, currency_rates, hierarchies → silver MVs (Phase 2/4) |
| **Free-text governance** | PII masking/redaction on activity/case text via curated views (Phase 4) |
| **Data contracts / SLAs** | Schema + expectation contracts; `ops.sla_tracking`, freshness rules (Phase 6) |
| **Backfill / replay** | Re-land files + targeted `--full-refresh-select`; idempotent APPLY CHANGES (Phase 3/4) |
| **Cost / perf governance** | `system.billing.usage`, channel per env, trigger/cluster tuning, Platform Ops agent (Phase 6/7) |
| **CI/CD** | DABs targets + GitHub Actions + approval gate (Phase 6) |
| **Semantic KPI definitions** | Documented gold KPI grains/metrics, Genie space semantics (Phase 5/7) |
| **PII / finance security** | UC column masks, row filters, least-privilege grants, audit (Phase 6) |
| **DR / recovery** | Delta time travel/`RESTORE`, full-refresh rebuild from landing, redeploy prior tag (Phase 6) |

---

## 5. Suggested execution order / next steps

```
Phase 1 ─► Phase 2 ─► Phase 3 ─► Phase 4 ─► Phase 5 ─► Phase 6 ─► Phase 7
(foundation) (data)  (bronze)   (silver)    (gold)    (gov/ops)  (agents)
```

1. **Phase 1 first**: get `databricks bundle validate -t dev` green; create catalogs,
   schemas, volumes, and `cdp_*` groups. Nothing else works without governance + the bundle.
2. **Phase 2**: write generators; land a small CRM/ERP/reference batch with seeded defects.
3. **Phase 3**: stand up Auto Loader bronze with audit columns; verify idempotent re-ingest.
4. **Phase 4**: build silver incrementally — MDM/`customer_key` first (everything depends on
   it), then reconciliation, then enrichment + DQ expectations.
5. **Phase 5**: publish the 7 gold products; reconcile totals to source; build dashboards;
   promote selected products to Managed Iceberg.
6. **Phase 6**: wire orchestration + CI/CD (dev→qa→prod), add masks/grants, lineage, DQ/SLA
   monitoring, and rollback runbooks.
7. **Phase 7**: stand up the 5 agents over governed views; grant `cdp_ai_app_users`; add eval
   sets; confirm no bronze/PII access and that queries are audited.

**Cross-cutting from day one:** every phase ships through the bundle (`bundle deploy -t dev`),
adds tests (`tests/unit`, `tests/dq`), and updates docs in `docs/`.

---

## 6. File map

| Concern | Location |
|---|---|
| Bundle root / targets | `databricks.yml` |
| Resources (jobs/pipelines) | `resources/*.yml` |
| Pipeline code | `src/pipelines/{ingestion,bronze,silver,gold}/` |
| Synthetic generators | `data_gen/` |
| Governance (masks/grants/contracts) | `governance/` |
| Agents | `agents/*` |
| CI/CD | `.github/workflows/`, `docs/cicd.md` |
| Notebooks / dashboards | `notebooks/` |
| Tests | `tests/unit`, `tests/dq` |
| Docs | `docs/{pipelines,cicd,agents,project-plan}.md` |
