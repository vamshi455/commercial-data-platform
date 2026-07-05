# Spec: MDM, Data Catalog & Governance (Standard scope)

**Status:** Approved scope — backlog seeded, not yet built
**Owner:** vamshi
**Scope decision (2026-07-04):** **Standard** — 3 masters (customer / product /
supplier) + survivorship golden records + persisted crosswalk + DQ scorecards,
including adding the missing source fields to generators + ingestion.
(Full scope — hierarchies, steward workflow, glossary/catalog, ABAC — is deferred
to a later phase; a few M4 items below stub it.)

## Problem

The platform has **identity resolution** (`silver.customer_master`) but no
**authoritative master**, no **golden-record survivorship**, and no **governed
catalog**. Sources emit operational attributes but omit the fields that make a
record authoritative (legal identity, hierarchy, per-source provenance).

## Missing source data points (add to generators + ingestion)

### Customer  (CRM `accounts` + ERP `customers`)
- `duns_number`, `lei`, `registration_number` — external identity / matching
- `parent_account_id`, `ultimate_parent_id` — corporate hierarchy
- Structured address: `street`, `city`, `state`, `postal_code`, `country_code` (+ geocode) — replacing the single address string
- Multiple address roles: bill-to / ship-to / sold-to
- `naics_code` / `sic_code` — standardized industry (vs free-text `industry`)
- `lifecycle_status` (prospect/active/inactive), `block_flag`
- `source_system`, `source_record_id`, `source_last_updated` — required for survivorship
- `verified_flag`, `steward_owner`

### Product / Material  (ERP `products` SCD)
- `crm_product_id` ↔ `material_id` crosswalk (none today)
- `uom` + `uom_conversions` (base `EA` only; crude needs BBL / MT + factors)
- Grade specs: `api_gravity`, `sulfur_pct`; `hs_code` / commodity code
- `product_hierarchy_id` linkage (reference hierarchy not joined to material)
- `lifecycle_status` / `discontinued_flag`, `source_system`, `source_record_id`

### Supplier / Vendor  (ERP `vendors`)
- `duns_number`, `lei`, `parent_vendor_id`
- Structured + multi-role address (remit-to / order-from)
- `onboarding_status`, `approval_status`, `block_flag`
- `sanctions_screened_flag`, `sanctions_status` — compliance for commodity trading
- `bank_master_ref` (vs `bank_reference_last4`), `source_system`, `source_record_id`

## Target design

1. **Bronze** — new columns flow through automatically (Auto Loader
   `addNewColumns` for CSV; JDBC snapshot picks up new columns). Update entity
   docs + data contracts.
2. **Crosswalk / xref** — persisted `silver.<domain>_xref` table with
   `match_method`, `match_confidence`, `matched_at`, history (not the throwaway
   generator crosswalk). Deterministic + crosswalk today; probabilistic later.
3. **Golden record (survivorship)** — `gold.<domain>_master` (or silver) applying
   **source trust ranking** + best-attribute-wins per field, with per-field
   provenance. Retains stable surrogate key.
4. **DQ scorecard** — per-master completeness / validity / uniqueness expectations
   materialized to a `governance.dq_scorecard` metrics table (feeds observability).
5. **Catalog/governance (M4, partial)** — UC business glossary + certified tags on
   the masters; steward review-queue design spec.

## Rollout (milestones) & backlog

See `scripts/seed_github_backlog.sh` — the authoritative, runnable backlog. Summary:

| # | Milestone | Issue | Prio |
|---|---|---|---|
| 1 | M1 Source enrichment | Customer MDM source fields → generators + Postgres schema | P0 |
| 2 | M1 | Product/material MDM fields → generator | P0 |
| 3 | M1 | Supplier/vendor MDM fields → generator | P0 |
| 4 | M1 | Propagate new columns through bronze + docs/data-contracts | P1 |
| 5 | M2 Customer master | Persisted `customer_xref` (confidence + history) | P0 |
| 6 | M2 | Customer survivorship golden record | P0 |
| 7 | M2 | Customer DQ scorecard | P1 |
| 8 | M3 Product & Supplier | Product crosswalk + golden record | P1 |
| 9 | M3 | Supplier golden record + sanctions handling | P1 |
| 10 | M3 | Product & Supplier DQ scorecards | P1 |
| 11 | M4 Governance & catalog | UC business glossary + certified tags | P2 |
| 12 | M4 | DQ scorecard rollup + observability hook | P2 |
| 13 | M4 | Steward review-queue design spec | P2 |

## Async execution model

Backlog lives in **GitHub Issues + Projects**. An issue labelled `status:ready`
is fair game: a scheduled Claude Code routine (or a session) takes the highest-
priority `ready` issue, implements on a branch → PR, comments back. You review PRs
when you return. Priorities via `priority:P0/P1/P2` labels; rollout via milestones.
