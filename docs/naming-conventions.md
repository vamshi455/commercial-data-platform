# Commercial Data Platform — Naming Conventions

> **Audience:** Everyone building in CDP — platform/data/analytics engineers and stewards.
> **Scope:** Canonical naming for catalogs, schemas, tables, columns, views, jobs/pipelines, bundle resources, tags, and groups. Consistency here is what makes governance, lineage, and CI/CD predictable.

**Related docs:**
- [`architecture.md`](./architecture.md) — the medallion layers these names map onto
- [`source-systems.md`](./source-systems.md) — the CRM/ERP entities that drive table names
- [`data-contracts.md`](./data-contracts.md) — contracts reference these names exactly

---

## 1. Principles

1. **Lowercase `snake_case` everywhere** — catalogs, schemas, tables, columns, jobs. No camelCase, no spaces, no hyphens (except bundle resource files where noted).
2. **Layer is encoded by schema, not table prefix.** A table named `crm_accounts` exists in `bronze`, `silver`, and (where applicable) is consumed from `gold`. The schema tells you the layer.
3. **Domain prefixes** identify the source domain: `crm_` and `erp_`. Conformed/derived objects use modeling prefixes (`dim_`, `fact_`, `xref_`, `ref_`).
4. **Environment is the catalog**, never embedded in table names.
5. **Stable, descriptive, no abbreviations** unless industry-standard (e.g., `gl`, `oli`, `so`, `po`, `sk`).

---

## 2. Catalogs — `cdp_<env>`

One catalog per environment. The catalog is the unit of environment isolation.

| Catalog | Environment | Notes |
|---|---|---|
| `cdp_dev` | Development | Includes `sandbox` schema |
| `cdp_qa` | QA / pre-prod | No `sandbox` |
| `cdp_prod` | Production | No `sandbox` |

Pattern: `cdp_<env>` where `<env>` ∈ `{dev, qa, prod}`.

---

## 3. Schemas — layer-based

Fixed set of schemas per catalog; names are identical across environments.

| Schema | Purpose | Format | Present in |
|---|---|---|---|
| `landing` | Raw immutable source files (UC Volume) | Files | all |
| `bronze` | As-ingested Delta tables | Delta | all |
| `silver` | Cleaned/conformed/modeled tables | Delta | all |
| `gold` | Business data products | Delta + select Managed Iceberg | all |
| `ops` | Run logs, DQ metrics, checkpoints, reconciliation | Delta | all |
| `sandbox` | Ad-hoc experimentation | Delta | **dev only** |

> Reference data lives in `silver` under a `ref_`/`dim_` prefix (a logical `ref` namespace), not a separate schema.

---

## 4. Tables

### 4.1 Source-derived tables — `<domain>_<entity>`

| Domain | Prefix | Examples |
|---|---|---|
| CRM | `crm_` | `crm_accounts`, `crm_contacts`, `crm_leads`, `crm_opportunities`, `crm_opportunity_line_items`, `crm_quotes`, `crm_contracts`, `crm_activities`, `crm_cases`, `crm_users`, `crm_territories` |
| ERP | `erp_` | `erp_customers`, `erp_vendors`, `erp_products`, `erp_sales_orders`, `erp_sales_order_items`, `erp_billing_documents`, `erp_invoices`, `erp_payments`, `erp_purchase_orders`, `erp_gl_entries`, `erp_cost_centers`, `erp_profit_centers`, `erp_currency_rates` |

The same `<domain>_<entity>` name is reused across `bronze` and `silver` (the schema disambiguates the layer). SCD2 history tables append `_hist` (e.g., `silver.crm_opportunities_hist`).

### 4.2 Conformed / derived tables (silver)

| Prefix | Meaning | Examples |
|---|---|---|
| `dim_` | Conformed dimension | `dim_customer`, `dim_date`, `dim_product`, `dim_user`, `dim_territory` |
| `fact_` | Conformed fact | `fact_invoice`, `fact_payment`, `fact_opportunity` |
| `xref_` | Crosswalk / mapping | `xref_customer` (CRM↔ERP identity) |
| `ref_` | Reference data | `ref_currency_rates`, `ref_product_hierarchy`, `ref_fiscal_calendar` |

### 4.3 Gold products — business name (no domain prefix)

Gold tables are named for the **business product**, not the source. They are the published, consumer-facing surface.

| Gold product | Table |
|---|---|
| Customer 360 | `gold.customer_360` |
| Revenue pipeline | `gold.revenue_pipeline` |
| Bookings vs billings | `gold.bookings_vs_billings` |
| Collections risk | `gold.collections_risk` |
| Support performance | `gold.support_performance` |
| Account health | `gold.account_health` |
| Renewal risk | `gold.renewal_risk` |

### 4.4 Views

| View type | Pattern | Example |
|---|---|---|
| Consumer-facing / masked | `v_<object>` | `gold.v_customer_360_masked` |
| Versioned (contract) | `v_<object>_v<major>` | `gold.v_revenue_pipeline_v2` |
| Persona-scoped | `v_<object>_<persona>` | `gold.v_collections_risk_finance` |

---

## 5. Columns

### 5.1 General rules
- `snake_case`, descriptive, no abbreviations except standard ones.
- Booleans use `is_` / `has_` prefixes (`is_won`, `is_disputed`).
- Dates end in `_date`, timestamps in `_at`, amounts carry currency intent (`amount`, `amount_usd`).

### 5.2 Key conventions

| Key type | Convention | Example |
|---|---|---|
| Surrogate key | `<entity>_sk` (system-generated, stable) | `account_sk`, `invoice_sk`, `master_customer_id` |
| Natural / business key | source field name, kept as-is | `account_id`, `invoice_id`, `customer_id` |
| Foreign key | referenced entity's natural key | `account_id`, `billing_doc_id` |

### 5.3 Audit columns (added at bronze, carried forward)

| Column | Type | Meaning |
|---|---|---|
| `_ingested_at` | TIMESTAMP | When the row was ingested into bronze |
| `_source_file` | STRING | Source file path the row came from (`_metadata.file_path`) |
| `_batch_id` | STRING | Ingestion batch/run identifier |
| `_rescued_data` | STRING | Auto Loader rescued/unmatched fields (bronze only) |

Audit columns are prefixed with a single underscore to visually separate platform metadata from business columns.

---

## 6. Jobs, Pipelines, and Bundle Resources

### 6.1 Workflows (jobs) — `job_<scope>_<purpose>`

| Pattern | Example |
|---|---|
| `job_ingest_<domain>` | `job_ingest_crm`, `job_ingest_erp` |
| `job_pipeline_<layer>` | `job_pipeline_silver`, `job_pipeline_gold` |
| `job_<product>` | `job_revenue_pipeline_refresh` |
| `job_ops_<purpose>` | `job_ops_dq_report`, `job_ops_reconciliation` |

### 6.2 Lakeflow Declarative Pipelines — `pipe_<scope>`

| Pattern | Example |
|---|---|
| `pipe_<domain>_bronze` | `pipe_crm_bronze`, `pipe_erp_bronze` |
| `pipe_<layer>` | `pipe_silver`, `pipe_gold` |
| `pipe_<product>` | `pipe_customer_360` |

### 6.3 Databricks Asset Bundle resources

| Resource | Pattern | Example |
|---|---|---|
| Bundle name | `cdp-<component>` (file/resource names allow hyphens) | `cdp-platform` |
| Target | `<env>` | `dev`, `qa`, `prod` |
| Job resource key | `job_<...>` (matches §6.1) | `job_ingest_crm` |
| Pipeline resource key | `pipe_<...>` (matches §6.2) | `pipe_silver` |
| Resource YAML files | `resources/<type>_<name>.yml` | `resources/job_ingest_crm.yml`, `resources/pipe_silver.yml` |

> Bundle/file names may use hyphens (`cdp-platform`); Databricks object names (catalogs, schemas, tables, jobs, pipelines) use underscores.

---

## 7. Tags / Classification

Unity Catalog tags use `key = value`. CDP standard tag keys:

| Tag key | Allowed values | Applied to |
|---|---|---|
| `sensitivity` | `public_reference`, `internal_only`, `pii`, `financial_sensitive`, `restricted_free_text` | columns / tables |
| `domain` | `crm`, `erp`, `conformed`, `reference` | tables / schemas |
| `layer` | `landing`, `bronze`, `silver`, `gold`, `ops` | tables / schemas |
| `data_product` | `customer_360`, `revenue_pipeline`, ... | gold tables |
| `owner` | UC group name | tables |
| `contract_version` | semver string | published tables |

---

## 8. Groups (personas)

Unity Catalog groups follow `cdp_<persona>`.

| Group | Responsibility |
|---|---|
| `cdp_platform_engineers` | Platform, UC admin, bundles, compute policies |
| `cdp_data_engineers` | Ingestion + silver/gold pipelines (producers) |
| `cdp_analytics_engineers` | Semantic models, gold modeling, views |
| `cdp_sales_analysts` | Consume pipeline/sales gold |
| `cdp_finance_analysts` | Consume financial gold (`financial_sensitive` access) |
| `cdp_customer_success` | Consume account health / renewal / support gold |
| `cdp_data_stewards` | Classification, identity overrides, contract approval |
| `cdp_ai_app_users` | AI/agent/Genie access to gold |

---

## 9. Layer → Table-Naming Reference

| Layer (schema) | Object pattern | CRM example | ERP example | Conformed/derived example |
|---|---|---|---|---|
| `landing` (Volume path) | `/<domain>/<entity>/<ingest_date>/` | `/crm/accounts/2026-06-26/` | `/erp/invoices/2026-06-26/` | — |
| `bronze` | `<domain>_<entity>` | `bronze.crm_accounts` | `bronze.erp_invoices` | — |
| `silver` | `<domain>_<entity>` / `dim_*` / `fact_*` / `xref_*` / `ref_*` | `silver.crm_opportunities`, `silver.crm_opportunities_hist` | `silver.erp_payments` | `silver.dim_customer`, `silver.xref_customer`, `silver.ref_currency_rates` |
| `gold` | business product name | — | — | `gold.customer_360`, `gold.bookings_vs_billings` |
| `ops` | `<purpose>` | `ops.dq_expectation_results` | `ops.reconciliation_bookings_billings` | `ops.pipeline_run_log` |

**Fully-qualified example (prod):**
`cdp_prod.silver.crm_opportunities` → consumed into → `cdp_prod.gold.revenue_pipeline`.

> ⚠️ **Known drift (tech debt, decision D2):** the *deployed* dev objects carry a
> redundant layer prefix — `bronze.bronze_erp_customers`, `silver.silver_customer`,
> `gold.gold_customer_360` — instead of the clean form above. The clean, redundancy-
> free convention in this table is the **standard**; the deployed names are to be
> renamed on the next pipeline redeploy (`@dlt.table` names + governance SQL +
> curated views). Until then, code and docs disagree — see `docs/decisions.md`.
