# Checkpoint — resume points

Running list of parked/pending threads to pick up. Newest first.

## ⏳ PENDING

### Agent lifecycle (DEV→QA→STAGING→PROD) — gap analysis + testing criteria (2026-07-15)
Audited `contract_intelligence` against the standard agent lifecycle. **DEV + QA spine is in
place; PROD observability is absent and the eval is not a deployment gate.**

**Done this pass:** MLflow wiring in [`run_agent_eval.py`](../src/evals/run_agent_eval.py) —
`set_experiment` + `@mlflow.trace` per question + session grouping + run metrics +
`mlflow.evaluate(model_type="databricks-agent")` (built-in judges). Golden rows extracted to
pure [`golden_set.py`](../src/evals/golden_set.py) (shared by notebook + pytest). Page-aware
`citation_accuracy_paged` + `extract_citation_pairs` in `custom_judges.py`. Eval job deps
pinned (`mlflow>=3.1.3`, `databricks-agents>=1.1.0`). **8 acceptance criteria** documented in
[`agent-evals.md` §5A](agent-evals.md) and enforced off-cluster (81 passed / 6 xfail).

**Domain pivot CLOSED (2026-07-15):** company named **Rheinhardt Industrial** (GmbH; Munich).
Product catalog retired the IT-vendor residue (Edge Server/Switch/Router) → divisions **Flow**
(pumps, valves) · **Power** (motors, compressors) · **Care** (filters, lubricants, spare parts)
· Services, across `reference_data_generator` + `erp_generator` + `crm_generator` (CRM had its
own stale list — would have poisoned the product crosswalk). New
[`data_gen/contract_generator.py`](../data_gen/contract_generator.py) generates the 6-doc
contract corpus (MSA/Distributor/Supply/Pricing/NDA/Warranty-SLA) as **real PDFs from pure
stdlib** — corpus is now reproducible + version-controlled (was: hand-dropped, unauditable).
Golden set reframed → **criterion 2 closed**. `architecture.md` no longer says "IT vendor".
**Bug found + fixed:** `metadata_extract.extract_contract_type` merged filename+body into one
haystack and returned the first list-order match, so an SLA citing "Master Sales Agreement" or
an NDA citing "pricing" misclassified — the oil corpus hid it (matched nothing → always None).
Now filename-first, longest-keyword-wins, +4 regression tests.
**Contracts land in a separate Volume** (`contracts/raw_contract_files`, not `landing/files`) —
generated to `data_gen/output_contracts/` outside `${OUT}` so the landing sweep can't grab them.

**4 audit gaps still tracked as `xfail(strict=True)`** (flip to XPASS → loud CI fail when fixed):
1. `expected_chunk_ids` all empty → retrieval recall/precision/MRR **dead**. (Backfill after
   the first index_sync — chunk_ids are only knowable once the corpus is indexed.)
3. **PII masking advertised in 5 places, implemented nowhere** — expected
   `src/contract_vector_search/masking.py::mask_pii`. Pipeline would fail its own PII gate.
4. Served/eval divergence — `model.py._retrieve` has no `query_type` (pure vector) while
   `retriever.py` uses HYBRID. Prod ≠ what we score.
5. `_page_for` always returns `1` → every citation's page fabricated.

**Lifecycle gaps (priority order):**
1. **Eval not a deploy gate** — `ci.yml` runs `pytest` only; `job_agent_eval` is NOT in
   deploy-qa/prod. Promotion is not gated on eval thresholds. ← cheapest, highest value.
2. **Inference Tables OFF** — no `auto_capture` on the serving endpoint; prod prompts/
   responses/latency not logged to Delta. Prod is blind.
3. **No Lakehouse Monitoring** — nothing watches drift/quality/toxicity (needs #2 first).
4. **No HITL feedback capture** — `agents.deploy` spins up a Review App but no feedback is
   persisted or fed back into the golden set.
5. **Feedback loop not closed** — no alerting; prod failures don't route back to DEV.
6. Minor: prompts duplicated + unversioned (no MLflow Prompt Registry); no
   Champion/Challenger UC aliases for staged rollout/rollback.

**Not gaps:** UC registry, scale-to-zero serving, prod manual-approval gate, DAB-as-IaC
(Terraform equivalent), LLM-judge + deterministic gates, MLflow tracing.
**Over-engineering note (same audit):** custom 154-line chunker reimplements a shipped lib;
SCD amendment/versioning likely never fires; streaming bronze for ~11 chunks / 5 PDFs.
See also: `agent-evals.md`, plan at `~/.claude/plans/lets-go-to-plan-soft-cat.md`.

### Agentic actions (beyond BI) — collections agent LIVE & GREEN (2026-07-10)
Flagship monitor→diagnose→draft→HITL→learn loop working in dev. `job_collections_agent`
(ddl→seed→run): scans `gold.collections_risk` → detects actionable (rules) → LLM
(claude-sonnet-5) diagnoses + drafts (dunning email / CSM escalation) → writes proposals
to `ops.action_queue` (status=pending). 8 accts → 5 proposals, priority-routed, genuine
"oversight vs distress" reasoning. Human approves in `notebooks/agentic_actions/review_queue.sql`
→ `ops.action_feedback` (learning signal). **Shared infra** (action_queue + action_feedback)
is reused by the portfolio (revenue-leakage/churn/pipeline) + the MDM steward app. No serving
endpoint → zero standing cost. Bugs fixed: serverless `currentRunId()` not whitelisted (→ uuid
+ `{{job.run_id}}`); Claude returns `content` as list-of-blocks (→ `_content_text`). Synthetic
`collections_risk` seed for now — swap to real gold after D6. Polish: 1/5 LLM JSON miss (lenient
fallback caught it) — tighten with structured outputs.
**PII decision (2026-07-10):** DON'T build a scanner — **UC Data Classification + ABAC are GA**
(agentic auto-tag + review UI). Re-aim the custom steward app at **MDM/entity stewardship**
(the Tamr-shaped gap), reusing action_queue/feedback. Federation for Postgres: pending stable
ngrok endpoint. Iceberg: adopt via **UniForm** on Snowflake-bound gold (multi-engine).

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

### contract_intelligence agent — DEPLOYED via Mosaic AI (2026-07-09)
Logged + registered + served through the Agent Framework, so it now appears in
**Models / Serving / Experiments**. `agents/contract_intelligence/model.py`
(mlflow ChatAgent) → `notebooks/agents/deploy_contract_agent.py`
(`job_deploy_contract_agent`): log-from-code + resources (VS index + gen
endpoint) → UC model `cdp_dev.contracts.contract_intelligence` v1 →
`agents.deploy(scale_to_zero=True)` → serving endpoint
`agents_cdp_dev-contracts-contract_intelligence`. Agent endpoint scales to zero
(≈no idle cost); the always-on cost is the VS endpoint (needed for retrieval).
⚠️ **Recreate gotcha:** deleting a VS endpoint ORPHANS the index UC entity —
`index_sync` then fails "UC entity … already exists" while get-index says
missing. Fix: `databricks vector-search-indexes delete-index
cdp_dev.contracts.contract_chunks_index` BEFORE re-running index_sync.

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
