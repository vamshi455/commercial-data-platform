# Pipelines — Commercial Data Platform

This document describes every data pipeline in the Commercial Data Platform (CDP): the
**ingestion** layer (CRM, ERP, reference), the **silver** conformance transforms, and the
**gold** data products. It also covers the Lakeflow / Delta Live Tables (DLT) concepts the
pipelines are built on, the Auto Loader ingestion pattern, the data-quality (DQ) rule
catalog, the identity-resolution (MDM) approach, and the backfill/replay strategy.

> **Stack:** Unity Catalog · Lakeflow Connect · Auto Loader · Lakeflow Spark Declarative
> Pipelines (DLT) · Delta + Managed Iceberg (UC) · lineage system tables · Databricks Asset
> Bundles.
>
> **Catalogs / schemas:** `cdp_{dev,qa,prod}` × `landing` · `bronze` · `silver` · `gold` · `ops`
> (+ `sandbox` in dev only).
>
> **Pipeline code:** `src/pipelines/{ingestion,bronze,silver,gold}` · **Bundle resources:**
> `resources/*.yml`.

---

## 1. Medallion overview

```
        SOURCE FILES                  BRONZE                    SILVER                       GOLD
   (CRM + ERP + reference)      (Delta, raw + audit)     (Delta, conformed + DQ)     (Delta + Managed Iceberg)
 ┌───────────────────────┐   ┌───────────────────────┐ ┌────────────────────────┐ ┌────────────────────────┐
 │ /Volumes/<cat>/landing│   │ ingest as-is, append- │ │ cleanse, standardize,  │ │ business products:     │
 │ /files/{crm,erp,ref}/ │──►│ only, add _ingested_  │►│ dedup (SCD2), MDM /    │►│ customer_360,          │
 │  *.json / *.csv       │   │ at,_source_file,      │ │ identity resolution,   │ │ revenue_pipeline, ...  │
 │  (Auto Loader)        │   │ _batch_id,_rescued    │ │ reconcile, enrich, DQ  │ │ KPI semantics          │
 └───────────────────────┘   └───────────────────────┘ └────────────────────────┘ └────────────────────────┘
        streaming tables          streaming tables          STs + materialized views      materialized views
```

| Layer    | Catalog.schema     | Format                       | Table type (DLT)                          | Purpose |
|----------|--------------------|------------------------------|-------------------------------------------|---------|
| Landing  | `<cat>.landing`    | raw files in UC Volumes      | n/a (files)                               | Inbound files from generators / Lakeflow Connect |
| Bronze   | `<cat>.bronze`     | Delta                        | streaming tables                          | Raw, append-only, audited copy of source |
| Silver   | `<cat>.silver`     | Delta                        | streaming tables + materialized views     | Conformed, deduplicated, DQ-validated, mastered |
| Gold     | `<cat>.gold`       | Delta + selective Iceberg    | materialized views                        | Business data products / KPI marts |
| Ops      | `<cat>.ops`        | Delta                        | tables                                    | DQ results, pipeline metadata, SLA tracking |

---

## 2. Lakeflow / DLT concepts used

### 2.1 Streaming tables vs materialized views

| | **Streaming table** (`@dlt.table` over a streaming read) | **Materialized view** (`@dlt.table` over a batch read) |
|---|---|---|
| Reads | `spark.readStream` (e.g. Auto Loader, another ST) | `spark.read` / SQL over Delta |
| Processing | **Incremental** — only new rows since last checkpoint | Recomputed (DLT incrementalizes when it safely can) |
| State | Maintains checkpoint/offset | Stateless logical view, physically materialized |
| Used in CDP for | All bronze ingest; silver CDC targets | Silver conformed dims/facts; all gold products |

Rule of thumb in this repo: **append-heavy + late-arriving data → streaming table**;
**aggregations / joins / KPI marts → materialized view**.

### 2.2 Core decorators / DDL

```python
import dlt
from pyspark.sql import functions as F

@dlt.table(
    name="bronze_crm_accounts",
    comment="Raw CRM accounts, Auto Loader ingest, append-only.",
    table_properties={"quality": "bronze", "delta.enableChangeDataFeed": "true"},
)
@dlt.expect_or_drop("valid_account_id", "account_id IS NOT NULL")
def bronze_crm_accounts():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        .option("cloudFiles.schemaLocation", f"{schema_loc}/crm_accounts")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("rescuedDataColumn", "_rescued_data")
        .load(f"{landing}/crm/accounts/")
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_batch_id", F.lit(spark.conf.get("pipelines.batchId", "manual")))
    )
```

### 2.3 Expectations (DQ as code)

| Decorator | Behavior on failed rows | Pipeline impact | When used |
|---|---|---|---|
| `@dlt.expect("name", "cond")` | **Keep** the row | Records a metric only | Soft / observational checks |
| `@dlt.expect_or_drop("name","cond")` | **Drop** the row from output | Metric + quarantine | Bad rows must not pollute downstream |
| `@dlt.expect_or_fail("name","cond")` | **Fail** the update | Pipeline run aborts | Hard contract violations (e.g. PK null) |

Combine with `@dlt.expect_all`, `@dlt.expect_all_or_drop`, `@dlt.expect_all_or_fail` to apply
a dict of rules at once.

### 2.4 APPLY CHANGES INTO (CDC / SCD)

Used in silver to turn append-only bronze change streams into clean current-state (SCD Type 1)
or full history (SCD Type 2) dimensions.

```python
dlt.create_streaming_table("silver_dim_account")

dlt.apply_changes(
    target="silver_dim_account",
    source="bronze_crm_accounts",
    keys=["account_id"],
    sequence_by=F.col("modified_at"),     # ordering / dedup of late events
    apply_as_deletes=F.expr("op = 'DELETE'"),
    except_column_list=["op", "_rescued_data"],
    stored_as_scd_type=2,                 # 1 = current only, 2 = full history
)
```

- **SCD Type 1**: `accounts`, `contacts`, `products`, `cost_centers`, `profit_centers`,
  `currency_rates` (latest wins).
- **SCD Type 2**: `customers`, `contracts`, `territories`, `opportunities` (history matters for
  point-in-time KPIs and renewal/pipeline snapshots).

---

## 3. Auto Loader ingestion pattern

All bronze ingest uses **Auto Loader** (`cloudFiles`) for incremental, exactly-once file
discovery with schema management.

| Option | Value (CDP convention) | Why |
|---|---|---|
| `cloudFiles.format` | `json` (CRM), `csv` (ERP/reference) | Source-native format |
| `cloudFiles.schemaLocation` | `<pipeline_storage>/_schemas/<entity>` | Persists inferred/evolved schema |
| `cloudFiles.inferColumnTypes` | `true` | Infer real types, not all-string |
| `cloudFiles.schemaEvolutionMode` | `addNewColumns` | New source columns auto-added; pipeline restarts once to pick up |
| `rescuedDataColumn` | `_rescued_data` | Captures off-schema / unparseable data instead of dropping it |
| `cloudFiles.maxFilesPerTrigger` | `1000` (tunable) | Backpressure / cost control |
| `cloudFiles.useNotifications` | `false` (dev), `true` (prod, optional) | Directory listing vs file-notification mode |

**Schema evolution flow:** new column appears in a file → Auto Loader writes it to
`_rescued_data` → on next trigger with `addNewColumns`, schema evolves, the stream restarts
automatically, and the column becomes first-class.

---

## 4. Bronze audit-column convention

Every bronze table carries these columns, added at ingest:

| Column | Type | Source | Meaning |
|---|---|---|---|
| `_ingested_at` | `timestamp` | `current_timestamp()` | When the row was loaded into bronze |
| `_source_file` | `string` | `_metadata.file_path` | Exact landing file the row came from |
| `_batch_id` | `string` | `pipelines.batchId` conf / run id | Groups a logical load for replay/audit |
| `_rescued_data` | `string` (JSON) | Auto Loader `rescuedDataColumn` | Off-schema fields not matched to the table schema |

These enable lineage to the file level, idempotent reprocessing, and "where did this row come
from?" debugging.

---

## 5. Ingestion pipelines

Code: `src/pipelines/ingestion/*` · Resource: `resources/pipeline_ingestion.yml`.

| Pipeline | Source domain | Entities (→ `bronze.*`) | Format | Notes |
|---|---|---|---|---|
| `ingest_crm` | CRM (Salesforce-like) | accounts, contacts, leads, opportunities, opportunity_line_items, quotes, contracts, activities, cases, users, territories | JSON | High-volume `activities`; `_rescued_data` watched for schema drift |
| `ingest_erp` | ERP (SAP-like) | customers, vendors, products, sales_orders, sales_order_items, billing_documents, invoices, payments, purchase_orders, gl_entries, cost_centers, profit_centers, currency_rates | CSV | Numeric/locale parsing; CDF enabled for downstream APPLY CHANGES |
| `ingest_reference` | Reference / master data | currency_rates, country/region, product_hierarchy, fx_calendar | CSV/JSON | Small, slowly-changing; refreshed as MVs in silver |

> Lakeflow Connect managed connectors can replace the synthetic-file path for real
> Salesforce/SAP sources without changing downstream bronze→gold logic.

---

## 6. Silver conformance transforms

Code: `src/pipelines/silver/*` · Resource: `resources/pipeline_silver.yml`.

### 6.1 Customer mastering / identity resolution

| | |
|---|---|
| **Inputs** | `silver.dim_account` (from `bronze_crm_accounts`), `silver.dim_customer_erp` (from `bronze_erp_customers`), `bronze_crm_contacts` |
| **Logic** | Resolve CRM `accounts` ↔ ERP `customers` into a single mastered customer; assign a stable **surrogate `customer_key`**. See §10. |
| **Outputs** | `silver.dim_customer` (mastered, SCD2), `silver.xref_account_customer` (mapping CRM account_id / ERP customer_id → customer_key) |
| **Key DQ** | `expect_or_fail` customer_key not null/unique; `expect_or_drop` match_confidence ≥ threshold for auto-merge; `expect` no orphan accounts |

### 6.2 Contract + order conformance

| | |
|---|---|
| **Inputs** | `bronze_crm_contracts`, `bronze_erp_sales_orders`, `bronze_erp_sales_order_items`, `silver.xref_account_customer` |
| **Logic** | Standardize statuses/dates/currency; link contracts to orders; attach `customer_key`; normalize line-item amounts to a reporting currency via `currency_rates`. |
| **Outputs** | `silver.fact_contract`, `silver.fact_sales_order`, `silver.fact_sales_order_item` |
| **Key DQ** | `expect_or_drop` order_amount ≥ 0; `expect` end_date ≥ start_date; `expect` valid currency_code in FX table |

### 6.3 Invoice + payment reconciliation

| | |
|---|---|
| **Inputs** | `bronze_erp_billing_documents`, `bronze_erp_invoices`, `bronze_erp_payments`, `silver.fact_sales_order` |
| **Logic** | Match invoices→billing docs→orders; allocate payments to invoices (FIFO/exact-match); compute open balance, days-past-due, and a reconciliation status. |
| **Outputs** | `silver.fact_invoice`, `silver.fact_payment`, `silver.reconciliation_invoice_payment` |
| **Key DQ** | `expect_or_drop` invoice_amount > 0; `expect` paid_amount ≤ invoice_amount + tolerance; `expect` reconciliation status in enum |

### 6.4 Product + territory standardization

| | |
|---|---|
| **Inputs** | `bronze_erp_products`, `bronze_crm_territories`, reference product hierarchy |
| **Logic** | Canonicalize product codes/units; build product hierarchy; standardize territory codes and ownership; map sales users→territories. |
| **Outputs** | `silver.dim_product`, `silver.dim_territory` |
| **Key DQ** | `expect_or_fail` product_id unique; `expect` non-null territory_code; `expect` product_family in allowed set |

### 6.5 Activity + case enrichment

| | |
|---|---|
| **Inputs** | `bronze_crm_activities`, `bronze_crm_cases`, `bronze_crm_leads`, `silver.dim_customer`, `silver.dim_account` |
| **Logic** | Enrich activities/cases with `customer_key` + account hierarchy; classify activity type; derive case SLA timers; **govern free-text** (mask emails/phones in `description`/`subject`, see DQ catalog). |
| **Outputs** | `silver.fact_activity`, `silver.fact_case` |
| **Key DQ** | `expect` non-null event_timestamp; `expect_or_drop` resolvable customer_key; `expect` case priority in enum |

---

## 7. Gold data products

Code: `src/pipelines/gold/*` · Resource: `resources/pipeline_gold.yml`. All are
**materialized views**; Iceberg-format used selectively for products shared with external
engines.

| Gold product | Inputs (silver) | Logic summary | Key outputs / grain | KPIs |
|---|---|---|---|---|
| `customer_360` | dim_customer, fact_contract, fact_invoice, fact_case, fact_activity | One row per mastered customer with CRM+ERP rollups | 1 row / `customer_key` | lifetime value, open AR, active contracts, last activity |
| `revenue_pipeline` | dim_account, fact opportunity (silver), dim_territory | Open opportunities, weighted by stage probability | 1 row / opportunity (snapshot) | pipeline $, weighted pipeline, expected close |
| `bookings_vs_billings` | fact_contract, fact_sales_order, fact_invoice | Compare booked vs billed by period/customer | 1 row / customer × period | bookings, billings, gap, billing ratio |
| `collections_risk` | reconciliation_invoice_payment, fact_invoice, dim_customer | Score open AR by aging + history | 1 row / customer | total open, >90d past due, risk score |
| `support_performance` | fact_case, fact_activity, dim_customer | Case throughput / SLA attainment | 1 row / customer × period (+ agent) | cases opened/closed, SLA %, MTTR |
| `account_health` | customer_360, support_performance, fact_activity | Composite health blend of usage/AR/support/engagement | 1 row / `customer_key` | health score, trend, drivers |
| `renewal_risk` | fact_contract (SCD2), account_health, collections_risk | Score contracts approaching renewal | 1 row / contract | days-to-renewal, churn risk, ARR at risk |

**Iceberg (Managed, UC):** `customer_360`, `revenue_pipeline`, `bookings_vs_billings`
published as **UC Managed Iceberg** for interoperability (external query engines / sharing).
The rest remain Delta.

---

## 8. Data-quality rules catalog

DQ runs as DLT expectations in-pipeline; results are persisted to `ops.dq_results`.

| Rule | Entities | Layer | Severity / action |
|---|---|---|---|
| Primary key not null | all dims/facts | bronze→silver | **fail** (`expect_or_fail`) |
| Primary key unique | dim_customer, dim_product, fact_invoice | silver | **fail** |
| Surrogate `customer_key` resolves | activities, cases, orders, invoices | silver | **drop** (`expect_or_drop`) + quarantine |
| Amount ≥ 0 | order_item, invoice, payment, gl_entries | silver | **drop** |
| paid ≤ invoiced (+tolerance) | payments vs invoices | silver | **warn** (`expect`) → `ops.reconciliation_exceptions` |
| Valid currency_code in FX table | orders, invoices, contracts | silver | **drop** |
| Date sanity (end ≥ start; not future) | contracts, opportunities | silver | **warn** |
| Enum membership (status/priority/stage) | cases, opportunities, reconciliation | silver | **warn** |
| Referential: order→customer exists | sales_orders | silver | **drop** |
| PII masking applied in free-text | activities.description, cases.subject | silver | **fail** if unmasked PII detected |
| Freshness (`_ingested_at` within SLA) | all bronze | ops | **warn** → SLA alert |
| Row-count delta within band | high-volume bronze | ops | **warn** (anomaly) |

---

## 9. Identity resolution (MDM): CRM accounts ↔ ERP customers

Goal: a single mastered customer with a stable surrogate **`customer_key`** that survives
re-runs and source-key changes.

```
   CRM accounts              ERP customers
  (account_id, name,        (customer_id, name,
   tax_id, domain,           tax_id, country,
   billing addr)             address)
        │                         │
        ▼                         ▼
  ┌──────────────── normalize (uppercase, strip, unaccent, std addr) ───────────────┐
  └─────────────────────────────────────┬───────────────────────────────────────────┘
                                         ▼
            ┌──────────── DETERMINISTIC match (high precision) ───────────┐
            │  tax_id (VAT/EIN) ==  | email domain == | DUNS == |          │
            │  exact (name + country + postal)                            │
            └───────────────────────┬─────────────────────────────────────┘
                       match? ──yes──► assign / reuse customer_key
                          │ no
                          ▼
            ┌──────────── FUZZY match (recall) ───────────────────────────┐
            │  jaro_winkler(name) ≥ 0.92  AND  same country                │
            │  AND token-overlap(address) ≥ 0.8  → match_confidence score  │
            └───────────────────────┬─────────────────────────────────────┘
              conf ≥ 0.95 ──auto-merge──► customer_key
              0.80–0.95  ──► stewardship queue (ops.mdm_review) → cdp_data_stewards
              < 0.80     ──► treat as distinct customer (new key)
```

- **Surrogate key:** deterministic hash of the chosen blocking keys, persisted in
  `silver.xref_account_customer` so the same logical customer always maps to the same
  `customer_key` across runs. Manual steward overrides win and are stored as authoritative.
- **Blocking** on `country + name-soundex` keeps fuzzy comparisons tractable.
- Outputs feed every gold product that is "per customer."

---

## 10. Backfill / replay, refresh modes, channels

### 10.1 Full refresh vs incremental

| Mode | Command / mechanism | Effect | Use when |
|---|---|---|---|
| Incremental (default) | normal pipeline update | Streaming tables process only new files/CDC | Steady-state runs |
| Full refresh (one table) | `databricks bundle run <pipeline> -t <env> --full-refresh-select <table>` | Drops & recomputes that table + checkpoints | Logic change to one transform |
| Full refresh (all) | pipeline update with **Full refresh all** | Recompute everything from landing | Breaking schema/key change, DR rebuild |

### 10.2 Backfill / replay strategy

1. **Replay files:** re-land historical files into `landing/...`; Auto Loader picks up new
   paths idempotently. `_batch_id` tags the backfill.
2. **Targeted full-refresh:** only the affected silver/gold table, preserving upstream
   checkpoints to limit cost.
3. **Time-travel verification:** use Delta `VERSION AS OF` / `TIMESTAMP AS OF` to compare
   pre/post backfill row counts before promoting.
4. **Idempotency:** APPLY CHANGES dedups by `sequence_by`, so replays do not double-count.

### 10.3 Pipeline channels (`var.pipeline_channel`)

| Target | Channel | Rationale |
|---|---|---|
| `dev` | `PREVIEW` | Exercise newest Lakeflow runtime features early |
| `qa` | `CURRENT` | Match prod runtime for valid validation |
| `prod` | `CURRENT` | Stability; only GA features |

---

## 11. Pipeline dependency DAG

```
                                 ┌──────────────────────────── ingestion ────────────────────────────┐
 landing/crm/* ──cloudFiles──►   bronze_crm_*  (accounts, contacts, leads, opportunities, oli, quotes,
                                                 contracts, activities, cases, users, territories)
 landing/erp/* ──cloudFiles──►   bronze_erp_*  (customers, vendors, products, sales_orders, soi,
                                                 billing_documents, invoices, payments, purchase_orders,
                                                 gl_entries, cost_centers, profit_centers, currency_rates)
 landing/ref/* ──cloudFiles──►   bronze_ref_*  (currency_rates, country_region, product_hierarchy)
                                 └────────────────────────────────┬─────────────────────────────────────┘
                                                                  ▼  (APPLY CHANGES / SCD)
     ┌───────────────────────────────────────── silver ──────────────────────────────────────────────┐
     │  dim_account ─┐                                                                                 │
     │  dim_customer_erp ─┴──► xref_account_customer ──► dim_customer (MDM, SCD2) ◄─ dim_contact        │
     │  dim_product   dim_territory                                                                     │
     │  fact_contract ◄─┐                                                                               │
     │  fact_sales_order, fact_sales_order_item ◄── dim_customer, currency_rates                        │
     │  fact_invoice, fact_payment ──► reconciliation_invoice_payment                                  │
     │  fact_activity, fact_case ◄── dim_customer, dim_account (PII-masked)                             │
     └────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                   ▼  (materialized views)
     ┌───────────────────────────────────────── gold ───────────────────────────────────────────────┐
     │  customer_360 ◄── dim_customer, fact_contract, fact_invoice, fact_case, fact_activity            │
     │  revenue_pipeline ◄── opportunities, dim_account, dim_territory                                  │
     │  bookings_vs_billings ◄── fact_contract, fact_sales_order, fact_invoice                          │
     │  collections_risk ◄── reconciliation_invoice_payment, fact_invoice                               │
     │  support_performance ◄── fact_case, fact_activity                                                │
     │  account_health ◄── customer_360, support_performance                                            │
     │  renewal_risk ◄── fact_contract, account_health, collections_risk                                │
     └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. File map

| Concern | Location |
|---|---|
| Ingestion pipelines | `src/pipelines/ingestion/` |
| Bronze definitions | `src/pipelines/bronze/` |
| Silver transforms | `src/pipelines/silver/` |
| Gold products | `src/pipelines/gold/` |
| Pipeline resources (DABs) | `resources/pipeline_*.yml` |
| Orchestration job | `resources/job_orchestration_daily.yml` |
| DQ results / ops tables | `<cat>.ops.*` |
| Tests | `tests/` |
