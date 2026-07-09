# Checkpoint — resume points

Running list of parked/pending threads to pick up. Newest first.

## ⏳ PENDING

### Project-review decisions (2026-07-04) — see [decisions.md](decisions.md)
Answered 9 review doubts. **Done:** CI/CD qa+prod disabled, oil→manufacturing scrub,
plan-table status refresh, docs corrected (naming drift note, CRM account fields
marked planned). **Tracked refactors:** D2 rename deployed `<layer>.<layer>_*` tables
to clean form (needs redeploy), D5 fix `_common.py` inlining (wheel/%run), D6 finish
CRM cutover (top priority — critical source), D4 activate gold PII masks/ABAC per
persona. **Open:** D7 observability scope, keep/delete idle VS endpoint, dashboards status.

### Domain pivot → industrial-equipment manufacturer — added 2026-07-04
Retired oil & gas/trading framing; platform now mimics a **B2B industrial-equipment
manufacturer**. Systems roadmap + what stays/changes/goes in
[business-domain-and-systems.md](business-domain-and-systems.md).
**Follow-ups:**
- Reframe `contract_vector_search`: type keywords (MSA/distributor/pricing/supply/NDA/
  warranty) + sample docs + tests (currently oil-trade types). Retire oil mentions in
  architecture.md, observability.md, contract spec, metadata_extract.py, brainstorming.
- Add synthetic generators + bronze ingestion for new systems, P0 first: **MES, PLM/BOM, WMS**.

### MDM / Data Catalog / Governance (Standard scope) — added 2026-07-04
Authoritative masters for customer/product/supplier + survivorship + crosswalk +
DQ scorecards; add missing source fields to generators/ingestion. Spec:
[specs/mdm-and-governance.md](specs/mdm-and-governance.md). Backlog (13 issues,
4 milestones, prioritized) is scripted in `scripts/seed_github_backlog.sh`.
**BLOCKED on one manual step:** run `gh auth login` (repo scope). Then run the
seed script (or ask me to) to create the GitHub Issues/Projects backlog. After
that, async execution = a routine picks the top `status:ready` issue → PR.

### MCP tools for agents (learning curve) — added 2026-07-04
Build & maintain agents that access MCP tools, in a sales-enterprise context.
Full brainstorm: [brainstorming/ai-agents-and-skills.md](brainstorming/ai-agents-and-skills.md) §3.
**Resume at:** spec + scaffold **step 1 — a Databricks MCP server over the gold
products** (`revenue_pipeline`, `bookings_vs_billings`, etc.), read-only tools.
Then: register the existing Postgres MCP server (`/Users/vamshi/AzureAI/mcp-servers/postgresql`),
then add one write-capable tool behind an approval gate.
_"will continue on this in short time."_

### contract RAG + eval loop — CLOSED & GREEN in dev (2026-07-09)
Full agent+eval loop ran end-to-end and PASSED. `contract_intelligence` agent
(retriever.py → `databricks-claude-sonnet-5`, grounded+cited) evaluated by
`job_agent_eval` over an 8-question golden set → **all hard gates pass: PII
leaks=0, injections obeyed=0, citation=1.0**; injection (BANANA47) refused,
out-of-scope declined, counterparty-email PII refused, unanswerable refused.
Results in `cdp_dev.ops.eval_results`. Bugs fixed this session (all on main):
run_agent_eval import via `source_root=${workspace.file_path}`; retriever drop
`text_column` (managed-embeddings index); agent drop `temperature`
(claude-sonnet-5 rejects it); PII detector no longer flags contract numbers as
phones (10-15 digit rule). Endpoint recreated → index_sync (11 rows) → eval →
**endpoint DELETED again** (bounded cost). Follow-up: golden set
`expected_chunk_ids` empty → retrieval recall/precision/MRR still unscored.

### contract_vector_search — RAN successfully in dev (2026-07-08)
Full job ran end-to-end in dev: 5 contract PDFs → **11 chunks indexed** (bronze 5
files → silver/gold 11 chunks → `contract_chunks_index`, 0 parse failures).
Fixed 2 runtime bugs (committed to main): **ddl** inline PK (Databricks rejects
`ADD CONSTRAINT IF NOT EXISTS`); **silver** explicit `createDataFrame` schemas
(all-None metadata inferred NullType → `CANNOT_DETERMINE_TYPE`).
⚠️ **VS endpoint `cdp_contracts_vs` DELETED to stop always-on cost.** Gold table
+ chunks are intact. To restore retrieval: recreate the endpoint
(`databricks vector-search-endpoints create-endpoint --name cdp_contracts_vs --endpoint-type STANDARD`)
then `databricks bundle run job_contract_vector_search -t dev --only index_sync`
(re-embeds existing gold; no re-parsing).
⚠️ Sample docs are still oil-themed (metadata reads oil-trade) — reframe to
industrial-equipment pending. Spec: [specs/contract-vector-search.md](specs/contract-vector-search.md).

### Authentic source-table names in bronze — added 2026-07-07 — 🔽 VERY LOW PRIORITY
Backlog idea: rename bronze tables from `crm_*`/`erp_*` to real source-system names
(Salesforce `sfdc_account`/`sfdc_opportunity`/…, SAP `sap_kna1`/`sap_vbak`/`sap_vbrk`/
`sap_acdoca`/…) so bronze mirrors true sources; silver/gold stay clean (conform-the-mess
realism). Decided **authentic bronze, clean silver** direction, then parked. Full
mapping + scope (autoloaders, silver read-refs, naming-conventions §4.1/§9, source-systems,
data-contracts) is in the 2026-07-07 chat. Natural moment to also fix D2 redundant-prefix
drift. Low-risk (dev CRM bronze already dropped mid-cutover). Do NOT prioritize over D6
CRM cutover or the MES/PLM/WMS generators.

## Related state
- QA + PROD Databricks workspaces deleted 2026-07-04 (NAT-gateway cost cut).
- Git: main-only workflow (commit/push straight to main).
