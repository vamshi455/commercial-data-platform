# Commercial Data Platform on Snowflake — Exact Build Plan

> Snowflake-native rebuild of this Databricks lakehouse. Same business goal — unify a
> Salesforce-like **CRM** and an SAP-like **ERP** into a governed **medallion** warehouse
> with CI/CD, MDM/identity resolution, DQ/SLA observability, contract vector search, and
> governed AI agents — implemented entirely on the Snowflake stack.

**Databases (one per env):** `CDP_DEV`, `CDP_QA`, `CDP_PROD`
**Schemas per database:** `LANDING`, `BRONZE`, `SILVER`, `GOLD`, `OPS`, `SANDBOX` (dev only), `REF`, `GOVERNANCE`
**Reporting/consumption:** Snowsight dashboards, Cortex Analyst, Cortex Search, Cortex Agents.

---

## 1. Component mapping (Databricks → Snowflake)

| Concern | Databricks (current) | Snowflake (target) |
|---|---|---|
| Governance container | Unity Catalog: catalog → schema | Database (`CDP_<ENV>`) → schema |
| Raw file landing | UC Volume on ADLS Gen2 | **External stage** (ADLS/S3) or **internal stage** + **directory table** |
| Incremental ingestion | Auto Loader (`cloudFiles`) | **Snowpipe** (auto-ingest via storage notifications) → bronze; **Snowpipe Streaming** for continuous |
| Declarative transforms + DAG | Lakeflow / DLT declarative pipelines | **Dynamic Tables** (declarative, incremental, auto-DAG) + **Streams & Tasks** where imperative MERGE/SCD2 is needed |
| Data-quality expectations | `@dlt.expect_or_drop / expect` | **Data Metric Functions (DMFs)** + quarantine `WHERE` splits; optional **dbt tests** / Great Expectations |
| Transform language | PySpark | **Snowpark Python** (DataFrame API, ~1:1 port) or SQL in Dynamic Tables |
| Table format (internal) | Delta Lake | Snowflake native (FDN) tables |
| Table format (external/open) | Managed Iceberg (UC) | **Snowflake-managed Iceberg tables** (Open Catalog / Polaris REST catalog) |
| CDC / Change Data Feed | Delta CDF | **Streams** |
| SCD2 dimensions | `APPLY CHANGES` | **Streams + Task MERGE**, or **dbt snapshots** |
| Compute | Photon / serverless clusters | **Virtual warehouses** (XS→) + **serverless tasks** |
| Orchestration | Databricks Workflows (jobs) | **Task graphs (DAGs)**, serverless tasks, triggered by stream freshness |
| IaC / deploy unit | Databricks Asset Bundles (`databricks.yml`) | **Snowflake CLI** (`snow` + `snowflake.yml`) for objects, **dbt** for transforms, **schemachange** or **Terraform** for migrations |
| CI/CD auth | GitHub OIDC → SP (WIF), no secrets | GitHub Actions + **key-pair (JWT) auth** or **external OAuth**; per-env service role |
| RBAC | UC groups / personas | **RBAC role hierarchy**: functional roles → access roles → objects |
| Column masking | UC column masks (`SET MASK`) | **Masking policies** (Dynamic Data Masking) |
| Row filtering | UC row filters | **Row Access Policies** |
| Tags / classification | UC tags | **Object Tags** + **automatic sensitive-data classification** (`SYSTEM$CLASSIFY`) |
| Lineage | `system.access.*_lineage` | **`SNOWFLAKE.ACCOUNT_USAGE.OBJECT_DEPENDENCIES`**, `ACCESS_HISTORY`, native Horizon lineage |
| Cost / usage | `system.billing.usage` | `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`, `ORGANIZATION_USAGE` |
| Ops event log | `ops` schema + DLT event log | `OPS` schema + `TASK_HISTORY`, `DYNAMIC_TABLE_REFRESH_HISTORY`, **event tables**, DMF result tables |
| Dashboards | Databricks SQL | **Snowsight** dashboards + Streamlit-in-Snowflake |
| Vector / RAG search | Vector Search index | **Cortex Search service** (managed hybrid vector+keyword) over parsed chunks; `AI_EMBED` + `VECTOR` type as the low-level path |
| Text-to-SQL / Genie | AI/BI Genie | **Cortex Analyst** over a semantic model (YAML) |
| Agents | Mosaic AI Agent Framework | **Cortex Agents** (+ Cortex Analyst & Cortex Search as tools); Snowpark function-calling for code-first |
| Model serving | MLflow serving | Cortex functions / **Snowpark Container Services** |

**Key architectural swap:** DLT's "declare the table, engine builds the DAG + does DQ inline"
becomes **Dynamic Tables** (declaration + incremental refresh + dependency DAG) with **DMFs**
for the expectation layer. Where DLT used `APPLY CHANGES` for SCD2 (identity/customer master),
Snowflake uses **Streams + Tasks (MERGE)** or **dbt snapshots** — Dynamic Tables alone do not
express SCD2 history.

---

## 2. Target repository layout

```text
commercial-data-platform/            (same repo, snowflake/ track)
├── snowflake.yml                     ← Snowflake CLI project: dev/qa/prod definitions
├── snowflake/
│   ├── objects/                      ← declarative DDL (databases, schemas, warehouses, stages, roles)
│   │   ├── 00_databases_schemas.sql
│   │   ├── 01_warehouses.sql
│   │   ├── 02_roles_grants.sql       ← functional + access role hierarchy
│   │   ├── 03_stages_pipes.sql       ← external stage, file formats, directory tables, Snowpipe
│   │   └── 04_ref_seed.sql
│   ├── governance/
│   │   ├── masking_policies.sql      ← email/phone/tax_id/free_text (was masking_functions.sql)
│   │   ├── row_access_policies.sql   ← territory/region row filters
│   │   ├── tags_classification.sql   ← object tags + SYSTEM$CLASSIFY
│   │   └── grants.sql                ← least-privilege SELECT to CDP_AI_APP_USERS etc.
│   ├── ingestion/                    ← Snowpipe + COPY INTO landing→bronze
│   ├── bronze/                       ← bronze tables/streams + audit columns
│   ├── silver/                       ← Snowpark + dynamic tables + MDM (streams/tasks)
│   ├── gold/                         ← 7 dynamic-table data products + Iceberg externals
│   ├── ops/                          ← DMFs, dq_results, sla_tracking, freshness views
│   └── cortex/
│       ├── search/                   ← Cortex Search service for contracts (was contract_vector_search)
│       ├── analyst/                  ← semantic model YAML for Cortex Analyst
│       └── agents/                   ← 5 governed Cortex Agents (revenue, health, steward, ops, finance)
├── dbt/                              ← OPTIONAL: transforms + tests + snapshots (alt to Snowpark)
│   ├── models/{bronze,silver,gold}/
│   ├── snapshots/                    ← SCD2 customer/product hierarchy
│   └── tests/
├── data_gen/                         ← REUSE as-is (CRM/ERP/reference generators) — writes to stage
├── snowpark/                         ← Snowpark Python transforms (port of src/pipelines/silver/*)
├── tests/                            ← pytest for DQ + config validation
├── .github/workflows/                ← ci.yml, deploy-qa.yml, deploy-prod.yml (snow CLI + key-pair)
└── docs/                             ← this plan + architecture/governance/pipelines (Snowflake)
```

`data_gen/` and much of `docs/` are **reused unchanged** — only the delivery/runtime stack changes.

---

## 3. Phased plan (mirrors the 7 original phases)

### Phase 1 — Foundation
- **Objects:** create `CDP_DEV/QA/PROD`; schemas `LANDING/BRONZE/SILVER/GOLD/OPS/REF/GOVERNANCE` (+`SANDBOX` dev); warehouses `CDP_INGEST_WH`, `CDP_TRANSFORM_WH`, `CDP_BI_WH` (XS, auto-suspend 60s).
- **RBAC:** functional roles `CDP_PLATFORM_ENGINEER`, `CDP_DATA_STEWARD`, `CDP_FINANCE_ANALYST`, `CDP_CUSTOMER_SUCCESS`, `CDP_AI_APP_USERS`; access roles per schema (`CDP_GOLD_R`, `CDP_SILVER_R`, `CDP_BRONZE_RW`…); grant access roles to functional roles.
- **IaC:** `snowflake.yml` + `snowflake/objects/*.sql`; `snow` CLI validates and deploys per connection (dev/qa/prod).
- **Accept:** `snow sql -f` applies cleanly to all three DBs; roles created and grantable; `snow app`/`snow object list` shows objects.

### Phase 2 — Synthetic sources (reuse)
- Keep `data_gen/` generators (CRM/ERP/reference, seeded dupes/PII/edge cases, referential integrity, CRM↔ERP crosswalk JSON).
- Change only the sink: `PUT` files to `@CDP_<ENV>.LANDING.CDP_STAGE/{crm,erp,ref}/<entity>/dt=YYYY-MM-DD/` (or land to ADLS/S3 external stage).
- **Accept:** files visible via `LIST @CDP_STAGE` and the **directory table**; FK integrity + seeded defects present.

### Phase 3 — Bronze ingestion
- **File formats** (CSV/JSON) + **external/internal stage** + **directory table** per source.
- **Snowpipe** (`CREATE PIPE … AUTO_INGEST=TRUE`) per entity → `BRONZE.<src>_<entity>` with audit columns `_INGESTED_AT`, `_SOURCE_FILE (METADATA$FILENAME)`, `_BATCH_ID`, `_ERROR/_REJECTED` (via `ON_ERROR=CONTINUE` + `VALIDATION_MODE`/rejected-record table = the `_rescued_data` analogue).
- Schema drift: `INFER_SCHEMA` + `MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE` + a `VARIANT _RAW` catch-all column so new source fields are never lost.
- **Accept:** every landed file lands in `BRONZE.*` exactly once (Snowpipe load-history idempotency); audit cols populated; drift captured in `_RAW`.

### Phase 4 — Silver conformance + MDM
- **Port `src/pipelines/silver/*` PySpark → Snowpark Python** (near 1:1: `normalize_name`, `normalize_domain`, `surrogate_key = SHA2(...)`, dedup windows).
- **Customer MDM / identity resolution** (the core problem): crosswalk join → deterministic name+domain → survivorship → stable `CUSTOMER_SK`. Because it needs SCD2 + steward overrides, implement as **Streams on bronze + a Task running a MERGE** into `SILVER.CUSTOMER` (or **dbt snapshot**). Emit `SILVER.XREF_CUSTOMER` crosswalk + an MDM **review queue** table.
- Other silver (invoice/payment recon, contract/order conformance, product/territory standardization, activity/case enrichment) as **Dynamic Tables** (`TARGET_LAG='1 hour'`, incremental).
- **DQ = DMFs:** `SYSTEM$` built-ins (NULL_COUNT, DUPLICATE_COUNT, UNIQUE_COUNT) + custom DMFs (valid amount, known currency, referential sanity) scheduled on silver tables; results → `OPS.DQ_RESULTS`. Hard failures routed to `SILVER.<t>_QUARANTINE` via a `WHERE` split.
- **PII masking** applied here (see Phase 6 policies): `SILVER.CONTACT.work_email/mobile_phone`.
- **Accept:** `SILVER.CUSTOMER` unique `CUSTOMER_SK`; recon status populated; DMFs recording; quarantine non-empty on seeded defects; review queue produced.

### Phase 5 — Gold publication
- Seven products as **Dynamic Tables** (or dbt models) keyed on `CUSTOMER_SK`:
  `GOLD.CUSTOMER_360`, `REVENUE_PIPELINE`, `BOOKINGS_VS_BILLINGS`, `COLLECTIONS_RISK`,
  `SUPPORT_PERFORMANCE`, `ACCOUNT_HEALTH`, `RENEWAL_RISK`.
- **Selective open format:** publish externally-consumed products (e.g. `REVENUE_PIPELINE`,
  `BOOKINGS_VS_BILLINGS`) as **Snowflake-managed Iceberg tables** exposed via Open Catalog —
  the Managed-Iceberg-for-external-consumers analogue.
- **Curated views** (masked, agent-facing) over each product; **Snowsight dashboards** + optional Streamlit app for KPIs.
- **Semantic model YAML** for Cortex Analyst (KPI grains/metrics) authored here.
- **Accept:** all 7 materialize and reconcile to source totals; Iceberg products queryable by an external engine; dashboards render.

### Phase 6 — Governance & operations
- **Masking policies** (port `masking_functions.sql`): `MASK_EMAIL/PHONE/TAX_ID/FREE_TEXT`, env-guarded (strict in prod via `CURRENT_ROLE()`/tag), privileged roles see clear text. Bind with `ALTER TABLE … MODIFY COLUMN … SET MASKING POLICY`.
- **Row access policies:** territory/region scoping for CS/finance roles.
- **Tags + classification:** `SYSTEM$CLASSIFY` to auto-tag PII/financial columns; propagate masking by tag (`ASSOCIATE` policy with tag).
- **Lineage/observability:** views over `ACCOUNT_USAGE.OBJECT_DEPENDENCIES`, `ACCESS_HISTORY`, `TASK_HISTORY`, `DYNAMIC_TABLE_REFRESH_HISTORY`; `OPS.SLA_TRACKING` (freshness/`TARGET_LAG` breaches), `OPS.DQ_RESULTS` (DMF output).
- **Cost:** views over `WAREHOUSE_METERING_HISTORY` for per-warehouse/domain attribution; auto-suspend + resource monitors.
- **CI/CD:** GitHub Actions — `ci.yml` (`snow sql` lint + `dbt build` on dev), `deploy-qa.yml`/`deploy-prod.yml` (gated, environment approval); **key-pair JWT** auth, per-env service role, no stored passwords.
- **Accept:** PR→dev→qa→prod promotion with approval gate; lineage queryable; DMF + SLA tracked; least-privilege verified.

### Phase 7 — Contract vector search + AI agents
- **Contract vector search** (port `src/contract_vector_search/`): ingest contract docs to stage → parse/chunk (Snowpark, reuse `chunking.py`/`metadata_extract.py`) into `SILVER.CONTRACT_CHUNKS` → build a **Cortex Search service** on the chunk text + metadata. Retriever becomes `SEARCH_PREVIEW` / the Cortex Search REST call (replaces the manual embed + `VECTOR_COSINE_SIMILARITY` index sync). Low-level fallback: `AI_EMBED` into a `VECTOR(FLOAT, 1024)` column + `VECTOR_COSINE_SIMILARITY`.
- **5 governed agents** as **Cortex Agents**, each wired to Cortex Analyst (semantic model over curated gold) + Cortex Search (contracts), running as `CDP_AI_APP_USERS`:
  `revenue_insights`, `customer_health`, `data_steward`, `platform_ops`, `finance_reconciliation`.
  Guardrails identical to today: SELECT-only on approved masked views, no bronze/PII, every call audited via `ACCESS_HISTORY`.
- **Accept:** agents answer sample prompts using only governed objects; no bronze/PII reachable; queries audited.

---

## 4. Concrete pattern translations

**Auto Loader → Snowpipe (bronze ingest):**
```sql
CREATE FILE FORMAT ref.ff_csv TYPE=CSV SKIP_HEADER=1 ERROR_ON_COLUMN_COUNT_MISMATCH=FALSE;
CREATE STAGE landing.cdp_stage
  URL='azure://.../landing' STORAGE_INTEGRATION=cdp_azure_int
  DIRECTORY=(ENABLE=TRUE) FILE_FORMAT=ref.ff_csv;

CREATE PIPE bronze.pipe_crm_accounts AUTO_INGEST=TRUE AS
COPY INTO bronze.crm_accounts
FROM (
  SELECT $1, ..., METADATA$FILENAME AS _source_file,
         CURRENT_TIMESTAMP() AS _ingested_at, TO_VARCHAR(CURRENT_DATE) AS _batch_id
  FROM @landing.cdp_stage/crm/accounts/
)
MATCH_BY_COLUMN_NAME=CASE_INSENSITIVE ON_ERROR=CONTINUE;
```

**DLT table + expectations → Dynamic Table + DMF:**
```sql
CREATE DYNAMIC TABLE silver.erp_invoices
  TARGET_LAG='1 hour' WAREHOUSE=CDP_TRANSFORM_WH AS
SELECT invoice_id, CAST(invoice_amount AS NUMBER(18,2)) AS invoice_amount, currency_code, ...
FROM bronze.erp_invoices
WHERE invoice_id IS NOT NULL AND invoice_amount >= 0;   -- expect_or_drop analogue

-- expectation as a DMF (warn-only metric feeding OPS.DQ_RESULTS)
CREATE DATA METRIC FUNCTION ops.unknown_currency_count(t TABLE(currency_code STRING))
  RETURNS NUMBER AS $$ SELECT COUNT_IF(currency_code NOT IN (SELECT currency_code FROM ref.currency_rates)) FROM t $$;
ALTER TABLE silver.erp_invoices ADD DATA METRIC FUNCTION ops.unknown_currency_count ON (currency_code);
```

**UC column mask → Masking policy:**
```sql
CREATE MASKING POLICY governance.mask_email AS (email STRING) RETURNS STRING ->
  CASE
    WHEN NOT governance.is_prod() THEN email
    WHEN IS_ROLE_IN_SESSION('CDP_DATA_STEWARD') OR IS_ROLE_IN_SESSION('CDP_CUSTOMER_SUCCESS') THEN email
    WHEN email IS NULL OR POSITION('@' IN email)=0 THEN '****'
    ELSE '****@' || SPLIT_PART(email,'@',2)
  END;
ALTER TABLE gold.customer_360 MODIFY COLUMN primary_email SET MASKING POLICY governance.mask_email;
```

**PySpark surrogate key → Snowpark (unchanged logic):**
```python
from snowflake.snowpark.functions import sha2, concat_ws, coalesce, lit, col
def surrogate_key(*cols):
    parts = [coalesce(col(c).cast("string"), lit("")) for c in cols]
    return sha2(concat_ws(lit("||"), *parts), 256)
```

---

## 5. Decisions to confirm before building

1. **Transform engine:** Snowpark Python (closest port of the PySpark silver logic) **or** dbt (cleaner tests/snapshots/lineage, more "analytics-engineering" idiom). Recommendation: **dbt for silver/gold + Dynamic Tables materialization; Snowpark only for the fuzzy MDM step.**
2. **IaC:** `snow` CLI declarative DDL **or** Terraform (`Snowflake-Labs/snowflake` provider) **or** schemachange. Recommendation: **`snow` CLI + schemachange for migrations**; Terraform only if you already run it.
3. **Cloud for the external stage:** ADLS Gen2 (matches current Azure workspace) vs S3/GCS — pick to match your Snowflake account's cloud region for egress.
4. **Iceberg:** enable Open Catalog now, or ship Delta-analogue native tables first and add Iceberg externals later.
5. **Scope of this branch:** scaffold all 7 phases, or start Phase 1–3 (foundation + ingest) and iterate.

---

## 6. Suggested execution order
```
Phase 1 → 2 → 3 → 4 → 5 → 6 → 7
foundation  data  bronze  silver  gold  gov/ops  cortex+agents
```
Reuse `data_gen/` and `docs/business-domain*`, `source-systems`, `data-contracts` unchanged; everything else is re-platformed to the Snowflake stack above.
