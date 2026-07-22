#!/usr/bin/env bash
# =============================================================================
# scripts/seed_github_backlog.sh
# -----------------------------------------------------------------------------
# Seeds the CONSOLIDATED CDP backlog into GitHub Issues + the CDP Project board:
# labels, milestones, ~31 grouped issues, then adds every issue to the project
# and sets its Priority/Area/Size fields.
#
# Design note: features that are "the same work across several tables/domains/
# systems" are ONE issue with a checklist — not one issue per table. (customer/
# product/supplier enrichment = 1 issue; MES/PLM/WMS = 1 issue; E3/E5/E6 = 1
# issue; etc.) This is the consolidation pass over the original 51-issue seed.
#
# Sources compiled from:
#   docs/checkpoint.md, docs/decisions.md, docs/specs/mdm-and-governance.md,
#   docs/embedding-lifecycle.md, docs/token-optimization-cost.md,
#   docs/agent-evals.md, docs/business-domain-and-systems.md
#
# One-time prerequisite:  gh auth login -s project,repo
# Run:  bash scripts/seed_github_backlog.sh
# Idempotent: labels/milestones are upserted; an issue whose exact title already
# exists is skipped. Board fields are set by scripts/sync_project_fields.sh.
# =============================================================================
set -uo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${REPO%%/*}"
PROJECT_NUMBER="${PROJECT_NUMBER:-6}"
echo "Seeding backlog into $REPO -> project #$PROJECT_NUMBER (owner: $OWNER)"

# ---- Labels ----------------------------------------------------------------
mklabel() { gh label create "$1" --color "$2" --description "$3" 2>/dev/null \
            || gh label edit "$1" --color "$2" --description "$3" 2>/dev/null || true; }
mklabel "area:mdm"          "b60205" "Mastering / survivorship / crosswalk"
mklabel "area:rag"          "8250df" "contract_intelligence RAG: corpus, retrieval, eval"
mklabel "area:agent-ops"    "5319e7" "Agent lifecycle: deploy gates, monitoring, feedback"
mklabel "area:ingestion"    "fbca04" "Sources, generators, bronze ingestion"
mklabel "area:governance"   "0052cc" "Governance / access / catalog / PII"
mklabel "area:ml"           "1d76db" "ML features, scoring, activation / reverse-ETL"
mklabel "area:platform"     "006b75" "Pipelines, naming, CI/CD, cost, ops"
mklabel "domain:customer"   "1d76db" "Customer master domain"
mklabel "domain:product"    "0e8a16" "Product/material master domain"
mklabel "domain:supplier"   "5319e7" "Supplier/vendor master domain"
mklabel "domain:cross-cutting" "555555" "Spans multiple domains"
mklabel "type:feature"      "0e8a16" "New capability"
mklabel "type:bug"          "d73a4a" "Something is broken / silently wrong"
mklabel "type:tech-debt"    "e4e669" "Refactor / cleanup / correctness debt"
mklabel "type:spike"        "c5def5" "Investigation or design spec only"
mklabel "type:dq"           "c2e0c6" "Data quality"
mklabel "priority:P0"       "b60205" "Must-have, foundational or actively broken"
mklabel "priority:P1"       "d93f0b" "High"
mklabel "priority:P2"       "fbca04" "Medium"
mklabel "priority:P3"       "ededed" "Low / someday"
mklabel "status:ready"      "0e8a16" "Groomed & ready for pickup (async execution)"
mklabel "status:blocked"    "e11d21" "Blocked on a dependency"
mklabel "status:needs-decision" "fef2c0" "Needs a call from the owner before work starts"

# ---- Milestones ------------------------------------------------------------
mkms() { gh api "repos/$REPO/milestones" -f title="$1" -f description="$2" >/dev/null 2>&1 \
         && echo "milestone: $1" || echo "milestone exists: $1"; }
mkms "M1 Source enrichment"      "Add missing MDM source fields to generators + ingestion"
mkms "M2 MDM masters"            "Crosswalks + survivorship golden records + DQ across all masters"
mkms "M3 Governance & catalog"   "Glossary, certified tags, PII masks/ABAC, steward design"
mkms "M4 Core pipeline & debt"   "CRM cutover, table naming, shared-helper packaging"
mkms "M5 Agent lifecycle"        "Deploy gates, observability pipeline, HITL, governance"
mkms "M6 RAG correctness"        "Embedding lifecycle, retrieval ground-truth, corpus/eval scaling"
mkms "M7 New source systems"     "MES / PLM / WMS generators + bronze ingestion"
mkms "M8 Platform ops & cost"    "Durable scheduling, cost telemetry, open decisions"
mkms "M9 Advanced: ML & activation" "Feature store, real-time scoring, reverse-ETL / CDP activation"

# ---- Issue creation --------------------------------------------------------
EXISTING="$(mktemp)"
gh issue list --repo "$REPO" --state all --limit 500 --json title -q '.[].title' > "$EXISTING" 2>/dev/null || true
CREATED_URLS="$(mktemp)"

# issue <title> <milestone> <labels-csv> <body>
issue() {
  local title="$1" ms="$2" labels="$3" body="$4"
  if grep -Fxq "$title" "$EXISTING"; then echo "  = exists, skipped: $title"; return; fi
  local url
  url="$(gh issue create --repo "$REPO" --title "$title" --milestone "$ms" \
          --label "$labels" --body "$body" 2>/dev/null)"
  if [[ -n "$url" ]]; then echo "  + $title"; echo "$url" >> "$CREATED_URLS"
  else echo "  ! failed: $title"; fi
}

echo ""
echo "== M1 — source enrichment =="
issue "MDM: enrich master source fields (customer / product / supplier)" "M1 Source enrichment" \
  "area:mdm,domain:cross-cutting,type:feature,priority:P0,status:ready" \
  "Add the missing master fields to the generators + ingestion. Per **D9** this is the *single place* these fields are added; docs currently mark them *planned (MDM M1)*.

- [ ] **Customer** — CRM \`accounts\` (Postgres + crm_generator) & ERP \`customers\` (erp_generator): duns_number, lei, registration_number, parent_account_id, ultimate_parent_id, structured address (street/city/state/postal_code/country_code + geocode), address roles (bill-to/ship-to/sold-to), naics_code/sic_code, lifecycle_status, block_flag, source_system, source_record_id, source_last_updated, verified_flag, steward_owner.
- [ ] **Product/material** — ERP products SCD + reference: crm_product_id crosswalk key, uom + uom_conversions, hs_code, product_hierarchy_id linkage, lifecycle_status/discontinued_flag, source_system, source_record_id. ⚠️ Use **Rheinhardt** divisions (Flow/Power/Care/Services) — the oil-era attributes (api_gravity, sulfur_pct, BBL/MT) in the spec are retired per **D8**; reconcile the spec while doing this.
- [ ] **Supplier/vendor** — ERP vendors (erp_generator): duns_number, lei, parent_vendor_id, structured + multi-role address (remit-to/order-from), onboarding_status, approval_status, block_flag, sanctions_screened_flag, sanctions_status, bank_master_ref, source_system, source_record_id.
- [ ] **Propagate** — verify Auto Loader \`addNewColumns\` picks up new CSV columns and the JDBC snapshot reads new Postgres columns; update source-systems.md, data-contracts.md, entity docs.

See \`docs/specs/mdm-and-governance.md\`, \`docs/decisions.md\` D1/D9."

echo ""
echo "== M2 — MDM masters =="
issue "MDM: crosswalks + survivorship golden records (all masters)" "M2 MDM masters" \
  "area:mdm,domain:cross-cutting,type:feature,priority:P0,status:ready" \
  "Persisted crosswalks + gold survivorship for the three masters. Replace reliance on the throwaway generator crosswalk.

- [ ] **Customer xref** — \`silver.customer_xref\` (crm_account_id, erp_customer_id, match_method, match_confidence, matched_at) with history.
- [ ] **Customer master** — \`gold.customer_master\`: source trust ranking + best-attribute-wins per field with per-field provenance; stable customer_sk.
- [ ] **Product** — CRM product ↔ ERP material crosswalk + \`gold.product_master\` survivorship.
- [ ] **Supplier** — \`gold.supplier_master\` survivorship; surface sanctions_screened_flag/status and block_flag in the master.

Depends on M1. See \`docs/specs/mdm-and-governance.md\`."
issue "MDM: DQ scorecards for all masters + observability rollup" "M2 MDM masters" \
  "area:mdm,domain:cross-cutting,type:dq,priority:P1,status:ready" \
  "One DQ framework across customer/product/supplier — completeness/validity/uniqueness expectations materialized to \`governance.dq_scorecard\`, then rolled up into a freshness/quality view surfaced to observability.

- [ ] Customer master expectations → \`governance.dq_scorecard\`.
- [ ] Extend to product + supplier masters.
- [ ] Rollup view for observability (overlaps the D7 observability-scope decision — settle that first).

Depends on M2 masters."

echo ""
echo "== M3 — governance & catalog =="
issue "Governance: activate gold PII column masks + ABAC per persona (D4)" "M3 Governance & catalog" \
  "area:governance,domain:cross-cutting,type:feature,priority:P1,status:ready" \
  "**D4:** gold carries PII (email/phone/tax_id) protected by column masks + ABAC; persona groups get unmasked access per policy (CS sees email, finance sees tax_id, AI/curated views see none). Bronze stays locked (grants only). The 8 \`cdp_*\` account groups + 5 test SPs already exist (RBAC unblocked 2026-06-29).

⚠️ Reconcile first: the governance SQL targets a **non-existent schema shape** (\`gold.gold_*\`/\`silver.silver_*\`) and asserts *no PII in serving*, contradicting D4. Overlaps the D2 rename.

See \`docs/decisions.md\` D4."
issue "Explore Databricks built-in Data Classification (UC) for auto-tagging + ABAC" "M3 Governance & catalog" \
  "area:governance,domain:cross-cutting,type:spike,priority:P1,status:ready" \
  "**Exploration / spike.** Evaluate Unity Catalog's **built-in Data Classification** (GA: agentic auto-tagging of sensitive columns + a review UI) and how it feeds ABAC. Ties to the **2026-07-10 PII decision**: don't build a custom PII scanner — UC Data Classification + ABAC are GA and cover it; this spike validates that call.

- [ ] Run auto-classification over the CDP catalogs — accuracy on gold (email/phone/tax_id) vs. our masking regexes.
- [ ] How auto-tags drive **ABAC** vs. the D4 column masks — overlap or complement?
- [ ] Review UI / steward workflow — does it subsume part of the steward-review-queue spec?
- [ ] Cost + enablement; any always-on billing?
- [ ] Decide: adopt as the PII-tagging mechanism; what (if anything) D4 masking still owns.

Relates to D4 + the steward review-queue spec. See \`docs/decisions.md\`, checkpoint 2026-07-10."
issue "Catalog: UC business glossary + certified tags for masters" "M3 Governance & catalog" \
  "area:governance,domain:cross-cutting,type:feature,priority:P2,status:ready" \
  "Define business-glossary terms and apply certified-dataset UC tags to the three master tables."
issue "Governance: steward review-queue design spec" "M3 Governance & catalog" \
  "area:governance,domain:cross-cutting,type:spike,priority:P2,status:ready" \
  "Design (spec only) a steward review queue: merge/unmerge, manual match override, audit. Reuses the shared \`ops.action_queue\` + \`ops.action_feedback\` infra proven by the collections agent. Per the 2026-07-10 PII decision this app is aimed at **MDM/entity stewardship** (the Tamr-shaped gap), NOT PII scanning — UC Data Classification + ABAC are GA and cover that."

echo ""
echo "== M4 — core pipeline & debt =="
issue "D6: finish CRM Postgres -> bronze cutover (repopulate bronze_crm_*)" "M4 Core pipeline & debt" \
  "area:ingestion,domain:cross-cutting,type:bug,priority:P0,status:ready" \
  "🔴 **TOP PRIORITY — half-done and currently broken.** Dev CRM bronze was dropped mid-cutover, so CRM-dependent silver objects are stale — built on a non-existent source. **D6:** CRM is a critical, first-class source; finishing the cutover unblocks further silver/gold work. Path: local Postgres + ngrok tunnel → Databricks bronze (on-demand). Loader is done; the cutover is what's incomplete. See \`docs/decisions.md\` D6 + deployment-state / postgres-crm-source notes."
issue "Fix table-name drift: D2 rename + broken job_platform_setup" "M4 Core pipeline & debt" \
  "area:platform,domain:cross-cutting,type:tech-debt,priority:P1,status:ready" \
  "Two symptoms of the same drift, fix together.

- [ ] **D2 rename** — standardize on the redundancy-free names in \`naming-conventions.md\` (\`bronze.crm_accounts\`, \`silver.customer\`, \`gold.customer_360\`); deployed reality is \`<layer>.<layer>_*\`. Scope: rename DLT \`@dlt.table\` names + repoint governance SQL + curated views + **pipeline redeploy (needs compute)**.
- [ ] **job_platform_setup** — the knowledge graph (2026-07-16) flagged this job as broken and doc↔object name drift. Reproduce the failure; likely the same naming mismatch.

See \`docs/decisions.md\` D2, \`docs/knowledge-graph.html\`."
issue "D5: package _common.py helpers instead of inlining into each ingestion file" "M4 Core pipeline & debt" \
  "area:platform,domain:cross-cutting,type:tech-debt,priority:P2,status:ready" \
  "**D5:** shared helpers are copy-pasted into \`erp_autoloader.py\` / \`reference_autoloader.py\` because serverless DLT can't import a sibling \`.py\`. Preferred: build a small wheel added to the pipeline \`environment\`/\`libraries\`. Fallback: \`%run ./_common\`. Remove the inlined blocks. See \`docs/decisions.md\` D5."
issue "Decide: authentic source-system bronze names (sfdc_* / sap_*)" "M4 Core pipeline & debt" \
  "area:ingestion,domain:cross-cutting,type:spike,priority:P3,status:needs-decision" \
  "🔽 **VERY LOW PRIORITY — parked idea; do not prioritize over D6 or the new-source-systems work.** Rename bronze from \`crm_*\`/\`erp_*\` to real source names (Salesforce \`sfdc_*\`; SAP \`sap_kna1\`/\`sap_vbak\`/\`sap_vbrk\`/\`sap_acdoca\`), silver/gold stay clean — 'conform-the-mess' realism. Direction decided (**authentic bronze, clean silver**) then parked. Natural to fold into the D2 rename. Full mapping is in the 2026-07-07 chat."

echo ""
echo "== M5 — agent lifecycle =="
issue "Agent lifecycle: make job_agent_eval a deployment gate" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:feature,priority:P0,status:ready" \
  "**Cheapest, highest-value lifecycle gap.** \`ci.yml\` runs \`pytest\` only; \`job_agent_eval\` is NOT in deploy-qa/deploy-prod. Gate promotion on the meaningful hard gates: PII leaks = 0, injections obeyed = 0, citation accuracy. **Do NOT gate on \`refused\`** — it's advisory until it moves to an LLM judge (see the is_refusal issue). See \`docs/checkpoint.md\` lifecycle gap #1."
issue "Agent observability: inference tables -> monitoring -> HITL feedback loop" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:feature,priority:P1,status:ready" \
  "The whole PROD observability spine, built in dependency order (each step needs the previous).

- [ ] **Inference Tables** — enable \`auto_capture\` on the serving endpoint; today prod prompts/responses/latency are logged nowhere → **prod is blind**.
- [ ] **Lakehouse Monitoring** — drift/quality/toxicity over the inference table.
- [ ] **HITL feedback** — persist Review App feedback into \`ops.action_feedback\` (same shape the collections agent uses) and back into the golden set.
- [ ] **Close the loop** — alerting; route prod failures back to DEV.

See \`docs/checkpoint.md\` lifecycle gaps #2–#5."
issue "Agent lifecycle: version prompts (MLflow Prompt Registry) + Champion/Challenger aliases" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:tech-debt,priority:P2,status:ready" \
  "Prompts are duplicated + unversioned; no Champion/Challenger UC aliases for staged rollout/rollback. The \`agent.py\`/\`model.py\` duplication is tolerated by design (served artifact can't import siblings without \`code_paths\`) and drift is locked by \`test_served_and_evaluated_prompts_are_identical\`; the registry removes the duplication properly. See \`docs/checkpoint.md\` lifecycle gap #6."
issue "Agent: govern behind Databricks AI Gateway + populate its description" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:feature,priority:P2,status:ready" \
  "Put the agent behind **Databricks AI Gateway** for governed access (rate limits, usage tracking, guardrails, per-consumer policy) rather than a bare serving endpoint. While there: the agent's description is empty in the Gateway/serving UI — populate it (same treatment applied to catalogs/jobs on 2026-07-12)."
issue "Agent: high-level BEHAVIOR test scenarios (distinct from evals)" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:feature,priority:P2,status:ready" \
  "Evals score answer *quality* over a golden set; this is the other axis — **behavioral** assertions: declines out-of-scope, respects the SCOPE list, stays grounded, handles empty retrieval, survives a malformed question. Assertions, not scores."
issue "Collections agent: tighten LLM JSON output with structured outputs" "M5 Agent lifecycle" \
  "area:agent-ops,domain:cross-cutting,type:tech-debt,priority:P3,status:ready" \
  "Polish: 1-in-5 LLM calls missed valid JSON (lenient fallback caught it) — use structured outputs. Also \`gold.collections_risk\` is a synthetic seed today — swap to real gold after the D6 cutover."

echo ""
echo "== M6 — RAG correctness =="
issue "RAG: fix embedding lifecycle — edit / delete / re-chunk (E3/E5/E6) + tests" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:bug,priority:P0,status:ready" \
  "🔴 **The corpus is append-only and the failures are SILENT** — the agent serves stale/withdrawn contracts with confident citations. Fix all three plus the tests that prove them.

- [ ] **E5 delete** — \`03_gold_merge\` has no delete branch; chunks of a removed PDF stay \`is_current=true\` forever. ⚠️ \`WHEN NOT MATCHED BY SOURCE DELETE\` is **the trap** (wipes every other doc on an incremental run). Correct: reconcile against the **volume file listing** (cheap metadata, no re-parse) → **soft-delete** (retriever already filters \`is_current=false\`).
- [ ] **E3 in-place edit** — Auto Loader checkpoint keys on file *path* (changed bytes under the same name never re-read) + silver's \`source_file\` anti-join blocks it again. A revised contract is invisible.
- [ ] **E6 orphans** — re-chunking into fewer chunks leaves old high-\`chunk_seq\` chunks current+retrievable. Guard the delete with \`t.source_file IN (SELECT source_file FROM staged)\` — only files touched this run are candidates.
- [ ] **Test job** \`job_embedding_lifecycle\` exercising E1–E7 so it can't silently regress (E1/E2/E7 pass today; E4 amendment has never run live).
- [ ] **E2E test A6** — modified PDF re-embeds and the agent chat reflects it (fails today by construction).

All stay incremental — deletion must NOT force a full load. See \`docs/embedding-lifecycle.md\`."
issue "RAG: backfill retrieval ground-truth after a live index_sync (chunk_ids + real pages)" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:bug,priority:P1,status:blocked" \
  "Both need a live pipeline run, not code — do them in one pass after the first \`index_sync\`.

- [ ] **expected_chunk_ids** are all empty → retrieval recall/precision/MRR are **dead**. chunk_ids are \`sha256(source_file:seq)\`, unknowable until indexed. Resolve at seed time (the golden set already resolves stable \`(file, seq)\` refs — 2026-07-16), don't paste hashes.
- [ ] **\`_page_for\` always returns 1** → every citation's page is fabricated. Needs real paging out of \`ai_parse_document\`; \`citation_accuracy_paged\` already exists and is waiting on it.

Audit gaps #1 + #5. See \`docs/checkpoint.md\`."
issue "RAG: scale corpus + eval — multi-chunk contracts, grow golden set, re-tune k" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:feature,priority:P1,status:ready" \
  "\`recall@5 = 1.0\` today is **1.0 by construction** — each contract is one chunk and \`k=5\` pulls ~83% of a 6-doc corpus, so retrieval can't miss. Retrieval metrics stay decorative until this lands.

- [ ] **Lengthen contracts** so retrieval splits into multiple chunks (corpus is generated reproducibly by \`data_gen/contract_generator.py\`).
- [ ] **Grow + reframe the golden set** (10 rows is smoke-test-only) against the Rheinhardt corpus; keep it in the pure \`golden_set.py\` module.
- [ ] **Re-tune k=5** — it was implicitly sized to 1-chunk-per-doc; multi-chunk needs re-tuning or context tokens multiply unexamined.

See \`docs/token-optimization-cost.md\`."
issue "RAG: replace is_refusal keyword-matching with an LLM judge" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:bug,priority:P1,status:ready" \
  "\`is_refusal\` keyword-matching failed twice in two attempts on textbook-correct declines. **Two misses in two tries = wrong tool.** Move to an LLM judge (\`guideline_adherence\`); keep regex for PII and exact-match for the injection canary where determinism is right. Until this lands, \`refused\` is advisory, NOT a gate. See \`docs/checkpoint.md\`, \`docs/agent-evals.md\`."
issue "RAG: log per-call token usage + dollar cost from MLflow traces" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:feature,priority:P1,status:ready" \
  "No token/cost logging exists in \`run_agent_eval.py\` or \`model.py\` — per-eval-run and per-request LLM cost is captured nowhere (MLflow traces latency/spans only). Pull token usage off the MLflow trace per call and trend it. See \`docs/token-optimization-cost.md\`."
issue "RAG: over-engineering review (custom chunker, SCD amendments, streaming bronze)" "M6 RAG correctness" \
  "area:rag,domain:cross-cutting,type:tech-debt,priority:P3,status:ready" \
  "Spike, decide keep/simplify/delete for each: a custom **154-line chunker** reimplements a shipped lib; **SCD amendment/versioning** (E4) has never run live and likely never fires; **streaming bronze** for ~11 chunks / 5 PDFs. Don't delete E4 without checking it against the E3/E5 redesign."

echo ""
echo "== M7 — new source systems =="
issue "Add MES / PLM-BOM / WMS generators + bronze ingestion" "M7 New source systems" \
  "area:ingestion,domain:cross-cutting,type:feature,priority:P0,status:ready" \
  "Synthetic generators + bronze ingestion for the three new systems, matching the Rheinhardt Industrial domain (Flow/Power/Care/Services). Same shape of work per system → one issue, one checklist.

- [ ] **MES** — Manufacturing Execution System.
- [ ] **PLM / BOM** — feeds the product master (M2).
- [ ] **WMS** — Warehouse Management System.

See \`docs/business-domain-and-systems.md\`."

echo ""
echo "== M8 — platform ops & cost =="
issue "Live platform knowledge graph from UC lineage + DLT + AST (retire hand-authored HTML)" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:feature,priority:P1,status:ready" \
  "**Design + build a self-updating, scalable knowledge graph of the whole platform**, replacing the hand-authored \`docs/knowledge-graph.html\` (drifts whenever a column/table/metric-view/RAG component is added).

**Extract** (don't hand-author): UC system tables — \`system.access.table_lineage\` + \`system.access.column_lineage\` (table & column edges auto), \`information_schema.tables/columns/views\` (nodes incl. metric views); DLT event-log DAG; repo AST + DAB resources + SQL DDL for jobs/agents/RAG/files.
**Store:** \`graph.nodes\`/\`graph.edges\` Delta + GraphFrames (no new infra, no idle cost; mirror to Neo4j only if interactive exploration earns it). Layout derived from catalog layer + schema/tags.
**Render:** build step queries the graph → emits the existing \`N\`/\`E\` JSON → injects into the current HTML template.
**Lint (the win):** dangling = bronze node w/ no outbound lineage edge (auto-catches the 17 unread bronze tables); drift = code-named table absent from information_schema; stub = declared DLT dataset never a lineage source.
**Ship:** \`job_platform_graph\` (extract→load→render→lint), scheduled with EOD ops; incremental off lineage, designed for the full catalog as MES/PLM/WMS + OT land.

See \`docs/knowledge-graph.html\` for the target visual + node/edge schema."
issue "Ops: make the EOD crons durable (launchd, not session-only)" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:bug,priority:P1,status:ready" \
  "Both EOD routines run via **session-only Claude Code crons (7-day auto-expiry) — they do NOT survive a new session**, so they're effectively unscheduled. Move both to durable \`launchd\` jobs: (1) \`scripts/check_idle_compute.sh\` idle-compute sweep (docs \`jobs-and-pipelines.md\` §7.1); (2) the \`PROGRESS.md\` EOD commit-summary entry."
issue "Decide: D7 observability scope (ops.dq_results / SLA)" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:spike,priority:P2,status:needs-decision" \
  "**D7 is OPEN — needs your call before work starts.** \`ops.dq_results\` / SLA observability is designed but not built. Overlaps the MDM DQ-rollup issue and the agent monitoring work — decide D7 first to avoid building the same thing twice. See \`docs/decisions.md\` D7."
issue "Decide: keep or delete the idle-billing dev Vector Search endpoint" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:spike,priority:P2,status:needs-decision" \
  "Review #11. The VS endpoint is the platform's **only always-on cost** (the agent endpoint scales to zero) but retrieval needs it. Current practice: delete + recreate on demand. ⚠️ **Recreate gotcha:** deleting the endpoint orphans the index UC entity — \`index_sync\` then fails 'UC entity already exists'. Fix: \`databricks vector-search-indexes delete-index cdp_dev.contracts.contract_chunks_index\` BEFORE re-running index_sync."
issue "Audit: are any notebooks/ dashboards actually built? (Phase 5)" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:spike,priority:P3,status:needs-decision" \
  "Review #12 — the plan claims Phase 5 dashboards; unclear whether any exist. Audit \`notebooks/\` and correct the plan table either way."
issue "Snowflake port: install snow CLI + validate the connection" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:feature,priority:P3,status:ready" \
  "Account **RJTIRPC-IE97345** (SSO) is in \`~/.snowflake/connections.toml\` (unblocks the port) but the \`snow\` CLI is **not installed yet**. Plan: \`docs/snowflake-port.md\`. Direction: adopt Iceberg via **UniForm** on Snowflake-bound gold."
issue "Build a read-only Databricks MCP server over the gold products" "M8 Platform ops & cost" \
  "area:platform,domain:cross-cutting,type:feature,priority:P3,status:ready" \
  "Learning thread. **Step 1:** scaffold a Databricks MCP server over the gold products (\`revenue_pipeline\`, \`bookings_vs_billings\`), **read-only**. Then register the existing Postgres MCP server (\`/Users/vamshi/AzureAI/mcp-servers/postgresql\`), then add one write tool **behind an approval gate**. Federation for Postgres needs a stable ngrok endpoint. Brainstorm: \`docs/brainstorming/ai-agents-and-skills.md\` §3."

echo ""
echo "== M9 — advanced: ML & activation =="
issue "ML: feature store + real-time scoring (churn, CLV, next-best-action)" "M9 Advanced: ML & activation" \
  "area:ml,domain:cross-cutting,type:feature,priority:P2,status:ready" \
  "Advanced-level capability: turn the governed gold layer into an ML surface.

- [ ] **Feature store / training features** — curate reusable features off gold (customer_360, revenue, engagement) in Databricks Feature Engineering.
- [ ] **Models** — churn propensity, customer lifetime value (CLV), next-best-action.
- [ ] **Real-time scoring** — serve the models (Model Serving, scale-to-zero) for online scoring; batch scoring to gold for BI.
- [ ] Wire predictions back into the platform (e.g. \`gold.customer_scores\`) so segments/actions can consume them.

Depends on the MDM masters (M2) + a live gold layer. Pairs with the reverse-ETL issue — scores are a prime activation payload."
issue "Reverse ETL / CDP activation: push segments & attributes to Salesforce / Marketo / Ads + APIs" "M9 Advanced: ML & activation" \
  "area:ml,domain:cross-cutting,type:feature,priority:P2,status:ready" \
  "Advanced-level capability: close the loop from warehouse back to operational tools (the 'activation' half of a CDP).

- [ ] **Segments & attributes** — define reusable audience segments + computed attributes off gold (masters + ML scores from the ML issue).
- [ ] **Reverse ETL** — sync segments/attributes to Salesforce, Marketo, and Ads platforms (evaluate a tool vs. a Databricks-native push; respect the D4 PII masks on outbound fields).
- [ ] **APIs** — expose selected attributes/segments via a read API for apps.

Depends on MDM masters (M2); consumes the ML scores. ⚠️ Outbound PII must honor the D4 column-mask/ABAC policy — don't ship unmasked email/phone/tax_id to external tools."

issue "Private CEO financial copilot: local data + MCP tools + swappable model (retrieve, don't train)" "M9 Advanced: ML & activation" \
  "area:ml,domain:cross-cutting,type:spike,priority:P3,status:needs-decision" \
  "Private financial copilot for the CEO (+2 trusted people), answers stay on a local Mac. **Corrected premises:** (1) *retrieve, don't train* — fine-tuning bakes/leaks/staleness + LLMs hallucinate numbers; (2) *SQL for numbers, vector for docs* — financials are structured → text-to-SQL over local DuckDB/Postgres; a vector store alone is the wrong primary tool; (3) *local model = privacy-vs-capability tradeoff*.

**Architecture:** local structured store (DuckDB/Postgres from QuickBooks/NetSuite/ERP) + local vector store (LanceDB/Chroma) + local model (Ollama: Qwen2.5-32B / Llama-3.3-70B quantized) + **MCP server** read-only tools (\`query_financials\` text-to-SQL, \`search_documents\`, \`get_metric\`) called by Claude Desktop / a local agent. **Guardrail:** numbers ONLY from SQL results, always show query+source. FileVault + auth gate for the 2 extra users.

**Decision (needs-decision):** full-local (max privacy, weaker reasoning) vs. data-local + swappable model (recommended — local Ollama, or a zero-retention private endpoint when reasoning demands it). Relates to the read-only Databricks MCP item (shared text-to-SQL)."

echo ""
echo "== Project board =="
PROJ_JSON="$(gh project view "$PROJECT_NUMBER" --owner "$OWNER" --format json 2>/dev/null)"
if [[ -z "$PROJ_JSON" ]]; then
  echo "! Could not read project #$PROJECT_NUMBER for $OWNER. Check 'gh auth status' has the 'project' scope."
  exit 1
fi
mkfield() {
  gh project field-create "$PROJECT_NUMBER" --owner "$OWNER" \
    --name "$1" --data-type SINGLE_SELECT --single-select-options "$2" >/dev/null 2>&1 \
    && echo "field: $1" || echo "field exists: $1"
}
mkfield "Priority" "P0,P1,P2,P3"
mkfield "Area"     "mdm,rag,agent-ops,ingestion,governance,ml,platform"
mkfield "Size"     "XS,S,M,L,XL"

echo ""
echo "Adding issues to project #$PROJECT_NUMBER ..."
ADDED=0
while IFS= read -r url; do
  [[ -z "$url" ]] && continue
  if gh project item-add "$PROJECT_NUMBER" --owner "$OWNER" --url "$url" >/dev/null 2>&1; then
    ADDED=$((ADDED+1)); echo "  → $url"
  else echo "  ! could not add $url"; fi
done < "$CREATED_URLS"

echo ""
echo "Done. $ADDED issue(s) added to project #$PROJECT_NUMBER."
echo "Next: bash scripts/sync_project_fields.sh   # set Priority/Area/Status from labels"
echo "      gh project view $PROJECT_NUMBER --owner $OWNER --web"
rm -f "$EXISTING" "$CREATED_URLS"
