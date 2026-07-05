#!/usr/bin/env bash
# =============================================================================
# scripts/seed_github_backlog.sh
# -----------------------------------------------------------------------------
# Seeds the MDM/Governance backlog into GitHub Issues: labels, milestones, and
# the 13 prioritized issues from docs/specs/mdm-and-governance.md.
#
# One-time prerequisite:  gh auth login     (needs 'repo' scope; 'project' too if
# you also want the Project board created below).
# Run:  bash scripts/seed_github_backlog.sh
# Idempotent-ish: label/milestone creation tolerates "already exists".
# =============================================================================
set -uo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Seeding backlog into $REPO"

# ---- Labels ----------------------------------------------------------------
mklabel() { gh label create "$1" --color "$2" --description "$3" 2>/dev/null \
            || gh label edit "$1" --color "$2" --description "$3" 2>/dev/null || true; }
mklabel "domain:customer"     "1d76db" "Customer master domain"
mklabel "domain:product"      "0e8a16" "Product/material master domain"
mklabel "domain:supplier"     "5319e7" "Supplier/vendor master domain"
mklabel "domain:cross-cutting" "555555" "Spans multiple domains"
mklabel "type:ingestion"      "fbca04" "Source/ingestion change"
mklabel "type:mdm"            "b60205" "Mastering / survivorship / crosswalk"
mklabel "type:dq"             "c2e0c6" "Data quality"
mklabel "type:governance"     "0052cc" "Governance / access / catalog"
mklabel "type:catalog"        "006b75" "Data catalog / glossary"
mklabel "priority:P0"         "b60205" "Must-have, foundational"
mklabel "priority:P1"         "d93f0b" "High"
mklabel "priority:P2"         "fbca04" "Medium"
mklabel "status:ready"        "0e8a16" "Groomed & ready for pickup (async execution)"
mklabel "status:blocked"      "e11d21" "Blocked"

# ---- Milestones ------------------------------------------------------------
mkms() { gh api "repos/$REPO/milestones" -f title="$1" -f description="$2" >/dev/null 2>&1 \
         && echo "milestone: $1" || echo "milestone exists: $1"; }
mkms "M1 Source enrichment"     "Add missing MDM source fields to generators + ingestion"
mkms "M2 Customer master"       "Customer crosswalk + survivorship golden record + DQ"
mkms "M3 Product & Supplier"    "Product & supplier masters + DQ scorecards"
mkms "M4 Governance & catalog"  "Glossary, certified tags, DQ rollup, steward design"

# ---- Issues ----------------------------------------------------------------
# issue <title> <milestone> <labels-csv> <body>
issue() {
  local title="$1" ms="$2" labels="$3" body="$4"
  gh issue create --repo "$REPO" --title "$title" --milestone "$ms" \
    --label "$labels" --body "$body" >/dev/null \
    && echo "  + $title" || echo "  ! failed: $title"
}

# M1 — source enrichment
issue "MDM: add customer master source fields" "M1 Source enrichment" \
  "domain:customer,type:ingestion,priority:P0,status:ready" \
  "Add to CRM \`accounts\` (Postgres schema + crm_generator) and ERP \`customers\` (erp_generator): duns_number, lei, registration_number, parent_account_id, ultimate_parent_id, structured address (street/city/state/postal_code/country_code + geocode), address roles (bill-to/ship-to/sold-to), naics_code/sic_code, lifecycle_status, block_flag, source_system, source_record_id, source_last_updated, verified_flag, steward_owner. See docs/specs/mdm-and-governance.md."
issue "MDM: add product/material master source fields" "M1 Source enrichment" \
  "domain:product,type:ingestion,priority:P0,status:ready" \
  "Add to ERP products SCD (erp_generator) + reference: crm_product_id crosswalk key, uom + uom_conversions (BBL/MT factors), api_gravity, sulfur_pct, hs_code, product_hierarchy_id linkage, lifecycle_status/discontinued_flag, source_system, source_record_id."
issue "MDM: add supplier/vendor master source fields" "M1 Source enrichment" \
  "domain:supplier,type:ingestion,priority:P0,status:ready" \
  "Add to ERP vendors (erp_generator): duns_number, lei, parent_vendor_id, structured + multi-role address (remit-to/order-from), onboarding_status, approval_status, block_flag, sanctions_screened_flag, sanctions_status, bank_master_ref, source_system, source_record_id."
issue "MDM: propagate new columns through bronze + update docs/data-contracts" "M1 Source enrichment" \
  "domain:cross-cutting,type:ingestion,priority:P1,status:ready" \
  "Verify Auto Loader addNewColumns picks up new CSV columns and the JDBC snapshot reads new Postgres columns; update source-systems.md, data-contracts.md, entity docs."

# M2 — customer master
issue "MDM: persisted customer_xref (match confidence + history)" "M2 Customer master" \
  "domain:customer,type:mdm,priority:P0,status:ready" \
  "Create silver.customer_xref: (crm_account_id, erp_customer_id, match_method, match_confidence, matched_at) with history. Replace reliance on the throwaway generator crosswalk."
issue "MDM: customer survivorship golden record" "M2 Customer master" \
  "domain:customer,type:mdm,priority:P0,status:ready" \
  "Build gold.customer_master applying source trust ranking + best-attribute-wins per field with per-field provenance; keep stable customer_sk."
issue "MDM: customer DQ scorecard" "M2 Customer master" \
  "domain:customer,type:dq,priority:P1,status:ready" \
  "Completeness/validity/uniqueness expectations for customer master; materialize governance.dq_scorecard metrics."

# M3 — product & supplier
issue "MDM: product crosswalk + survivorship golden record" "M3 Product & Supplier" \
  "domain:product,type:mdm,priority:P1,status:ready" \
  "CRM product <-> ERP material crosswalk + gold.product_master survivorship."
issue "MDM: supplier golden record + sanctions handling" "M3 Product & Supplier" \
  "domain:supplier,type:mdm,priority:P1,status:ready" \
  "gold.supplier_master survivorship; surface sanctions_screened_flag/status and block_flag in the master."
issue "MDM: product & supplier DQ scorecards" "M3 Product & Supplier" \
  "domain:cross-cutting,type:dq,priority:P1,status:ready" \
  "Extend governance.dq_scorecard to product and supplier masters."

# M4 — governance & catalog
issue "Catalog: UC business glossary + certified tags for masters" "M4 Governance & catalog" \
  "domain:cross-cutting,type:catalog,priority:P2,status:ready" \
  "Define business glossary terms and apply certified-dataset UC tags to the three master tables."
issue "Governance: DQ scorecard rollup + observability hook" "M4 Governance & catalog" \
  "domain:cross-cutting,type:governance,priority:P2,status:ready" \
  "Roll up dq_scorecard into a freshness/quality view surfaced to observability."
issue "Governance: steward review-queue design spec" "M4 Governance & catalog" \
  "domain:cross-cutting,type:governance,priority:P2,status:blocked" \
  "Design (spec only) a steward review queue: merge/unmerge, manual match override, audit."

echo "Done. View: gh issue list --repo $REPO --label status:ready"
