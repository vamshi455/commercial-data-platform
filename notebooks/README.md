# Notebooks — Commercial Data Platform

Databricks SQL/Python notebooks for observability, lineage, and analytics. Each
file carries the `-- Databricks notebook source` header and uses notebook
**widgets** (e.g. `catalog`, `pipeline_id`, `lookback_days`) so the same
notebook runs against cdp_dev / cdp_qa / cdp_prod.

## Folders

| Folder | Notebook | Purpose | Sources |
|--------|----------|---------|---------|
| `observability/` | `freshness_dashboard.sql` | Table freshness vs domain SLA, stale-table rollup | `information_schema.tables` |
| `observability/` | `dq_dashboard.sql` | DLT expectation pass/fail by pipeline + rule, failing rules, errors | pipeline `event_log(...)` |
| `observability/` | `run_health.sql` | Job/pipeline run status, failures, SLA breaches, reliability rollup | `system.lakeflow.job_run_timeline` |
| `lineage/` | `impact_analysis.sql` | "What depends on X" — direct + recursive downstream impact, upstream root-cause, column-level impact | `system.access.table_lineage` / `column_lineage` |
| `analytics/` | `exec_summary.sql` | Exec KPIs — weighted pipeline, bookings vs billings, collections risk, account health | `gold.*` curated products |
| `setup/` | (reserved) | Environment / governance setup notebooks |

## Conventions

- **Widgets** parameterize catalog and lookback windows; defaults target dev.
- Observability/lineage notebooks read **system** and **information_schema**
  metadata; analytics notebooks read **curated gold** only — never raw bronze,
  never unmasked PII.
- The `event_log(TABLE(...))` table-valued function needs the pipeline id (find
  it in the pipeline UI or `system.lakeflow`); some pipelines also publish an
  `event_log` table you can query directly.
- `system.lakeflow.*` and `system.access.*` schemas must be enabled for the
  workspace for `run_health` and `impact_analysis` to return rows.

These notebooks pair with the `platform_ops` and `data_steward` agents, which
answer the same questions conversationally over the same governed sources.
