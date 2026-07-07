# Decisions Log (ADR-lite)

Resolutions to the project-review questions (2026-07-04). Each entry: the doubt,
the decision, and whether it's **done** or **tracked** (backlog/checkpoint).

## D1 — CRM source fields the docs describe but the generator doesn't emit
**Doubt:** `source-systems.md` says `accounts` has `duns_number`, `website`,
`parent_account_id`, `tax_id`, `billing_address`; the generator/Postgres schema
emit none.
**Decision:** enrich the generators to produce them. This is done in **one place —
MDM milestone M1** (see D9). Docs annotated to mark those fields **planned (MDM M1)**
until emitted. *(docs annotated — done; generator enrichment — tracked, MDM M1)*

## D2 — Table naming standardization
**Doubt:** docs specify clean `bronze.crm_accounts` / `silver.customer` /
`gold.customer_360`; deployed reality is redundant `bronze.bronze_erp_customers`,
`silver.silver_customer`, `gold.gold_customer_360` (layer prefix repeats the schema).
**Decision:** **standardize on the clean, redundancy-free convention** already in
`naming-conventions.md` (form A). The deployed `<layer>.<layer>_*` names are tech
debt. Rename requires renaming DLT `@dlt.table` names + repointing governance SQL +
curated views + a pipeline **redeploy (compute)**, so it is a tracked refactor, not
executed now. *(standard set — done; rename — tracked, needs compute)*

## D3 — CI/CD deploy-qa / deploy-prod target deleted workspaces
**Decision:** disable auto-deploy now (workspaces torn down; repo pushes to main so
prod would fire every commit). Both workflows set to `workflow_dispatch`-only; push
triggers commented out with a re-enable note. *(done)*

## D4 — PII in the serving layer
**Doubt:** dev-log toggled between "no PII in serving layer" and "gold carries PII".
**Decision:** **gold carries PII** (email/phone/tax_id) **protected by column
masks + ABAC**; specific persona groups are granted unmasked access per policy
(e.g. CS sees email, finance sees tax_id, AI/curated-views see none). This matches
the masking/ABAC design already applied in dev. Bronze stays locked (grants only).
*(decision recorded; column-level activation tracked under governance "Track A")*

## D5 — `_common.py` inlined into each ingestion file
**Doubt:** shared helpers are copy-pasted into `erp_autoloader.py` /
`reference_autoloader.py` because serverless DLT can't import a sibling `.py`.
**Decision:** **fix properly** — package the shared helpers so there is a single
source of truth (preferred: build a small wheel added to the pipeline
`environment`/`libraries`; fallback: `%run ./_common` notebook include). Remove the
inlined blocks. *(tracked)*

## D6 — Silver built on non-existent CRM bronze
**Decision:** **CRM is a critical, first-class source.** Finishing the CRM
Postgres→bronze cutover (repopulate `bronze_crm_*`) is the priority unblocker before
further silver/gold work; CRM-dependent silver objects are stale until then.
*(tracked — top priority; see checkpoint / deployment-state)*

## D7 — Observability (`ops.dq_results` / SLA) designed but not built
**Status:** user wants to understand scope before deciding. **Open** — see the
"Observability" discussion; decide in/out of scope next. *(open)*

## D8 — Retire oil & gas / trading framing
**Decision:** platform models a **B2B industrial-equipment manufacturer**. Removed
oil references from the contract module (type keywords → MSA/distributor/pricing/
supply/NDA/warranty), its tests, the contract spec, module README, and brainstorming
doc. `business-domain-and-systems.md` is the domain source of truth. *(done)*

## D9 — MDM as the single place new master fields are added
**Decision:** the MDM **M1 source-enrichment** issues are the one place the missing
master fields (customer/product/supplier) get added to generators + ingestion; docs
that currently *claim* those fields are corrected to say **planned**. *(done for docs;
field-add tracked in MDM M1 backlog)*

---
### Still open / needs your input
- **D7** observability scope.
- (from review) **#11** keep or delete the idle-billing dev Vector Search endpoint.
- (from review) **#12** are any `notebooks/` dashboards actually built? (Phase 5)
