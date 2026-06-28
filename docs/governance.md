# Governance — Unity Catalog, Sensitivity & Access Control

> **Program:** Commercial Data Platform (CDP) — a Salesforce-like CRM + SAP-like ERP
> feeding a medallion lakehouse.
> **Workspace:** `https://adb-7405618019865738.18.azuredatabricks.net` (Azure Databricks)
> **Governance engine:** Unity Catalog (UC).
>
> This document describes **how the platform is governed**: the object model, the
> sensitivity model, who can touch what (RBAC), how PII is masked and filtered,
> how AI agents consume data safely, and how we audit and trace everything via
> system tables.

---

## 1. Why governance-first

CDP carries customer PII, financial data, and free-text human commentary
(case notes, opportunity notes). A breach or an over-permissioned analyst is an
existential risk, not a bug. Therefore the platform is **governance-first**:

1. **Nothing is readable by default.** UC denies all access unless a `GRANT`
   exists. New tables are invisible to everyone except the owner/admin until a
   grant is written in `governance/grants.sql`.
2. **Sensitivity is declared, not assumed.** Every column belongs to one of five
   sensitivity classes (Section 4) and is tagged accordingly.
3. **Protection moves with the data through the medallion.** Raw PII is locked
   down in bronze, progressively de-risked in silver, and masked/tokenized
   before it reaches gold and AI consumers.
4. **Humans and agents read governed surfaces, not raw tables.** Analysts and AI
   apps query gold products and approved views — never `bronze.*`.
5. **Everything is observable.** Lineage and audit come "for free" from UC system
   tables; we query them for impact analysis and forensics.

---

## 2. The Unity Catalog object model

Unity Catalog is the single governance layer across all workspaces in the
account. Its object hierarchy:

```
 Account
   └── Metastore                    (one per region; attached to the workspace)
        ├── Catalog                 cdp_dev | cdp_qa | cdp_prod
        │     ├── Schema (database) landing | bronze | silver | gold | ops | sandbox
        │     │     ├── Table       managed Delta / managed Iceberg
        │     │     ├── View        governed read surfaces for analysts + agents
        │     │     ├── Volume      UC-governed files (landing dir, exports)
        │     │     ├── Function    SQL UDFs, masking functions, row filters
        │     │     └── Model       (MLflow / UC-registered models)
        │     └── ...
        ├── Storage Credential      Access Connector (managed identity) UC assumes to reach ADLS Gen2
        ├── External Location       ADLS Gen2 (abfss://) path + credential (governs volumes/ext tables)
        └── Share / Recipient       (Delta Sharing, if/when used externally)
```

**Securable objects** (catalog, schema, table, view, volume, function, model,
external location, …) each carry their own ACL. Privileges **inherit downward**:
a grant on a catalog applies to all current and future schemas/tables within it,
unless overridden at a lower level.

### The three-level namespace

Every table, view, volume, and function is addressed as:

```
catalog . schema . object
└──┬──┘   └──┬──┘   └──┬─┘
  env      layer    entity

  cdp_prod . silver . customer
  cdp_prod . gold   . customer_360
  cdp_dev  . landing . files          (a volume)
```

Because the **catalog encodes the environment** (Section: [environments.md](./environments.md))
and the **schema encodes the medallion layer**, the fully-qualified name tells
you both *where* (dev/qa/prod) and *what stage* (raw → curated → product) a
dataset is in. The same code, parameterized by `${var.catalog}`, runs against all
three catalogs.

| Level | Securable | CDP usage |
|-------|-----------|-----------|
| 1 | **Catalog** | Environment boundary: `cdp_dev`, `cdp_qa`, `cdp_prod` |
| 2 | **Schema** | Medallion layer: `landing`, `bronze`, `silver`, `gold`, `ops`, `sandbox` (dev only) |
| 3 | **Object** | Table / view / volume / function / model |

> **Implemented by:** `governance/catalogs_schemas.sql` — creates the three
> catalogs and the per-layer schemas, attaches comments/owners, and creates the
> `landing` volumes.

---

## 3. Schemas (medallion layers) and their storage formats

| Schema | Purpose | Format | Who writes | Who reads |
|--------|---------|--------|------------|-----------|
| `landing` | Raw files as delivered by Lakeflow Connect / file drops (volumes) | Files in UC Volume | Ingestion jobs | Data engineers only |
| `bronze` | Raw, append-only, schema-on-read ingest of CRM/ERP tables | **Delta** | Auto Loader / DLT | Data engineers only |
| `silver` | Cleaned, conformed, deduped, typed business entities | **Delta** | Lakeflow/DLT | Data + analytics engineers |
| `gold` | Curated, consumption-ready data products | **Delta** + selective **Managed Iceberg (UC)** | Analytics engineers | Analysts, agents (via views) |
| `ops` | Operational metadata: run logs, DQ results, freshness, SLAs | Delta | Pipelines / observability jobs | Platform engineers, stewards |
| `sandbox` | Free-form experimentation (**dev catalog only**) | Delta | Any engineer | Author |

> **Why Iceberg in gold?** Selected gold products are published as **UC-managed
> Apache Iceberg** tables so external engines (Snowflake, Trino, BigQuery, Athena
> via the Iceberg REST catalog) can read them with the *same* UC permissions and
> masking. Bronze/silver stay Delta for performance, `MERGE`, CDF, and DLT.

---

## 4. The sensitivity model — 5 classes × medallion handling

Every column is classified into exactly one of **five sensitivity classes**.
The class drives *handling rules* that tighten or loosen per layer.

| Class | Meaning | Examples |
|-------|---------|----------|
| `public_reference` | Non-sensitive reference / lookup data | country codes, product catalog, currency |
| `internal_only` | Business data, no personal/financial sensitivity | opportunity stage, account industry, region |
| `pii` | Personally identifiable information | email, phone, name, address |
| `financial_sensitive` | Money + identifiers with regulatory weight | tax id (EIN/VAT), bank account, ARR by named account, invoice amounts |
| `restricted_free_text` | Unstructured human text that may hide PII/financials | case comments, opportunity notes, support transcripts |

### Handling rules per medallion layer

```
            ┌──────────┬──────────────┬──────────────┬──────────────────────┐
            │  BRONZE  │    SILVER    │     GOLD     │   AI / AGENT ACCESS  │
┌───────────┼──────────┼──────────────┼──────────────┼──────────────────────┤
│ public_   │  open    │   open       │   open       │  direct view OK      │
│ reference │          │              │              │                      │
├───────────┼──────────┼──────────────┼──────────────┼──────────────────────┤
│ internal_ │ eng only │ eng + AE     │ analysts     │  governed view       │
│ only      │          │              │              │                      │
├───────────┼──────────┼──────────────┼──────────────┼──────────────────────┤
│ pii       │ RAW,     │ PROTECTED    │ MASKED /     │ approved masked      │
│           │ locked   │ (limited     │ TOKENIZED    │ view ONLY — never    │
│           │ to eng + │  groups,     │ (column-mask │ raw PII              │
│           │ stewards │  masked)     │  functions)  │                      │
├───────────┼──────────┼──────────────┼──────────────┼──────────────────────┤
│ financial_│ RAW,     │ PROTECTED    │ MASKED +     │ aggregate / masked   │
│ sensitive │ locked   │ (finance     │ ROW-FILTERED │ view ONLY            │
│           │          │  stewards)   │ by persona   │                      │
├───────────┼──────────┼──────────────┼──────────────┼──────────────────────┤
│ restricted│ RAW,     │ NOT promoted │ redacted /   │ redacted view ONLY;  │
│ free_text │ locked   │ unmasked;    │ summarized   │ no raw free text to  │
│           │ to eng + │ PII-scrubbed │ only         │ agents (Section 11)  │
│           │ stewards │ copy only    │              │                      │
└───────────┴──────────┴──────────────┴──────────────┴──────────────────────┘
```

Plain-English summary:

- **Bronze** holds raw PII and is **locked to `cdp_data_engineers` and
  `cdp_data_stewards` only**. No analyst, no agent ever touches bronze.
- **Silver** holds *protected* PII: real values exist but are visible only to
  limited steward groups; masking functions hide them from everyone else.
- **Gold** exposes only **masked or tokenized** PII and **row-filtered**
  financials. This is the analyst surface.
- **Agents** (`cdp_ai_app_users`) read **only approved governed views** built on
  gold — never base tables, never raw PII, never raw free text.

---

## 5. RBAC by persona — the GRANT matrix

Eight Unity Catalog groups (personas) map to privilege sets. The matrix below is
the source of truth for `governance/grants.sql`. Privileges shown are the *net*
effective grant per catalog/schema. (`USE CATALOG`/`USE SCHEMA` are implied
wherever any `SELECT`/`MODIFY` is granted.)

Legend: **S** = `SELECT`, **M** = `MODIFY` (insert/update/delete/merge),
**C** = `CREATE` (table/view/function), **U** = `USE` only, **–** = no access,
**EXEC** = `EXECUTE` (functions).

| Group \ Schema | `landing` | `bronze` | `silver` | `gold` | `ops` | `sandbox` (dev) |
|---|---|---|---|---|---|---|
| `cdp_platform_engineers` | C/M/S | C/M/S | C/M/S | C/M/S | C/M/S | C/M/S |
| `cdp_data_engineers` | C/M/S | C/M/S | C/M/S | S | M/S | C/M/S |
| `cdp_analytics_engineers` | – | – | S | C/M/S | S | C/M/S |
| `cdp_data_stewards` | S | S | S | S | C/M/S | – |
| `cdp_sales_analysts` | – | – | – | S (via views, row-filtered) | – | – |
| `cdp_finance_analysts` | – | – | – | S (financial views) | S (freshness) | – |
| `cdp_customer_success` | – | – | – | S (support/account views) | – | – |
| `cdp_ai_app_users` | – | – | – | **EXEC/S on approved views only** | – | – |

Notes on the matrix:

- **Bronze is a vault.** Only platform + data engineers (write) and data
  stewards (read) ever see it. This is where raw PII lives.
- **Analysts never see base tables.** `cdp_sales_analysts`,
  `cdp_finance_analysts`, and `cdp_customer_success` are granted `SELECT` on the
  **gold views**, which carry row filters and column masks, not on the gold base
  tables. (UC requires the *view owner* to have access to the underlying tables;
  the analyst only needs `SELECT` on the view.)
- **Agents are the most restricted.** `cdp_ai_app_users` can `EXECUTE` retrieval
  functions / `SELECT` only the explicitly approved governed views.
- **`sandbox` exists only in `cdp_dev`.** No sandbox schema is created in qa/prod.

### Example grants (`governance/grants.sql`)

```sql
-- Catalog visibility (needed before any schema/table grant resolves).
GRANT USE CATALOG ON CATALOG cdp_prod TO `cdp_sales_analysts`;
GRANT USE CATALOG ON CATALOG cdp_prod TO `cdp_finance_analysts`;
GRANT USE CATALOG ON CATALOG cdp_prod TO `cdp_ai_app_users`;

-- Data engineers own bronze + silver write paths.
GRANT CREATE, MODIFY, SELECT ON SCHEMA cdp_prod.bronze TO `cdp_data_engineers`;
GRANT CREATE, MODIFY, SELECT ON SCHEMA cdp_prod.silver TO `cdp_data_engineers`;

-- Bronze is locked: only engineers + stewards.
GRANT SELECT ON SCHEMA cdp_prod.bronze TO `cdp_data_stewards`;

-- Analytics engineers build gold.
GRANT SELECT ON SCHEMA cdp_prod.silver               TO `cdp_analytics_engineers`;
GRANT CREATE, MODIFY, SELECT ON SCHEMA cdp_prod.gold TO `cdp_analytics_engineers`;

-- Analysts get gold VIEWS only (row-filtered / masked surfaces).
GRANT SELECT ON VIEW cdp_prod.gold.v_revenue_pipeline      TO `cdp_sales_analysts`;
GRANT SELECT ON VIEW cdp_prod.gold.v_bookings_vs_billings  TO `cdp_finance_analysts`;
GRANT SELECT ON VIEW cdp_prod.gold.v_collections_risk      TO `cdp_finance_analysts`;
GRANT SELECT ON VIEW cdp_prod.gold.v_support_performance   TO `cdp_customer_success`;
GRANT SELECT ON VIEW cdp_prod.gold.v_account_health        TO `cdp_customer_success`;

-- AI agents: approved views + retrieval function ONLY.
GRANT SELECT  ON VIEW cdp_prod.gold.v_customer_360_agent  TO `cdp_ai_app_users`;
GRANT EXECUTE ON FUNCTION cdp_prod.gold.f_account_lookup  TO `cdp_ai_app_users`;
```

> **Best practice:** grant to **groups, never individuals**; assign people to
> groups in the account console / SCIM. Ownership of securables is held by a
> group (e.g. `cdp_platform_engineers`) so there is no single human owner.

---

## 6. Column masking with UC column-mask functions

A **column mask** is a SQL UDF bound to a column via `ALTER TABLE ... SET MASK`.
UC invokes it transparently on every read; what the caller sees depends on
**their group membership** (evaluated with `is_account_group_member()`). The base
data is unchanged — masking is read-time.

> **Prod-strict environment guard.** Every mask and row filter short-circuits on
> `gold.is_prod()` — a boolean UDF whose value is **baked in at deploy time** from
> the bundle target (`env`). It is `TRUE` only in `cdp_prod`, so masks and row
> filters **enforce strictly in prod** and **relax on the synthetic dev/qa data**,
> letting engineers iterate without fighting redaction. Because the target is a
> literal in the function body (a mask UDF can't read session params), the guard
> cannot be flipped at query time. To also lock down QA, change the baked
> predicate to `env IN ('qa','prod')` in
> [governance/masking_functions.sql](../governance/masking_functions.sql) /
> [notebooks/setup/02](../notebooks/setup/02_masking_row_filters.sql). The guard is
> created first so every downstream mask/filter can call it.

### 6.1 Email mask (`pii`)

```sql
-- governance/masking_functions.sql

CREATE OR REPLACE FUNCTION cdp_prod.gold.mask_email(email STRING)
RETURNS STRING
RETURN
  CASE
    -- Stewards and engineers see the real value.
    WHEN is_account_group_member('cdp_data_stewards')
      OR is_account_group_member('cdp_data_engineers')
      THEN email
    -- Everyone else sees a partially-redacted address: j***@acme.com
    WHEN email IS NULL THEN NULL
    ELSE concat(substr(email, 1, 1), '***@', split(email, '@')[1])
  END;

-- Bind the mask to the column.
ALTER TABLE cdp_prod.gold.customer_360
  ALTER COLUMN email SET MASK cdp_prod.gold.mask_email;
```

| Caller group | Stored value | Returned value |
|--------------|--------------|----------------|
| `cdp_data_stewards` | `jane.doe@acme.com` | `jane.doe@acme.com` |
| `cdp_sales_analysts` | `jane.doe@acme.com` | `j***@acme.com` |
| `cdp_ai_app_users` | `jane.doe@acme.com` | `j***@acme.com` |

### 6.2 Tax id mask / tokenization (`financial_sensitive`)

```sql
CREATE OR REPLACE FUNCTION cdp_prod.gold.mask_tax_id(tax_id STRING)
RETURNS STRING
RETURN
  CASE
    WHEN is_account_group_member('cdp_finance_analysts')
      OR is_account_group_member('cdp_data_stewards')
      THEN tax_id                                   -- finance sees full value
    WHEN tax_id IS NULL THEN NULL
    ELSE concat('***-**-', substr(tax_id, -4))       -- everyone else: last 4 only
  END;

ALTER TABLE cdp_prod.gold.customer_360
  ALTER COLUMN tax_id SET MASK cdp_prod.gold.mask_tax_id;
```

> **Tokenization note:** where last-4 is still too revealing, replace the `ELSE`
> branch with a deterministic token (e.g. `sha2(concat(tax_id, secret_salt), 256)`)
> so values can still be *joined* across products without exposing the original.
> Drop a mask with `ALTER TABLE ... ALTER COLUMN tax_id DROP MASK;`.

---

## 7. Row filters

A **row filter** is a SQL UDF returning a boolean, bound with
`ALTER TABLE ... SET ROW FILTER`. UC applies it as an implicit `WHERE` on every
read, again keyed on group membership.

**Requirement:** finance analysts see *all* accounts; sales analysts see *only
their own territory*.

```sql
-- governance/row_filters.sql

CREATE OR REPLACE FUNCTION cdp_prod.gold.rf_territory(territory STRING)
RETURNS BOOLEAN
RETURN
  -- Finance + stewards + engineers: unrestricted.
  is_account_group_member('cdp_finance_analysts')
  OR is_account_group_member('cdp_data_stewards')
  OR is_account_group_member('cdp_data_engineers')
  -- Sales: only rows whose territory matches a mapping table for this user.
  OR EXISTS (
       SELECT 1
       FROM cdp_prod.ops.user_territory_map m
       WHERE m.user_email = current_user()
         AND m.territory  = territory
     );

ALTER TABLE cdp_prod.gold.revenue_pipeline
  SET ROW FILTER cdp_prod.gold.rf_territory ON (territory);
```

| Caller | Sees |
|--------|------|
| `cdp_finance_analysts` | every territory |
| `cdp_sales_analysts` (EMEA-West rep) | only `EMEA-West` rows |
| `cdp_data_stewards` | every territory (governance/audit) |

Row filters and column masks **compose**: a sales analyst querying
`revenue_pipeline` gets only their territory's rows (filter) *and* masked
`email`/`tax_id` (masks) in one query, with no special SQL.

---

## 8. Governed views vs. direct table access for AI consumers

```
   ┌────────────────────┐        ┌────────────────────┐
   │   Human analysts    │        │   AI agents /       │
   │ (sales/finance/CS)  │        │ cdp_ai_app_users    │
   └─────────┬──────────┘        └─────────┬──────────┘
             │ SELECT on gold views         │ SELECT/EXECUTE on
             │ (row filter + mask)           │ APPROVED agent views only
             ▼                               ▼
   ┌─────────────────────────────────────────────────────┐
   │              gold.* governed VIEWS                   │
   │  v_revenue_pipeline · v_customer_360_agent · ...     │  ← masks/filters/redaction baked in
   └───────────────────────────┬─────────────────────────┘
                               │ (view owner has access)
                               ▼
   ┌─────────────────────────────────────────────────────┐
   │     gold base tables (Delta / Managed Iceberg)       │  ← analysts/agents NOT granted here
   └─────────────────────────────────────────────────────┘
```

Design rules for AI consumers:

1. **Agents never get base-table grants.** They are granted only on a curated set
   of `v_*_agent` views and retrieval functions.
2. **The agent view is the contract.** It selects a fixed, reviewed column set;
   excludes `restricted_free_text` raw columns; applies masks and (optionally) a
   row filter scoped to the app's service principal.
3. **No `SELECT *`.** Agent views enumerate columns so a new sensitive column in
   the base table cannot silently leak.
4. **Provenance is queryable.** Because access flows through views, lineage
   (Section 9) shows exactly which base columns feed each agent view.

```sql
-- An approved agent view: redacted, masked, no free-text leakage.
CREATE OR REPLACE VIEW cdp_prod.gold.v_customer_360_agent AS
SELECT
  account_id,
  account_name,
  industry,
  region,
  health_score,
  mask_email(primary_contact_email) AS primary_contact_email,  -- masked
  arr_band,                                                     -- banded, not raw ARR
  renewal_quarter
FROM cdp_prod.gold.customer_360;
-- Note: tax_id, raw ARR, and free-text notes are deliberately omitted.
```

---

## 9. Data classification tags

UC supports **governed tags** (key/value) on catalogs, schemas, tables, and
columns. We tag every sensitive column with its class so masking/filtering policy
can be discovered and audited consistently.

```sql
-- governance/tags_classification.sql

-- Column-level sensitivity tags.
ALTER TABLE cdp_prod.silver.customer
  ALTER COLUMN email   SET TAGS ('sensitivity' = 'pii');
ALTER TABLE cdp_prod.silver.customer
  ALTER COLUMN tax_id  SET TAGS ('sensitivity' = 'financial_sensitive');
ALTER TABLE cdp_prod.silver.case_comment
  ALTER COLUMN body    SET TAGS ('sensitivity' = 'restricted_free_text');

-- Table / schema level tags for domain + data-product ownership.
ALTER TABLE  cdp_prod.gold.collections_risk
  SET TAGS ('domain' = 'finance', 'data_product' = 'collections_risk',
            'contains' = 'financial_sensitive');
ALTER SCHEMA cdp_prod.bronze SET TAGS ('layer' = 'bronze', 'pii_present' = 'true');
```

**Querying tags** to find every `pii` column in prod (drives reviews + policy
gap detection):

```sql
SELECT catalog_name, schema_name, table_name, column_name
FROM   cdp_prod.information_schema.column_tags
WHERE  tag_name = 'sensitivity'
  AND  tag_value IN ('pii', 'financial_sensitive', 'restricted_free_text')
ORDER  BY 1, 2, 3, 4;
```

> **Governance loop:** a steward job cross-checks `column_tags` against the bound
> masks. Any `pii`/`financial_sensitive` column **without** a `SET MASK` is
> flagged in `ops` as a policy violation.

---

## 10. Automatic lineage + querying lineage system tables

UC captures **table and column lineage automatically** whenever a query/notebook/
DLT pipeline reads and writes governed objects — no instrumentation required. It
surfaces in **Catalog Explorer** (visual graph) and in **system tables**:

| System table | Grain | Use |
|--------------|-------|-----|
| `system.access.table_lineage` | source table → target table per event | "what feeds / consumes this table" |
| `system.access.column_lineage` | source column → target column | column-level impact analysis |

> System tables must be enabled on the metastore (`system.access` schema) and the
> querying group needs `SELECT` on them.

### Impact analysis — "what breaks if I change `silver.customer`?"

**Downstream tables that read `silver.customer`:**

```sql
SELECT DISTINCT
       target_table_catalog AS catalog,
       target_table_schema  AS schema,
       target_table_name    AS table_name
FROM   system.access.table_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer'
  AND  target_table_name IS NOT NULL
ORDER  BY 1, 2, 3;
```

**Column-level: who consumes `silver.customer.email`?** (find every downstream
column derived from it before you rename/drop it):

```sql
SELECT DISTINCT
       target_table_catalog || '.' || target_table_schema || '.' ||
       target_table_name AS downstream_table,
       target_column_name
FROM   system.access.column_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer'
  AND  source_column_name   = 'email'
ORDER  BY 1, 2;
```

**Upstream provenance of an agent view** (proves no raw PII path exists):

```sql
SELECT DISTINCT source_table_catalog, source_table_schema, source_table_name
FROM   system.access.table_lineage
WHERE  target_table_catalog = 'cdp_prod'
  AND  target_table_schema  = 'gold'
  AND  target_table_name    = 'v_customer_360_agent';
```

> Notebooks in `notebooks/lineage/` wrap these queries into reusable impact-analysis
> reports (see [observability.md](./observability.md)).

---

## 11. Audit via system tables

Every action against UC securables is logged to `system.access.audit`. This is
the forensic record: who read what, when, from where.

**Who queried `financial_sensitive` data in the last 7 days:**

```sql
SELECT event_time,
       user_identity.email                       AS user_email,
       request_params.full_name_arg              AS object_accessed,
       action_name,
       source_ip_address
FROM   system.access.audit
WHERE  service_name = 'unityCatalog'
  AND  action_name IN ('getTable', 'generateTemporaryTableCredential')
  AND  request_params.full_name_arg LIKE 'cdp_prod.gold.collections_risk%'
  AND  event_time >= current_timestamp() - INTERVAL 7 DAYS
ORDER  BY event_time DESC;
```

**Grant/revoke changes (who changed permissions):**

```sql
SELECT event_time, user_identity.email, action_name, request_params
FROM   system.access.audit
WHERE  action_name IN ('updatePermissions', 'updateSharePermissions')
  AND  event_time >= current_date() - INTERVAL 30 DAYS
ORDER  BY event_time DESC;
```

Complementary system tables: `system.billing.usage` (cost), `system.compute.*`
(clusters/warehouses), `system.lakeflow.*` / `system.workflow.*` (job and
pipeline runs — see observability).

---

## 12. Free-text governance (`restricted_free_text`)

Case comments, opportunity notes, and support transcripts are the highest-risk
columns: they are **unstructured** and frequently contain PII, financials, and
profanity/legal exposure that structured masking cannot catch by column name.

Handling rules:

| Stage | Rule |
|-------|------|
| **Bronze** | Stored raw, schema-locked to `cdp_data_engineers` + `cdp_data_stewards`. Tagged `sensitivity = restricted_free_text`. |
| **Silver** | Raw free text is **not promoted as-is**. A **PII-scrubbed** copy is produced (regex/NER redaction of emails, phones, card/tax numbers) into a `*_redacted` column; the raw column stays restricted. |
| **Gold** | Only the redacted/summarized form is published. Sentiment/topic/score derivatives are preferred over the text itself. |
| **Agents** | Agents receive **redacted** text or model-generated **summaries** only. Raw free text is never granted to `cdp_ai_app_users`. |

```sql
-- Silver: keep raw restricted, expose only a redacted derivative.
CREATE OR REPLACE VIEW cdp_prod.silver.v_case_comment_safe AS
SELECT case_id,
       created_at,
       -- redact common PII patterns before anyone but stewards sees it
       regexp_replace(
         regexp_replace(body, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+', '[EMAIL]'),
         '\\b\\d{3}-\\d{2}-\\d{4}\\b', '[ID]'
       ) AS body_redacted
FROM cdp_prod.silver.case_comment;

-- Only stewards can read the raw table; everyone else uses the safe view.
GRANT SELECT ON VIEW cdp_prod.silver.v_case_comment_safe TO `cdp_customer_success`;
```

> The raw free-text column is **never** column-masked into a "fake safe" state —
> partial masking of free text is unreliable. Instead the *raw column is locked*
> and a *separately redacted column/view* is the only path forward.

---

## 13. Implementing files (`governance/`)

| File | Responsibility |
|------|----------------|
| `governance/catalogs_schemas.sql` | Create `cdp_dev/qa/prod` catalogs, the per-layer schemas, `landing` volumes, owners/comments. |
| `governance/grants.sql` | All persona → securable `GRANT` statements (the Section 5 matrix). |
| `governance/masking_functions.sql` | `mask_email`, `mask_tax_id`, etc. + `ALTER TABLE ... SET MASK` bindings. |
| `governance/row_filters.sql` | `rf_territory` and other row-filter UDFs + `SET ROW FILTER` bindings. |
| `governance/tags_classification.sql` | `SET TAGS` for the 5 sensitivity classes + domain/data-product tags. |

These are idempotent (`CREATE OR REPLACE`, `GRANT` is additive) and are deployed
per environment by substituting the catalog name — run them against `cdp_dev`,
`cdp_qa`, and `cdp_prod` as part of the bundle deploy. See
[environments.md](./environments.md) for the promotion flow.

---

## 14. Governance checklist (apply to every new table)

- [ ] Created in the correct catalog (env) + schema (layer).
- [ ] Owner set to a **group**, not a person.
- [ ] Every column assigned a sensitivity class and tagged.
- [ ] `pii` / `financial_sensitive` columns have a bound mask in gold.
- [ ] `financial_sensitive` / territory tables have a row filter where required.
- [ ] `restricted_free_text` columns locked; redacted derivative published.
- [ ] Grants written to groups in `grants.sql` — no individual grants.
- [ ] If consumed by agents: an explicit, column-enumerated `v_*_agent` view.
- [ ] Lineage verified in Catalog Explorer; audit confirmed flowing.
