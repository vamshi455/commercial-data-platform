# Jobs & Pipelines — Deployed Resources Reference

> **Scope:** Every Databricks **Job** (Workflow) and **Lakeflow Declarative Pipeline (DLT)**
> defined in this bundle, what runs inside each, how it's triggered, and what it costs.
> **Source of truth:** `resources/*.yml` + `databricks.yml` (variables). Deployed via
> `databricks bundle deploy -t <env>`.
> **Environments:** only **dev** is live today (qa/prod workspaces deleted 2026-07-04).

---

## 1. What's deployed (dev)

| Kind | Resource | Deployed name (dev) | Trigger |
|---|---|---|---|
| Job | `job_platform_setup` | `[dev vsingam] [dev] job_platform_setup` | On-demand |
| Job | `job_orchestration_daily` | `[dev vsingam] [dev] job_orchestration_daily` | Schedule 05:00 daily (**paused in dev**) |
| Job | `job_contract_vector_search` | `[dev vsingam] [dev] job_contract_vector_search` | File-arrival on contract volume + on-demand |
| Pipeline | `crm_postgres_ingestion` | `[dev vsingam] [dev] cdp_crm_postgres_ingestion` | On-demand (`scripts/pull_crm_from_pg.sh`) |
| Pipeline | `erp_ingestion` | `[dev vsingam] [dev] cdp_erp_ingestion` | Called by orchestration job |
| Pipeline | `transformation` | `[dev vsingam] [dev] cdp_transformation` | Called by orchestration job |

> The old file-based `crm_ingestion` pipeline was **removed** — CRM bronze now comes from
> `crm_postgres_ingestion` (Postgres/JDBC). All pipelines are **serverless + Photon**,
> `continuous: false` (triggered, not always-on).

---

## 2. Shared config (bundle variables)

Set in `databricks.yml` (`variables:`), overridable per target and at run time via `--var`.

| Variable | Default (dev) | Used by | Notes |
|---|---|---|---|
| `catalog` | `cdp_dev` | all | UC catalog this env writes to |
| `landing_volume` | `/Volumes/cdp_dev/landing/files` | erp_ingestion | file landing root |
| `pipeline_channel` | `CURRENT` | all pipelines | DLT runtime channel |
| `pipeline_development` | `false` | all pipelines | dev-mode fail-fast vs prod auto-retry |
| `contracts_schema` | `contracts` | contract job | isolated schema for contract docs |
| `vs_endpoint` | `cdp_contracts_vs` | contract job | ⚠️ **always-on billed** VS endpoint |
| `pg_host` / `pg_port` / `pg_db` / `pg_user` | ngrok-injected / `5432` / `cdp_crm` / `databricks_reader` | crm_postgres_ingestion | Postgres over ngrok; password from secret scope `cdp` |
| `notifications_email` | `vsingam@mhktechinc.com` | jobs | failure alerts |

---

## 3. Jobs (Workflows)

### 3.1 `job_platform_setup` — one-time / on-demand governance bootstrap
**Purpose:** create catalog/schemas/volume, apply RBAC, bind masks/row-filters/tags.
**Trigger:** on-demand. **Compute:** serverless SQL notebooks. **Domain tag:** `governance`.

```
create_catalogs_schemas ──► grants_personas ──► masking_row_filters
 (00_*.sql)                  (01_*.sql)          (02_*.sql — env-strict guard)
```

| Task | Notebook | Does |
|---|---|---|
| `create_catalogs_schemas` | `notebooks/setup/00_create_catalogs_schemas.sql` | Catalog, schemas, landing volume |
| `grants_personas` | `notebooks/setup/01_grants_personas.sql` | Persona RBAC grants |
| `masking_row_filters` | `notebooks/setup/02_masking_row_filters.sql` | Column masks + row filters + tags; `env` drives the prod-strict `gold.is_prod` guard |

**Run:** `databricks bundle run job_platform_setup -t dev`

---

### 3.2 `job_orchestration_daily` — daily ERP → transformation
**Purpose:** daily batch: ingest ERP + reference to bronze, then build silver/gold.
**Trigger:** schedule `0 0 5 * * ?` (05:00 America/New_York) — **auto-paused in dev**, fires only in qa/prod. **Domain tag:** `orchestration`.

```
erp_ingestion (pipeline) ──► transformation (pipeline)
 full_refresh: false          full_refresh: false
```

| Task | Runs | Notes |
|---|---|---|
| `erp_ingestion` | pipeline `erp_ingestion` | ERP + reference files → `bronze.*` |
| `transformation` | pipeline `transformation` | silver + gold; depends on `erp_ingestion` |

> **CRM is NOT in this job.** CRM bronze is refreshed **independently, on-demand** via
> `crm_postgres_ingestion` (Postgres pull). The transformation reads whatever `bronze_crm_*`
> currently exists — so refresh CRM before relying on downstream gold.

**Run manually:** `databricks bundle run job_orchestration_daily -t dev`

---

### 3.3 `job_contract_vector_search` — contract PDFs → RAG index
**Purpose:** ingest contract PDFs and maintain the Vector Search index for contract RAG.
**Trigger:** **file-arrival** on `/Volumes/{catalog}/{contracts_schema}/raw_contract_files/` (no polling compute) **+** on-demand. **Domain tag:** `contracts`.
**Params:** `catalog`, `schema` (=`contracts`), `vs_endpoint` (=`cdp_contracts_vs`).
**Special env:** `index_sync` task runs on `vs_env` (serverless) with `databricks-vectorsearch` + `databricks-langchain`.

```
ddl ─► bronze_ingest ─► silver_parse_chunk ─► gold_merge ─► index_sync
 │        │                 │                    │            │
 DDL      Auto Loader       ai_parse_document    MERGE on     Delta Sync
 schema/  binaryFile,       + contract-aware     chunk_id +   index (TRIGGERED,
 volume   availableNow      chunking; dead-      is_current   managed gte-large-en)
                            letter failures      amendments
```

| Task | Notebook | Output |
|---|---|---|
| `ddl` | `ddl/contract_vector_search.sql` | `{catalog}.contracts` schema + `raw_contract_files` volume |
| `bronze_ingest` | `01_bronze_ingest.py` | `bronze_raw_contract_docs` (Auto Loader binaryFile) |
| `silver_parse_chunk` | `02_silver_parse_chunk.py` | `silver_parsed_contracts` (+ `silver_parse_failures` dead-letter) |
| `gold_merge` | `03_gold_merge.py` | `gold_contract_chunks` (CDF on; amendment/`is_current`) |
| `index_sync` | `04_index_sync.py` | `contract_chunks_index` (Delta Sync, TRIGGERED) |

**Backfill = just run it** — the empty Auto Loader checkpoint drains all existing PDFs on the
first run; later runs pick up only new files. **Re-sync only:**
`databricks bundle run job_contract_vector_search -t dev --only index_sync`
**Full run:** `databricks bundle run job_contract_vector_search -t dev` *(spins up compute)*

---

## 4. Pipelines (Lakeflow / DLT)

All: `serverless: true`, `photon: true`, `continuous: false`, channel `${pipeline_channel}`,
dev-mode `${pipeline_development}`.

### 4.1 `crm_postgres_ingestion` — Postgres CRM → bronze (on-demand)
- **Target:** `{catalog}.bronze` · **Module:** `src/pipelines/ingestion/crm_postgres_jdbc.py`
- **Source:** local **PostgreSQL over ngrok (JDBC)**; one bronze table per entity → `bronze.crm_pg_*`
- **Secrets:** reader password from secret scope `cdp` / key `pg_reader_password` (via `dbutils.secrets`, not in config)
- **Trigger:** not scheduled — run with `scripts/pull_crm_from_pg.sh` (auto-detects the live ngrok host/port and injects them via `bundle deploy --var`, since the endpoint changes each restart)

### 4.2 `erp_ingestion` — ERP + reference files → bronze
- **Target:** `{catalog}.bronze` · **Modules:** `erp_autoloader.py`, `reference_autoloader.py`
- **Source:** landing files under `${landing_volume}` → `bronze.erp_*` and reference tables (Auto Loader)
- **Trigger:** invoked by `job_orchestration_daily` (or run standalone)

### 4.3 `transformation` — silver + gold
- **Default publish schema:** `gold` (silver flows self-publish to `silver`)
- **Includes (glob):**
  - **silver/** — `customer_master`, `contract_order_conformance`, `invoice_payment_recon`, `product_territory_standardization`, `activity_case_enrichment`
  - **gold/** — `customer_360`, `revenue_pipeline`, `collections_risk`, `account_health_support`
- **Reads:** `bronze_crm_*` (from Postgres pull) + `bronze_erp_*` / reference
- **Trigger:** invoked by `job_orchestration_daily` after `erp_ingestion`

---

## 5. How they fit together

```
 job_platform_setup ......... one-time: catalogs, schemas, grants, masks
        │
        ▼
 crm_postgres_ingestion (on-demand, Postgres/JDBC) ─┐
                                                     ├─► bronze.*  ─►  transformation ─► silver.* + gold.*
 job_orchestration_daily: erp_ingestion (files) ────┘        (daily, paused in dev)

 job_contract_vector_search (file-arrival): PDFs ─► contracts.* ─► contract_chunks_index ─► RAG retriever
   (independent lane — its own `contracts` schema + Vector Search endpoint)
```

---

## 6. Cost & operational notes

- **Vector Search endpoint `cdp_contracts_vs` is always-on billed** whether or not the job runs
  or anyone queries it. It's the one standing cost here. Delete it to stop the charge; recreate
  when needed (only dev is provisioned).
- Everything else is **triggered serverless** — no idle compute. Pipelines are `continuous: false`;
  the contract index is `TRIGGERED`; bronze uses `availableNow`.
- **Deploy ≠ run.** `bundle deploy` only ships definitions (no compute). A job/pipeline **run**
  spins up serverless compute (billed for the run).
- **Dev schedule is paused** by bundle development mode — `job_orchestration_daily` won't fire on
  its cron until deployed to a `production`-mode target.
- **qa/prod don't exist** — deploy/run only `-t dev` until those workspaces are re-provisioned.
