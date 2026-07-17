# Commercial Data Platform — Architecture

> **Audience:** Platform engineers, data engineers, analytics engineers, and architects working on the Commercial Data Platform (CDP).
> **Scope:** End-to-end technical architecture of the medallion lakehouse that unifies the CRM and ERP systems on Azure Databricks.

**Related docs:**
- [`source-systems.md`](./source-systems.md) — detailed CRM/ERP source models, entities, and the identity problem
- [`data-contracts.md`](./data-contracts.md) — producer/consumer contracts, schemas, SLAs, change policy
- [`naming-conventions.md`](./naming-conventions.md) — catalog/schema/table/column/job naming rules

---

## 1. Executive Summary

The **Commercial Data Platform (CDP)** is the enterprise lakehouse for an IT sales & services company. The business sells software licenses, subscriptions, hardware, and professional/managed services to commercial accounts. Two operational systems run the business:

- A **Salesforce-like CRM** that owns the *front office*: leads, opportunities, quotes, contracts, accounts, contacts, support cases, and sales activity.
- An **SAP-like ERP** that owns the *back office*: customer master, sales orders, billing, invoices, payments, the general ledger, and organizational/financial master data.

These systems answer different questions and rarely agree on identifiers, granularity, or timing. CDP unifies them into a governed **medallion lakehouse** on **Unity Catalog (UC)**, producing a curated set of **gold data products** that power BI, finance close, customer success, and AI/agent workloads.

**Core outcomes:**

| Outcome | How CDP delivers it |
|---|---|
| Single source of truth for "who is the customer" | Identity resolution joining CRM `accounts` ↔ ERP `customers` into a conformed customer dimension |
| Pipeline vs. revenue reconciliation | `bookings_vs_billings` aligns CRM closed-won bookings to ERP billings/invoices |
| Governed, lineage-tracked data | Unity Catalog RBAC, tags, volumes, and lineage system tables across all layers |
| Reliable, declarative pipelines | Lakeflow Spark Declarative Pipelines (DLT) with built-in expectations and dependency graphs |
| Open, interoperable gold | Delta everywhere + **Managed Iceberg (UC)** for select externally-consumed gold products |
| Reproducible delivery | Databricks Asset Bundles (DABs) for CI/CD across `cdp_dev` → `cdp_qa` → `cdp_prod` |

**Workspace:** `https://<your-workspace>.azuredatabricks.net` (Azure Databricks)
**Catalogs (one per environment):** `cdp_dev`, `cdp_qa`, `cdp_prod`
**Schemas per catalog:** `landing`, `bronze`, `silver`, `gold`, `ops`, `sandbox` (sandbox in **dev only**)

---

## 2. Business Context

The company is **Rheinhardt Industrial** — a mid-to-large **B2B industrial-equipment
manufacturer** (pumps, valves, motors, compressors + aftermarket parts) selling to
distributors and direct OEM/end-user customers, with a field-service and spare-parts
arm. Product divisions: **Flow** (pumps, valves) · **Power** (motors, compressors) ·
**Care** (filters, lubricants, spare parts) · **Services**. See
[`business-domain-and-systems.md`](./business-domain-and-systems.md). Its commercial
lifecycle spans both systems:

```
   Marketing/SDR        Sales            Deal Desk         Fulfillment        Finance           Success
   ───────────    ───────────────   ──────────────   ──────────────   ──────────────   ──────────────
   Lead     ─►    Opportunity   ─►   Quote/Contract ─►  Sales Order   ─►  Invoice    ─►   Renewal / Case
   (CRM)          (CRM)              (CRM)              (ERP)             (ERP)            (CRM)
```

The **handoff between CRM and ERP** is the central analytical challenge: a *closed-won opportunity* in CRM must reconcile against a *sales order → billing document → invoice → payment* chain in ERP, even though the two systems use different keys, currencies, timing, and granularity. CDP exists to make that reconciliation trustworthy and queryable.

---

## 3. End-to-End Data Flow

Data flows strictly left-to-right through the medallion layers. Each arrow is an incremental, checkpointed, and lineage-tracked transition.

```
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                      SOURCES (synthetic gen)                                       │
  │   CRM (Salesforce-like): accounts, contacts, leads, opportunities, ...                             │
  │   ERP (SAP-like):        customers, sales_orders, invoices, payments, gl_entries, ...              │
  └───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                               │  files (JSON / CSV / Parquet), CDC + snapshots
                                               ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  LANDING  (UC Volume:  cdp_<env>.landing.<volume>/<domain>/<entity>/<date>/...)                    │
  │  Raw, immutable files exactly as produced. No parsing. Lifecycle-managed.                          │
  └───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                               │  Auto Loader  (cloudFiles) — incremental, exactly-once
                                               ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  BRONZE  (Delta:  cdp_<env>.bronze.crm_accounts, erp_invoices, ...)                                │
  │  As-ingested, append-mostly. Schema inferred + evolved. Audit cols added. Quarantine on bad rows.  │
  └───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                               │  Lakeflow Spark Declarative Pipelines (DLT) + expectations
                                               ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  SILVER  (Delta:  cdp_<env>.silver.crm_accounts, erp_invoices, dim_customer, ...)                  │
  │  Cleaned, typed, deduplicated, conformed. SCD where needed. Identity resolution. Business keys.    │
  └───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                               │  Lakeflow DLT (joins, aggregates, semantic modeling)
                                               ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  GOLD  (Delta + selective Managed Iceberg:  cdp_<env>.gold.customer_360, revenue_pipeline, ...)    │
  │  Business-ready, denormalized data products. Star schemas / wide tables. SLA-backed contracts.     │
  └───────────────────────────────────────────┬──────────────────────────────────────────────────────┘
                                               ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  CONSUMPTION                                                                                        │
  │   • Databricks SQL / BI dashboards   • AI/BI Genie & agents (cdp_ai_app_users)                     │
  │   • External engines via Iceberg REST catalog   • Reverse ETL / operational sync                   │
  └──────────────────────────────────────────────────────────────────────────────────────────────────┘

  ── Cross-cutting (all layers) ──────────────────────────────────────────────────────────────────────
   Unity Catalog: RBAC · tags/classification · volumes · lineage system tables (system.access.*)
   Orchestration: Databricks Workflows (job_*)   |   CI/CD: Databricks Asset Bundles
   Observability: ops schema (run logs, DQ metrics, expectation results, reconciliation)
```

**Synthetic generation note:** Because there is no live production tap, source data is produced by a synthetic generator that emulates real CRM/ERP behavior (lead conversion, stage progression, partial payments, finance-close adjustments, SCD changes). Generated files land in the UC **Volume** under `landing`, which is the contract boundary between "data production" and "the platform."

---

## 4. Medallion Layers

The medallion architecture progressively refines data quality and business readiness. Each layer has a distinct **purpose**, **contents**, and **guarantee**.

### 4.1 Layer responsibilities

| Layer | Purpose | Contents | What it guarantees |
|---|---|---|---|
| **landing** | Durable raw capture | Immutable source files in a UC Volume, partitioned by domain/entity/ingest date | Nothing is lost; replay is always possible from raw |
| **bronze** | Faithful as-ingested copy | Delta tables, one per source entity, append-mostly, with audit columns; bad records quarantined | Every source row is captured exactly once with provenance |
| **silver** | Clean, conformed, modeled | Typed/deduplicated Delta tables, SCD2 dimensions, conformed `dim_*`, business keys, identity resolution | Correctness: data is valid, deduplicated, and join-ready |
| **gold** | Business data products | Denormalized Delta/Iceberg tables aligned to consumer needs, SLA-backed | Fitness-for-use: contract-compliant, fast, semantically stable |

### 4.2 Examples by layer

| Layer | CRM example | ERP example | Conformed/derived example |
|---|---|---|---|
| bronze | `bronze.crm_opportunities` (raw stages, possible dupes) | `bronze.erp_invoices` (raw, mixed types) | — |
| silver | `silver.crm_opportunities` (typed, deduped, stage history) | `silver.erp_invoices` (typed, currency-normalized) | `silver.dim_customer` (resolved CRM↔ERP), `silver.dim_date` (fiscal calendar) |
| gold | — | — | `gold.customer_360`, `gold.revenue_pipeline`, `gold.bookings_vs_billings`, `gold.collections_risk`, `gold.support_performance`, `gold.account_health`, `gold.renewal_risk` |

### 4.3 Layer guarantees in detail

- **landing → bronze:** *Completeness & provenance.* Auto Loader guarantees exactly-once file processing. Bronze adds `_ingested_at`, `_source_file`, `_batch_id` so every row is traceable to a raw file.
- **bronze → silver:** *Correctness & conformance.* DLT expectations enforce types, non-null business keys, referential sanity, and dedup. Identity resolution and SCD logic live here. Rows failing hard expectations are dropped/quarantined; soft violations are flagged.
- **silver → gold:** *Fitness-for-use.* Gold tables are shaped to consumer questions (star schema or wide tables), carry contract guarantees (schema stability, SLA, freshness), and are the **only** layer most analysts and AI agents query.

---

## 5. Why Lakeflow Spark Declarative Pipelines (DLT)

CDP transforms (bronze → silver → gold) are authored as **Lakeflow Spark Declarative Pipelines** (the framework historically known as DLT). Instead of imperatively scheduling tasks, you *declare* the target tables and their queries; the engine derives the rest.

| Capability | What it gives CDP |
|---|---|
| **Declarative dependency graph** | You declare `silver.crm_opportunities` reads `bronze.crm_opportunities`; the engine builds the DAG, orders execution, and parallelizes safely. No manual orchestration of inter-table dependencies. |
| **Expectations (data quality)** | `@dlt.expect`, `expect_or_drop`, `expect_or_fail` enforce quality inline. Violations are measured, logged to the event log, and surfaced in `ops`. This is how data contracts are *enforced*, not just documented. |
| **Unified streaming + batch** | Streaming tables for continuous ingestion (CDC, hourly CRM) and materialized views for batch aggregates, in one framework. Switch a table from triggered to continuous without rewriting logic. |
| **Auto-managed materializations** | The engine decides incremental vs. full recompute, manages checkpoints, handles late-arriving data, and maintains streaming tables and materialized views automatically. |
| **Lineage & observability** | Pipeline lineage is captured automatically and joins UC lineage system tables; the event log feeds the `ops` schema for run/DQ monitoring. |
| **Idempotent recovery** | Failed runs resume from checkpoint; reruns are safe. |

**Example expectation (silver invoices):**

```python
import dlt

@dlt.table(name="erp_invoices", comment="Cleaned ERP invoices")
@dlt.expect_or_drop("valid_invoice_id", "invoice_id IS NOT NULL")
@dlt.expect_or_drop("valid_amount", "invoice_amount >= 0")
@dlt.expect("known_currency", "currency_code IN (SELECT currency_code FROM ref.currency_rates)")
def erp_invoices():
    return (
        dlt.read_stream("bronze.erp_invoices")
           .transform(cast_and_normalize)
    )
```

Hard rules (`expect_or_drop`/`expect_or_fail`) protect downstream correctness; soft rules (`expect`) generate metrics without dropping data, letting stewards triage.

---

## 6. Auto Loader — Incremental Ingestion

Auto Loader (`cloudFiles` source) is the engine for **landing → bronze**. It incrementally and efficiently processes new files as they land in the UC Volume.

```
   landing volume                Auto Loader (cloudFiles)              bronze Delta
   ┌──────────────┐    discovers new files only    ┌──────────────┐   ┌──────────────┐
   │ file_001.json│ ─────────────────────────────► │ schema infer │ ─►│ append rows  │
   │ file_002.json│      (notification or          │ + evolution  │   │ + audit cols │
   │ file_003.json│       directory listing)        │ + checkpoint │   │ exactly-once │
   └──────────────┘                                 └──────────────┘   └──────────────┘
                                                            │
                                                    _checkpoint (RocksDB) tracks
                                                    processed files + schema
```

| Concern | How Auto Loader handles it |
|---|---|
| **Incremental discovery** | Tracks which files it has seen in a durable checkpoint; only new files are processed. Scales to millions of files via file-notification mode. |
| **Schema inference** | Infers column types from sampled files on first run; persists the schema in the checkpoint's schema location. |
| **Schema evolution** | New columns appearing in source files are added automatically (`schemaEvolutionMode`); the stream restarts to pick up the new schema. Rescued data (`_rescued_data`) captures fields that don't match. |
| **Checkpointing** | The checkpoint (RocksDB-backed) records processed files and stream offsets, enabling resume-after-failure. |
| **Exactly-once** | Combined checkpoint + Delta transactional writes guarantee each file's rows are committed exactly once, even across retries. |
| **Bad data** | Malformed records are rescued or routed to quarantine rather than failing the whole batch. |

**Pattern used in CDP:**

```python
(spark.readStream
   .format("cloudFiles")
   .option("cloudFiles.format", "json")
   .option("cloudFiles.schemaLocation", "/Volumes/cdp_dev/landing/_schemas/crm_accounts")
   .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
   .option("rescuedDataColumn", "_rescued_data")
   .load("/Volumes/cdp_dev/landing/crm/accounts/")
   .selectExpr("*",
       "current_timestamp() AS _ingested_at",
       "_metadata.file_path  AS _source_file")
   .writeStream
   .option("checkpointLocation", "/Volumes/cdp_dev/ops/_checkpoints/bronze_crm_accounts")
   .toTable("cdp_dev.bronze.crm_accounts"))
```

---

## 7. Delta vs. Iceberg Strategy

CDP standardizes on **Delta Lake** for bronze and silver, and uses **Managed Iceberg in Unity Catalog** selectively for chosen gold products.

```
   bronze ───────────► silver ───────────► gold
   Delta               Delta               Delta (default)
                                              └──► Managed Iceberg (UC) for select external products
```

| Dimension | Delta Lake | Managed Iceberg (Unity Catalog) |
|---|---|---|
| **Where used** | bronze, silver, most gold | Select gold products consumed by external/heterogeneous engines |
| **Strengths** | Deepest Databricks integration: DLT, liquid clustering, predictive optimization, Change Data Feed, Photon | Open-table interoperability via the **Iceberg REST catalog**; read/write from external engines while UC governs |
| **Why for internal** | Best performance and lowest operational overhead inside Databricks; native to Lakeflow pipelines | — |
| **Why Iceberg for select gold** | — | External consumers (third-party query engines, partner platforms, certain BI tools) standardize on Iceberg; UC Managed Iceberg lets them read CDP gold **without copying** while keeping UC RBAC, lineage, and tags |
| **Governance** | Unity Catalog | Unity Catalog (same RBAC, tags, lineage) |
| **Interoperability** | Delta UniForm can expose Delta tables as Iceberg metadata when needed | Native Iceberg + REST catalog endpoint |

**Decision rule:**
- Default to **Delta** for everything.
- Promote a **gold** product to **Managed Iceberg** only when it has a confirmed **external, non-Databricks consumer** that requires native Iceberg. Examples: a partner analytics platform reading `revenue_pipeline`, or a finance tool consuming `bookings_vs_billings`.
- Where a Delta gold table occasionally needs Iceberg readers, enable **UniForm** rather than converting the table — this avoids fragmenting the storage strategy.

Both formats live under the same UC catalogs/schemas, so governance, lineage, and discovery are uniform regardless of format.

---

## 8. Master Data & Identity Resolution (CRM ↔ ERP)

The single most important modeling problem in CDP: a customer exists **twice** — as a CRM `account` (front office) and an ERP `customer` (back office) — with **no shared key**.

```
   CRM.accounts                         ERP.customers
   ┌────────────────────┐               ┌────────────────────┐
   │ account_id (CRM PK)│               │ customer_id (ERP PK)│
   │ account_name       │   ??? join    │ customer_name       │
   │ billing_address    │ ◄───────────► │ address             │
   │ tax_id / DUNS      │               │ tax_id / DUNS       │
   │ website / domain   │               │ vat_reg_no          │
   └────────────────────┘               └────────────────────┘
                  │                                   │
                  └──────────► dim_customer ◄─────────┘
                               (conformed, with both source keys + master_customer_id)
```

**Why it matters:** Without resolution you cannot connect *pipeline/bookings* (CRM) to *billings/invoices/payments* (ERP). Every cross-domain gold product (`customer_360`, `bookings_vs_billings`, `collections_risk`, `account_health`, `renewal_risk`) depends on it.

**Approach (in silver):**

1. **Deterministic matching first** — exact/normalized matches on strong identifiers: tax ID, DUNS/registration number, VAT number, normalized legal name + country.
2. **Probabilistic/fuzzy matching** — for the remainder, score candidate pairs on normalized name similarity, address, domain/website, and email domain; apply thresholds.
3. **Survivorship & golden record** — assign a stable `master_customer_id` (surrogate key), choose surviving attribute values by source-of-truth rules (e.g., ERP wins on legal/tax fields, CRM wins on commercial/contact fields).
4. **Crosswalk table** — `silver.xref_customer` maps `(source_system, source_key) → master_customer_id`, persisted and versioned so resolution decisions are auditable.
5. **Steward override** — `cdp_data_stewards` can confirm/split/merge matches; overrides are stored and always win over automated scores.

The output is `silver.dim_customer`, the conformed customer dimension carrying both `account_id` and `customer_id` plus `master_customer_id`. All gold customer references use `master_customer_id`.

---

## 9. Reference Data

Reference data is small, slowly-changing, and shared across domains. It is conformed in silver (commonly a `ref` namespace within silver) and treated as `public_reference` or `internal_only`.

| Reference set | Purpose | Notes |
|---|---|---|
| **Fiscal calendar** (`dim_date`) | Maps calendar dates to fiscal year/quarter/period; the company's fiscal year may not be calendar-aligned | Drives all time-based gold (pipeline by quarter, bookings by period, finance close) |
| **Product hierarchy** | Rolls SKUs up to product families/lines/business units | Conforms CRM `opportunity_line_items` products with ERP `products`; SCD2 to preserve historical hierarchy |
| **Currency rates** (`currency_rates`) | Daily FX rates for normalizing multi-currency amounts to reporting currency | Sourced from ERP; both transaction-date and period-close rates retained |
| **Org dimensions** | Cost centers, profit centers, territories | Link ERP financial postings and CRM ownership to org structure |

**Currency handling principle:** amounts are kept in **document currency** plus a normalized **reporting currency** (converted using the appropriate rate — transaction-date for operational metrics, period-close for finance reconciliation). Never silently overwrite original-currency values.

---

## 10. Non-Functional Concerns

### 10.1 Backfill & replay
- **Raw is durable.** Because landing keeps immutable source files, any layer can be rebuilt by reprocessing from landing. Bronze can be fully replayed by resetting Auto Loader checkpoints against retained files.
- **DLT full refresh** rebuilds silver/gold deterministically from upstream.
- **Time-tested ordering:** late-arriving CDC is handled by `APPLY CHANGES` (SCD) logic in silver; backfills don't corrupt SCD history because effective-dating is key-based.

### 10.2 Cost & performance governance
- **Predictive optimization & liquid clustering** on Delta tables remove manual `OPTIMIZE`/`ZORDER` tuning.
- **Photon** + serverless compute for SQL/pipelines.
- **Workload isolation per env** via separate catalogs and compute policies; `sandbox` (dev only) isolates ad-hoc experimentation from governed schemas.
- **System tables** (billing/usage) drive cost attribution by domain/job.

### 10.3 Disaster recovery
- Data resides in cloud object storage (ADLS Gen2) with versioning and cross-region replication per the org DR tier.
- **UC metadata** and pipeline definitions are reproducible from **Databricks Asset Bundles** in git, so a workspace can be re-provisioned and re-pointed at replicated storage.
- **RPO/RTO** are bounded by storage replication lag and the time to redeploy bundles + restart pipelines; because pipelines are declarative and idempotent, recovery is a redeploy + rerun rather than a manual rebuild.

### 10.4 Governance & lineage (cross-cutting)
- Unity Catalog provides RBAC (group-based via personas), tags/classification, volumes, and **lineage system tables** (`system.access.table_lineage`, `system.access.column_lineage`) for column-level lineage across all layers.
- The `ops` schema centralizes run logs, expectation results, DQ metrics, and reconciliation outputs for monitoring and alerting.

---

## 11. Cross-References

- Source entity details, lifecycle behaviors, and PII inventory → [`source-systems.md`](./source-systems.md)
- Contract templates, filled examples, SLAs, and change policy → [`data-contracts.md`](./data-contracts.md)
- Catalog/schema/table/column/job naming rules → [`naming-conventions.md`](./naming-conventions.md)
