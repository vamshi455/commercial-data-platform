# Development Log

Chronological record of implementation steps, issues hit, and fixes. For tracking dev effort.

---

## 2026-06-29 — Governance, AI semantic layer, ABAC

### 1. Project status review
Reviewed done/pending. Dev platform working (28 bronze + 9 silver + 7 gold); QA deployed (no data); prod created (not configured); CRM cutover half-done; merge-to-main and cost app pending.

### 2. Account-admin unlock
User promoted to Entra Global Admin → auto Databricks **account admin**.
- Created account-level CLI profile `cdp-account` (`accounts.azuredatabricks.net`, account `de01ac70-3bde-41c6-9a81-c1bb6990e4d8`).
- Verified via `account workspaces list` + `account groups list`.
- **Unblocked** the RBAC work parked on account admin.

### 3. RBAC scaffold — groups + test SPs
Created **8 account groups** (`cdp_platform_engineers`, `cdp_data_engineers`, `cdp_analytics_engineers`, `cdp_sales_analysts`, `cdp_finance_analysts`, `cdp_customer_success`, `cdp_data_stewards`, `cdp_ai_app_users`) + **5 test service principals**, one per persona, mapped to their group.
- **Issue:** first membership loop applied only one (wrong) mapping — `zsh` does **not** word-split unquoted `$var` like bash, so `for x in $pairs` ran once.
- **Fix:** removed the bad membership, reapplied all 5 with explicit per-pair commands. Verified.

### 4. AI semantic-layer design
Goal: make catalog objects AI-inferable. Decided the layers needed: comments, tags, PK/FK (optional), metric views, trusted functions, freshness/DQ signals, scoped grants, eval set. Confirmed all are CLI-doable except Genie space authoring.

### 5. Catalog inventory — key discoveries
- gold/silver objects are **DLT materialized views** (not plain tables) → comments/constraints on base objects must live in pipeline source (Track A), not ad-hoc ALTER.
- **Naming mismatch:** real objects are `gold.gold_*` / `silver.silver_*`; governance SQL referenced `gold.customer_360` etc.
- **No PII in serving layer:** silver/gold carry no email/phone/tax_id — only company/product/territory names + aggregates. PII lives only in **bronze**. ERP tax_id/email already pre-masked/tokenized at source.

### 6. Curated views (`governance/semantics.sql`)
Built **5 AI-facing curated views** (`customer_360_curated`, `account_health_curated`, `support_performance_curated`, `revenue_pipeline_curated`, `collections_risk_curated`) — rich column comments (grain + USD units + `aka` synonyms) + `data_as_of` freshness column, marked `CERTIFIED AI-safe`, PII-free. Applied + verified queryable in dev.
- **Issue:** SQL applier split file on `;`, breaking a comment line containing a semicolon.
- **Fix:** strip `--` comments before splitting; use fully-qualified names (each Statement-API call is its own session, so `USE` doesn't persist).

### 7. Governance SQL reconciliation
Reframed goal: actually implement **data security across layers**. Decisions: gold.customer_360 will carry email+phone+tax_id (matches original mask design); bronze stays locked (grants only); AI reads PII-free curated views.
- `grants.sql` → re-pointed to `gold.gold_*`/`silver.silver_*` + curated views. **50 stmts applied OK** (account groups resolve for UC grants even pre-workspace-assignment).
- `tags_classification.sql` → reconciled, split into PART A (exists now), B (CRM bronze post-reload), C (silver/gold PII cols post-Track-A). **24 stmts applied OK**.
- `masking_functions.sql` → 5 mask UDFs (`is_prod`, `mask_email/phone/tax_id/free_text`) applied; mask bindings commented out until columns exist.
- **Issue:** two UDFs failed — COMMENT string literals contained semicolons, breaking the splitter again.
- **Fix:** removed inner semicolons from COMMENT prose (now a standing rule).

### 8. ABAC (GA 2026) — `governance/abac_policies.sql`
Implemented attribute-based masking to replace per-column `SET MASK`: created governed tag `mask` (`email`/`phone`/`tax_id`) + 3 catalog-level COLUMN MASK policies matching `has_tag_value('mask', …)`, `TO account users EXCEPT` the unmask groups. All 3 live in dev (`SHOW POLICIES` confirms).
- **Issue 1:** policies failed — `Unknown tag policy key 'mask'`. ABAC only matches **governed** tags, not ad-hoc.
- **Fix 1:** `CREATE GOVERNED TAG mask VALUES (…)` first (needs account admin).
- **Issue 2:** still failed right after creating the tag — propagation lag.
- **Fix 2:** retried after a moment; succeeded.
- **Issue 3 (recurring):** semicolons in COMMENT strings broke the splitter — removed.
- Note: requires DBR 16.4+/serverless. Inert until PII columns are tagged `mask=*` (Track A).

### Recurring lesson
Keep semicolons **out of SQL COMMENT string literals** — they break naive `;`-splitters (hit 3×). Use fully-qualified names with the Statement Execution API.

### Pending (next)
- **Track A (gated on CRM cutover):** finish cutover → repopulate `bronze_crm_*` → add `silver_contact` (work_email/mobile_phone) + carry primary_email/phone/tax_id into `gold_customer_360` (SET MASK / tags in the MV def) → tag columns `mask=*` to activate ABAC.
- Persona test with the 5 SPs (CS sees email, sales/other-territory doesn't, finance sees tax_id, AI sees nothing).
- Track B remainder: metric views, trusted functions, eval set.
