# Commercial Data Platform — Data Contracts

> **Audience:** Data engineers (producers) and analytics engineers / analysts (consumers) of CDP datasets.
> **Scope:** What a data contract is, the CDP contract template, filled examples, refresh SLAs per domain, and the breaking-change policy.

**Related docs:**
- [`architecture.md`](./architecture.md) — how contracts are *enforced* via DLT expectations and the medallion model
- [`source-systems.md`](./source-systems.md) — source entity fields and sensitivity inventory
- [`naming-conventions.md`](./naming-conventions.md) — naming rules referenced by every contract

---

## 1. What Is a Data Contract?

A **data contract** is an explicit, versioned agreement between a dataset's **producer** (the pipeline/team that publishes it) and its **consumers** (dashboards, downstream pipelines, AI agents). It turns implicit assumptions ("the column is always there", "it refreshes by 6am") into a checked, documented commitment.

A contract covers four pillars:

| Pillar | Question it answers | Enforced by |
|---|---|---|
| **Schema** | What columns, types, nullability, keys? | DLT expectations, schema evolution policy |
| **Semantics** | What does each field mean? business keys? grain? | Documentation + steward review |
| **Quality** | What must be true of the data (ranges, uniqueness, referential integrity)? | DLT expectations, `ops` DQ metrics |
| **SLA / freshness** | How current is it, how often, by when? | Workflow schedule + freshness monitors |

**Why contracts matter in CDP:**
- The CRM↔ERP unification means many consumers depend on a handful of conformed datasets; an unannounced change breaks finance, BI, and agents simultaneously.
- Contracts let the platform **enforce quality in-pipeline** (DLT) rather than discovering breakage in a dashboard.
- They make ownership explicit (`cdp_data_engineers` produce; persona groups consume) and give stewards a control point for change.

Contracts in CDP are strongest at the **silver** and **gold** layers (the published, consumed surfaces). Bronze is governed by ingestion expectations but is not a public contract surface.

---

## 2. Contract Template

Every published dataset carries a contract with these fields:

```yaml
contract:
  dataset:            <catalog>.<schema>.<table>     # e.g. cdp_prod.gold.customer_360
  version:            <semver>                        # e.g. 2.1.0
  owner:              <UC group>                      # producing team, e.g. cdp_data_engineers
  steward:            <UC group>                      # accountable steward, e.g. cdp_data_stewards
  source:             <upstream datasets / systems>   # lineage parents
  grain:              <one row per ...>               # the unique business grain
  business_keys:      [<columns that uniquely identify a row>]
  sensitivity_default: <class>                        # table-level default sensitivity

  schema:
    - column:         <name>
      type:           <delta/iceberg type>
      nullable:       <true|false>
      sensitivity:    <public_reference|internal_only|pii|financial_sensitive|restricted_free_text>
      description:    <meaning>

  refresh:
    cadence:          <continuous|hourly|daily|...>
    sla:              <freshness target, e.g. "available by 06:00 ET">
    method:           <streaming | snapshot | snapshot+CDC | full refresh>

  quality_expectations:
    - name:           <expectation name>
      rule:           <SQL boolean>
      severity:       <fail|drop|warn>                # maps to expect_or_fail / expect_or_drop / expect

  breaking_change_policy:
    notice:           <lead time, e.g. "2 sprints">
    channel:          <where changes are announced>
    versioning:       <semver rules referenced in §5>
```

**Severity mapping to DLT:**

| Severity | DLT primitive | Effect |
|---|---|---|
| `fail` | `@dlt.expect_or_fail` | Violations stop the pipeline update |
| `drop` | `@dlt.expect_or_drop` | Violating rows are dropped + counted |
| `warn` | `@dlt.expect` | Rows kept; violation counted in `ops` metrics |

---

## 3. Filled Example Contracts

The examples below are written against `cdp_prod`; the same contracts apply in `cdp_dev`/`cdp_qa` with the env catalog swapped.

### 3.1 CRM Accounts — `cdp_prod.silver.crm_accounts`

```yaml
contract:
  dataset:            cdp_prod.silver.crm_accounts
  version:            1.3.0
  owner:              cdp_data_engineers
  steward:            cdp_data_stewards
  source:             cdp_prod.bronze.crm_accounts (Salesforce-like CRM, snapshot+diff)
  grain:              one row per current CRM account (SCD2 history in crm_accounts_hist)
  business_keys:      [account_id]
  sensitivity_default: internal_only

  schema:
    - {column: account_sk,        type: BIGINT,    nullable: false, sensitivity: internal_only,      description: surrogate key}
    - {column: account_id,        type: STRING,    nullable: false, sensitivity: internal_only,      description: CRM natural key}
    - {column: account_name,      type: STRING,    nullable: false, sensitivity: internal_only,      description: company name}
    - {column: industry,          type: STRING,    nullable: true,  sensitivity: internal_only,      description: industry classification}
    - {column: billing_address,   type: STRING,    nullable: true,  sensitivity: pii,                description: billing address}
    - {column: tax_id,            type: STRING,    nullable: true,  sensitivity: financial_sensitive, description: tax identifier}
    - {column: duns_number,       type: STRING,    nullable: true,  sensitivity: financial_sensitive, description: DUNS}
    - {column: owner_user_id,     type: STRING,    nullable: true,  sensitivity: internal_only,      description: owning rep}
    - {column: territory_id,      type: STRING,    nullable: true,  sensitivity: internal_only,      description: territory}
    - {column: parent_account_id, type: STRING,    nullable: true,  sensitivity: internal_only,      description: parent for hierarchy}
    - {column: master_customer_id,type: BIGINT,    nullable: true,  sensitivity: internal_only,      description: resolved cross-system id}
    - {column: _ingested_at,      type: TIMESTAMP, nullable: false, sensitivity: internal_only,      description: bronze ingest time}

  refresh:
    cadence:  daily
    sla:      "available by 06:00 ET"
    method:   snapshot+diff

  quality_expectations:
    - {name: pk_not_null,    rule: "account_id IS NOT NULL",                         severity: drop}
    - {name: pk_unique,      rule: "COUNT(*) = COUNT(DISTINCT account_id)",          severity: fail}
    - {name: name_present,   rule: "account_name IS NOT NULL",                       severity: drop}
    - {name: parent_valid,   rule: "parent_account_id IS NULL OR parent_account_id <> account_id", severity: warn}

  breaking_change_policy: {notice: "2 sprints", channel: "#cdp-data-contracts", versioning: "semver per §5"}
```

### 3.2 CRM Opportunities — `cdp_prod.silver.crm_opportunities`

```yaml
contract:
  dataset:            cdp_prod.silver.crm_opportunities
  version:            2.0.1
  owner:              cdp_data_engineers
  steward:            cdp_data_stewards
  source:             cdp_prod.bronze.crm_opportunities (CRM, hourly CDC)
  grain:              one row per current opportunity (stage history in crm_opportunities_hist)
  business_keys:      [opportunity_id]
  sensitivity_default: internal_only

  schema:
    - {column: opportunity_sk,   type: BIGINT,    nullable: false, sensitivity: internal_only,       description: surrogate key}
    - {column: opportunity_id,   type: STRING,    nullable: false, sensitivity: internal_only,       description: CRM natural key}
    - {column: account_id,       type: STRING,    nullable: false, sensitivity: internal_only,       description: parent account}
    - {column: master_customer_id,type: BIGINT,   nullable: true,  sensitivity: internal_only,       description: resolved customer}
    - {column: stage_name,       type: STRING,    nullable: false, sensitivity: internal_only,       description: current stage}
    - {column: amount,           type: DECIMAL(18,2), nullable: true, sensitivity: financial_sensitive, description: deal amount (doc ccy)}
    - {column: amount_usd,       type: DECIMAL(18,2), nullable: true, sensitivity: financial_sensitive, description: deal amount (reporting ccy)}
    - {column: currency_code,    type: STRING,    nullable: false, sensitivity: internal_only,       description: document currency}
    - {column: close_date,       type: DATE,      nullable: true,  sensitivity: internal_only,       description: expected/actual close}
    - {column: forecast_category,type: STRING,    nullable: true,  sensitivity: internal_only,       description: forecast bucket}
    - {column: is_closed,        type: BOOLEAN,   nullable: false, sensitivity: internal_only,       description: terminal flag}
    - {column: is_won,           type: BOOLEAN,   nullable: false, sensitivity: internal_only,       description: won flag}
    - {column: _ingested_at,     type: TIMESTAMP, nullable: false, sensitivity: internal_only,       description: ingest time}

  refresh:
    cadence:  hourly
    sla:      "lag <= 90 minutes from source CDC"
    method:   streaming (CDC via APPLY CHANGES)

  quality_expectations:
    - {name: pk_not_null,       rule: "opportunity_id IS NOT NULL",                          severity: drop}
    - {name: pk_unique,         rule: "COUNT(*) = COUNT(DISTINCT opportunity_id)",           severity: fail}
    - {name: account_fk,        rule: "account_id IS NOT NULL",                              severity: drop}
    - {name: amount_nonneg,     rule: "amount IS NULL OR amount >= 0",                       severity: drop}
    - {name: won_implies_closed,rule: "is_won = false OR is_closed = true",                  severity: fail}
    - {name: known_currency,    rule: "currency_code IN (SELECT DISTINCT from_currency FROM silver.currency_rates)", severity: warn}
```

### 3.3 ERP Invoices — `cdp_prod.silver.erp_invoices`

```yaml
contract:
  dataset:            cdp_prod.silver.erp_invoices
  version:            1.2.0
  owner:              cdp_data_engineers
  steward:            cdp_data_stewards
  source:             cdp_prod.bronze.erp_invoices (ERP, daily snapshot + CDC)
  grain:              one row per invoice
  business_keys:      [invoice_id]
  sensitivity_default: financial_sensitive

  schema:
    - {column: invoice_sk,      type: BIGINT,        nullable: false, sensitivity: internal_only,        description: surrogate key}
    - {column: invoice_id,      type: STRING,        nullable: false, sensitivity: internal_only,        description: ERP natural key}
    - {column: billing_doc_id,  type: STRING,        nullable: false, sensitivity: internal_only,        description: billing doc fk}
    - {column: customer_id,     type: STRING,        nullable: false, sensitivity: internal_only,        description: ERP customer}
    - {column: master_customer_id,type: BIGINT,      nullable: true,  sensitivity: internal_only,        description: resolved customer}
    - {column: invoice_date,    type: DATE,          nullable: false, sensitivity: internal_only,        description: invoice posting date}
    - {column: due_date,        type: DATE,          nullable: true,  sensitivity: internal_only,        description: payment due date}
    - {column: invoice_amount,  type: DECIMAL(18,2), nullable: false, sensitivity: financial_sensitive,  description: amount (doc ccy)}
    - {column: invoice_amount_usd,type: DECIMAL(18,2),nullable: true, sensitivity: financial_sensitive,  description: amount (reporting ccy)}
    - {column: currency_code,   type: STRING,        nullable: false, sensitivity: internal_only,        description: document currency}
    - {column: payment_status,  type: STRING,        nullable: false, sensitivity: financial_sensitive,  description: open/partial/paid/disputed}
    - {column: _ingested_at,    type: TIMESTAMP,     nullable: false, sensitivity: internal_only,        description: ingest time}

  refresh:
    cadence:  daily
    sla:      "available by 07:00 ET after ERP close batch"
    method:   snapshot+CDC (APPLY CHANGES)

  quality_expectations:
    - {name: pk_not_null,     rule: "invoice_id IS NOT NULL",                               severity: drop}
    - {name: pk_unique,       rule: "COUNT(*) = COUNT(DISTINCT invoice_id)",                severity: fail}
    - {name: customer_fk,     rule: "customer_id IS NOT NULL",                              severity: drop}
    - {name: amount_positive, rule: "invoice_amount >= 0",                                  severity: drop}
    - {name: due_after_inv,   rule: "due_date IS NULL OR due_date >= invoice_date",         severity: warn}
    - {name: status_domain,   rule: "payment_status IN ('open','partial','paid','disputed')", severity: fail}
```

### 3.4 ERP Payments — `cdp_prod.silver.erp_payments`

```yaml
contract:
  dataset:            cdp_prod.silver.erp_payments
  version:            1.1.0
  owner:              cdp_data_engineers
  steward:            cdp_data_stewards
  source:             cdp_prod.bronze.erp_payments (ERP, CDC)
  grain:              one row per payment / clearing event (multiple per invoice)
  business_keys:      [payment_id]
  sensitivity_default: financial_sensitive

  schema:
    - {column: payment_sk,    type: BIGINT,        nullable: false, sensitivity: internal_only,        description: surrogate key}
    - {column: payment_id,    type: STRING,        nullable: false, sensitivity: internal_only,        description: ERP natural key}
    - {column: invoice_id,    type: STRING,        nullable: false, sensitivity: internal_only,        description: invoice fk}
    - {column: payment_date,  type: DATE,          nullable: false, sensitivity: internal_only,        description: clearing date}
    - {column: amount_paid,   type: DECIMAL(18,2), nullable: false, sensitivity: financial_sensitive,  description: amount (doc ccy)}
    - {column: amount_paid_usd,type: DECIMAL(18,2),nullable: true,  sensitivity: financial_sensitive,  description: amount (reporting ccy)}
    - {column: currency_code, type: STRING,        nullable: false, sensitivity: internal_only,        description: document currency}
    - {column: payment_method,type: STRING,        nullable: true,  sensitivity: internal_only,        description: method}
    - {column: is_disputed,   type: BOOLEAN,       nullable: false, sensitivity: financial_sensitive,  description: dispute flag}
    - {column: _ingested_at,  type: TIMESTAMP,     nullable: false, sensitivity: internal_only,        description: ingest time}

  refresh:
    cadence:  daily
    sla:      "available by 07:30 ET (after erp_invoices)"
    method:   CDC (APPLY CHANGES)

  quality_expectations:
    - {name: pk_not_null,     rule: "payment_id IS NOT NULL",                              severity: drop}
    - {name: pk_unique,       rule: "COUNT(*) = COUNT(DISTINCT payment_id)",               severity: fail}
    - {name: invoice_fk,      rule: "invoice_id IS NOT NULL",                              severity: drop}
    - {name: amount_positive, rule: "amount_paid > 0",                                     severity: drop}
    - {name: ref_integrity,   rule: "invoice_id IN (SELECT invoice_id FROM silver.erp_invoices)", severity: warn}
```

> Note: `ref_integrity` is `warn` (not `fail`) because late-arriving CDC can deliver a payment before its invoice within the same batch window; the steward reviews persistent orphans via `ops` metrics.

---

## 4. Refresh SLA by Domain

| Domain | Entities | Method | Cadence | SLA target |
|---|---|---|---|---|
| **CRM — high velocity** | opportunities, activities, cases | CDC streaming (APPLY CHANGES) | hourly | lag ≤ 90 min from source |
| **CRM — standard** | accounts, contacts, leads, quotes, contracts, users, territories | snapshot+diff | daily | available by 06:00 ET |
| **ERP — transactional** | sales_orders, sales_order_items, billing_documents, invoices, payments, gl_entries | snapshot + CDC | daily | available by 07:30 ET after ERP close batch |
| **ERP — master/org** | customers, vendors, products, cost_centers, profit_centers | daily full snapshot (SCD2) | daily | available by 06:30 ET |
| **Reference** | currency_rates, fiscal calendar, product hierarchy | snapshot | daily | available by 06:00 ET |
| **Gold products** | customer_360, revenue_pipeline, bookings_vs_billings, collections_risk, support_performance, account_health, renewal_risk | full/incremental materialization | daily (pipeline subsets hourly) | available by 08:00 ET |

Freshness is monitored in the `ops` schema; breaches alert the owning group.

---

## 5. Breaking vs. Non-Breaking Change Policy

Contracts are versioned with **semver** (`MAJOR.MINOR.PATCH`). The change class determines the version bump and the required process.

| Change class | Examples | Semver bump | Process |
|---|---|---|---|
| **Non-breaking (additive)** | Add a nullable column; add a new value to a non-enforced field; loosen a `warn` expectation; performance change | `MINOR` (new column) / `PATCH` (doc/expectation tweak) | Announce in change channel; deploy via bundle to dev→qa→prod; no consumer action required |
| **Breaking** | Remove/rename a column; change a column type; tighten nullability (nullable→not null); narrow an enforced domain; change grain or business keys; change semantics of an existing column | `MAJOR` | Required notice (≥ 2 sprints), steward sign-off, consumer migration plan, parallel-run of old + new version where feasible |

**Breaking-change procedure:**
1. Open a change proposal referencing the contract `dataset` and `version`.
2. Notify consumers via the change channel with the migration window.
3. Steward (`cdp_data_stewards`) reviews and approves.
4. Where feasible, publish the new version alongside the old (e.g., a versioned view) and run in parallel.
5. Deprecate the old version after consumers migrate; remove on the announced date.

**Schema evolution alignment:** Additive source changes flow safely through Auto Loader (`addNewColumns`) and DLT without breaking contracts. Any source change that would force a *breaking* downstream change must go through the procedure above before it reaches silver/gold.
