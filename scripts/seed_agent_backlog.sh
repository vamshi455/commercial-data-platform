#!/usr/bin/env bash
# =============================================================================
# scripts/seed_agent_backlog.sh
# -----------------------------------------------------------------------------
# Seeds the AGENT LIFECYCLE backlog into GitHub Issues: labels, milestones, and
# the prioritized issues from the 2026-07-15 agent-lifecycle audit
# (docs/checkpoint.md "Agent lifecycle (DEV->QA->STAGING->PROD)") plus the
# unstructured-content + test-scenario asks.
#
# Companion to scripts/seed_github_backlog.sh (MDM/Governance backlog) — same
# conventions, separate milestones so the two tracks don't collide.
#
# One-time prerequisite:  gh auth login     (needs 'repo' scope)
# Run:  bash scripts/seed_agent_backlog.sh
# Idempotent-ish: label/milestone creation tolerates "already exists".
# =============================================================================
set -uo pipefail

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Seeding agent backlog into $REPO"

# ---- Labels ----------------------------------------------------------------
mklabel() { gh label create "$1" --color "$2" --description "$3" 2>/dev/null \
            || gh label edit "$1" --color "$2" --description "$3" 2>/dev/null || true; }
mklabel "domain:agent"        "8b5cf6" "AI agent / RAG"
mklabel "domain:unstructured" "0e8a16" "Unstructured docs / vector search"
mklabel "type:agent"          "8b5cf6" "Agent logic / framework"
mklabel "type:eval"           "1d76db" "Evaluation harness / golden set"
mklabel "type:observability"  "006b75" "Inference tables / monitoring / alerting"
mklabel "type:testing"        "c2e0c6" "Test scenarios / QA"
mklabel "type:security"       "b60205" "PII / injection / guardrails"
mklabel "type:cicd"           "0052cc" "CI/CD / promotion gating"
mklabel "type:techdebt"       "999999" "Simplification / over-engineering cleanup"
mklabel "priority:P0"         "b60205" "Must-have, foundational"
mklabel "priority:P1"         "d93f0b" "High"
mklabel "priority:P2"         "fbca04" "Medium"
mklabel "status:ready"        "0e8a16" "Groomed & ready for pickup (async execution)"
mklabel "status:blocked"      "e11d21" "Blocked"

# ---- Milestones ------------------------------------------------------------
mkms() { gh api "repos/$REPO/milestones" -f title="$1" -f description="$2" >/dev/null 2>&1 \
         && echo "milestone: $1" || echo "milestone exists: $1"; }
mkms "A1 Agent correctness & safety"   "Close the 5 xfail audit gaps: PII masking, retrieval parity, page numbers, ground truth, domain"
mkms "A2 Unstructured content & domain" "Replace oil&gas corpus with manufacturing docs; reframe + grow the golden set"
mkms "A3 Lifecycle gating"             "Eval as a deploy gate, prompt versioning, model aliases"
mkms "A4 PROD observability & HITL"    "Inference tables, Lakehouse Monitoring, Review App feedback, closed feedback loop"
mkms "A5 Agent capability & governance" "Full-featured agent + Databricks AI Gateway governance"
mkms "A6 Behavioral test scenarios"    "High-level agent behavior tests (distinct from evals) + E2E freshness"

# ---- Issues ----------------------------------------------------------------
# issue <title> <milestone> <labels-csv> <body>
issue() {
  local title="$1" ms="$2" labels="$3" body="$4"
  gh issue create --repo "$REPO" --title "$title" --milestone "$ms" \
    --label "$labels" --body "$body" >/dev/null \
    && echo "  + $title" || echo "  ! failed: $title"
}

# ---------------------------------------------------------------------------
# A1 — Agent correctness & safety (the 5 xfail gaps from the audit)
# ---------------------------------------------------------------------------
issue "Agent: implement PII masking in silver (advertised but ABSENT)" "A1 Agent correctness & safety" \
  "domain:unstructured,type:security,priority:P0,status:ready" \
  "**Critical.** PII masking is asserted in 5 places (module README, job description, BOTH agent system prompts, and the \`safety-pii\` golden row) but **no masking code exists** — \`grep -riE 'pii|mask|redact' src/contract_vector_search/\` returns zero hits. The pipeline would leak real PII and **fail its own hard gate**.

**Do:** implement \`src/contract_vector_search/masking.py::mask_pii(text) -> str\` (emails -> \`[EMAIL]\`, phones -> \`[PHONE]\`), call it in \`02_silver_parse_chunk.py\` **before** chunk_text is written (so masking happens pre-embedding), keep it pure for off-cluster tests.

**Done when:** \`tests/pipeline_validation/test_pii_masking.py\` passes and its \`xfail(strict=True)\` markers are removed. Criterion 3 in docs/agent-evals.md §5A."

issue "Agent: unify served retrieval onto the shared HYBRID retriever" "A1 Agent correctness & safety" \
  "domain:agent,type:agent,priority:P0,status:ready" \
  "**Served agent diverges from what we evaluate.** \`agents/contract_intelligence/model.py:_retrieve\` calls \`similarity_search(...)\` with **no \`query_type\`** (= pure vector), while \`src/contract_vector_search/retriever.py:50\` uses \`query_type=\"HYBRID\"\`. Eval scores one code path, production serves another.

Also duplicated across agent.py/model.py: \`format_context\`, the citation regex, the retrieve column list, and the SYSTEM_PROMPT (which has already **drifted** — long form vs condensed).

**Do:** make model.py reuse the shared retriever (or at minimum pass HYBRID + is_current + same columns); de-duplicate the prompt/helpers to one source of truth.

**Done when:** \`tests/pipeline_validation/test_agent_retrieval_parity.py::test_served_retrieval_is_hybrid\` passes, xfail removed. Criterion 4."

issue "Agent: real page extraction (_page_for is a stub returning 1)" "A1 Agent correctness & safety" \
  "domain:unstructured,type:agent,priority:P1,status:ready" \
  "\`_page_for\` in \`src/contract_vector_search/02_silver_parse_chunk.py:48-50\` **always returns 1**, yet \`page_number\` propagates to gold, the index, and **every agent citation**. All '(document, p1)' citations are fabricated — citation accuracy is fiction.

**Do:** extract real page numbers from \`ai_parse_document()\` output and map chunk -> page.

**Done when:** \`tests/test_contract_vector_search.py::test_page_for_is_not_a_constant_stub\` passes (xfail removed) and \`citation_accuracy_paged\` scores meaningfully. Criterion 5."

issue "Eval: backfill expected_chunk_ids (retrieval metrics are dead)" "A1 Agent correctness & safety" \
  "domain:agent,type:eval,priority:P0,status:ready" \
  "Every \`expected_chunk_ids\` in \`src/evals/golden_set.py\` is \`[]\`, so \`retrieval_scores()\` returns \`None\` and **recall@5 / precision@5 / MRR are unscored for every question** (custom_judges.py:89-90).

**Do:** for each retrieval/groundedness row, identify the chunk(s) that actually contain the answer and record their \`chunk_id\`. Cheapest path: generate the Q&A synthetically **from** a known chunk so the ground-truth id is known before the question exists (docs/agent-evals.md §3).

**Done when:** \`test_eval_dataset_contract.py::test_retrieval_rows_have_ground_truth_chunk_ids\` passes, xfail removed. Criterion 1."

# ---------------------------------------------------------------------------
# A2 — Unstructured content & domain
# ---------------------------------------------------------------------------
issue "Unstructured: remove oil & gas PDFs, ingest manufacturing contracts" "A2 Unstructured content & domain" \
  "domain:unstructured,type:ingestion,priority:P0,status:ready" \
  "The embedded corpus is still **oil & gas / trading themed** (spot purchase, FOB cargo, term PSA, multi-grade term deals) while the platform is a **B2B industrial-equipment manufacturer** and the pipeline taxonomy (\`metadata_extract._TYPE_KEYWORDS\`) is already industrial (MSA, Distributor, Reseller, Pricing, Supply, NDA, Warranty/SLA). Half-completed migration.

**Do:**
1. Purge oil/gas PDFs from \`/Volumes/<catalog>/contracts/raw_contract_files/\`.
2. Create manufacturing-domain contract PDFs: master sales agreements, distributor/reseller agreements, pricing agreements, supplier procurement contracts, NDAs, warranty/SLA.
3. Re-run \`job_contract_vector_search\` (bronze -> silver -> gold -> index_sync).
4. **Make the corpus reproducible** — today no PDF is version-controlled and no generator produces them, so the indexed corpus cannot be audited or rebuilt from the repo. Add a generator or commit the source docs.

Also fix the oil-flavored fixture text in \`tests/test_contract_vector_search.py\` (\"crude oil\").

**Related:** blocks the golden-set reframe. See docs/business-domain-and-systems.md."

issue "Eval: reframe + grow the golden set to the industrial domain" "A2 Unstructured content & domain" \
  "domain:agent,type:eval,priority:P0,status:ready" \
  "\`src/evals/golden_set.py\` has **8 rows, all oil/trading-themed** — they reference no contract type in the industrial taxonomy, so a \`contract_type\` filter could never match them.

**Do:**
1. Reframe questions to MSA / distributor / pricing / supply / NDA / warranty.
2. Grow to ~30-50 rows (docs/agent-evals.md §3 target): synthetic Q&A from chunks -> SME review -> hand-authored adversarial/edge cases.
3. Keep the safety lane (scope/injection/PII/empty).

**Depends on:** the manufacturing corpus landing first.
**Done when:** \`test_eval_dataset_contract.py::test_content_rows_reference_known_contract_type\` passes, xfail removed. Criterion 2."

# ---------------------------------------------------------------------------
# A3 — Lifecycle gating
# ---------------------------------------------------------------------------
issue "CI/CD: wire job_agent_eval as a BLOCKING deploy gate" "A3 Lifecycle gating" \
  "domain:agent,type:cicd,priority:P0,status:ready" \
  "**Highest-leverage lifecycle gap.** The standard lifecycle says promotion to PROD requires passing automated QA thresholds — but \`.github/workflows/ci.yml\` runs \`pytest\` only. \`job_agent_eval\` is **not** in deploy-qa/deploy-prod, so the LLM-judge scores and hard gates **never block a release**. The gate exists; it just isn't in the promotion path.

**Do:** add a step to deploy-qa (then deploy-prod) that runs \`databricks bundle run job_agent_eval\` and fails the deploy on a hard-gate breach (the notebook already \`raise SystemExit\`s on PII/injection). Start advisory (report-only), then enforce.

**Note:** running the eval needs the VS endpoint online — factor the recreate -> run -> delete cost pattern (docs/databricks-gotchas.md)."

issue "Agent: single source of truth for the system prompt + version it" "A3 Lifecycle gating" \
  "domain:agent,type:agent,priority:P1,status:ready" \
  "The system prompt is hardcoded in **two places that have already diverged**: \`agent.py:22-38\` (long form) vs \`model.py:32-40\` (condensed). So the eval scores one prompt and production serves a different one — a live correctness bug, not just duplication.

**Do:**
1. Extract to one shared constant consumed by both forms.
2. Register in the **MLflow Prompt Registry** so each tweak is versioned, runs link to a prompt version, and you can roll back / A-B two prompts.

**Why:** the prompt is the highest-leverage, most-changed artifact; without versioning you can't answer 'which prompt produced last week's score?'"

issue "Deploy: adopt Champion/Challenger UC model aliases" "A3 Lifecycle gating" \
  "domain:agent,type:cicd,priority:P2,status:ready" \
  "Promotion today is per-catalog with no alias-based rollout. Adopt UC model aliases (\`@Champion\` live vs \`@Challenger\` candidate) so promotion = moving an alias and rollback is instant. Serving reads the alias rather than a pinned version."

issue "Docs/UI: populate the agent's description (AI Gateway shows it empty)" "A3 Lifecycle gating" \
  "domain:agent,type:agent,priority:P2,status:ready" \
  "\`agents_cdp_dev-contracts-contract_intelligence\` shows an empty Description under Serving / AI Gateway. It's inherited from the UC registered model's \`comment\`, which \`notebooks/agents/deploy_contract_agent.py\` never sets.

**Do:** set the comment on \`cdp_dev.contracts.contract_intelligence\` AND bake it into the deploy notebook so it survives the next \`agents.deploy()\` (otherwise it's wiped on redeploy). Follow the rich 'About' metadata pattern from commit e6bc64d."

# ---------------------------------------------------------------------------
# A4 — PROD observability & HITL
# ---------------------------------------------------------------------------
issue "Observability: enable Inference Tables on the agent serving endpoint" "A4 PROD observability & HITL" \
  "domain:agent,type:observability,priority:P0,status:ready" \
  "**PROD is blind.** No \`auto_capture\` / inference table is enabled, so user prompts, agent responses, tool calls, and latency are **not logged to Delta**. Nothing to monitor, nothing to learn from, no failure cases to harvest.

**Do:** enable inference tables on \`agents_cdp_dev-contracts-contract_intelligence\` (endpoint config) so prod traffic lands in a Delta table. Blocks Lakehouse Monitoring and the feedback loop.

**Cost note:** endpoint is scale-to-zero; inference tables only write when there's traffic."

issue "Observability: Lakehouse Monitoring over the inference table" "A4 PROD observability & HITL" \
  "domain:agent,type:observability,priority:P1,status:blocked" \
  "Once inference tables exist, create a Lakehouse Monitor over them to detect **data drift, quality degradation, and toxicity spikes** over time, with alert thresholds.

**Blocked by:** Inference Tables must be enabled first."

issue "HITL: capture Review App feedback and feed it into the golden set" "A4 PROD observability & HITL" \
  "domain:agent,type:eval,priority:P1,status:ready" \
  "\`agents.deploy()\` **already provisions a Databricks Review App** (\`deploy_contract_agent.py:77\` prints the URL) — SMEs can chat with the agent and leave thumbs up/down + comments. What's missing is **process, not code**: nobody has access, and no feedback is persisted or consumed.

**Do:**
1. Grant SMEs access (\`agents.set_permissions\`) and share the URL.
2. Persist the feedback/assessments.
3. Route corrections into \`golden_set.py\` — human labeling is the trustworthiness gate (docs/agent-evals.md §3).

**Note:** distinct from the collections agent's notebook HITL (\`review_queue.sql\` -> \`ops.action_feedback\`), which approves *actions*; this collects feedback on *answers*."

issue "Observability: close the feedback loop (alerts -> DEV)" "A4 PROD observability & HITL" \
  "domain:agent,type:observability,priority:P2,status:blocked" \
  "Nothing routes production failures back to development — the lifecycle cycle doesn't close.

**Do:** alert on negative feedback / gate breaches in prod; auto-append failure cases to the golden set and open a dev issue so the next iteration fixes them.

**Blocked by:** inference tables + HITL feedback capture."

# ---------------------------------------------------------------------------
# A5 — Agent capability & governance
# ---------------------------------------------------------------------------
issue "Agent: build a full-featured agent governed by Databricks AI Gateway" "A5 Agent capability & governance" \
  "domain:agent,type:agent,priority:P1,status:ready" \
  "Today \`contract_intelligence\` is a single-hop RAG agent (retrieve -> generate -> cite). Build up to a genuinely capable, **properly governed** agent.

**Capability:** multi-tool (vector search + SQL/Genie + structured lookups), routing across agents (contract vs revenue_insights vs customer_health), multi-turn memory, multi-hop reasoning, structured outputs, streaming.

**Governance via AI Gateway** — the point of this issue:
- Rate limiting + usage tracking per consumer
- **Guardrails** (PII detection, toxicity, topic restriction) enforced at the gateway, not just the prompt
- Payload logging / inference tables
- Fallbacks + traffic splitting across models
- Cost attribution per endpoint

**Why gateway-level:** prompt-level rules are advisory — a model can ignore them. Gateway guardrails are enforced outside the model. Pairs with the (currently missing) pipeline-level PII masking."

# ---------------------------------------------------------------------------
# A6 — Behavioral test scenarios (NOT evals)
# ---------------------------------------------------------------------------
issue "Testing: high-level agent BEHAVIOR scenarios (distinct from evals)" "A6 Behavioral test scenarios" \
  "domain:agent,type:testing,priority:P1,status:ready" \
  "We have evals (scored answer quality) and unit tests (scorer correctness). **Missing: high-level behavioral scenarios** — how the agent should *behave*, expressed as acceptance scenarios rather than scored metrics.

**Do:** author a scenario spec (docs) + executable checks covering, e.g.:
- Asked a contract question -> retrieves, answers, cites (document, page).
- Asked a metrics question -> **declines and routes** to revenue_insights/customer_health.
- Context insufficient -> says 'I don't know', never guesses.
- Injected instruction inside a document -> ignored.
- Asked for PII -> returns masked form only.
- Superseded contract -> **never** returns stale terms (\`is_current=false\`).
- Multi-turn: follow-up question keeps prior context.
- Empty/ambiguous/typo'd query -> graceful behavior.
- Unauthorized object -> refuses (UC grant is the real test).

**Difference from evals:** evals score *how good* an answer is (thresholded, fuzzy); these assert *what the agent does* (pass/fail, deterministic where possible). See docs/agent-evals.md §2D/§4."

issue "Testing: E2E — modified PDF re-embeds and the agent reflects it" "A6 Behavioral test scenarios" \
  "domain:unstructured,type:testing,priority:P1,status:ready" \
  "**Freshness / amendment E2E — currently untested end to end.** Prove that editing a source document flows all the way through to the agent's answer.

**Scenario:**
1. Land a contract PDF -> run \`job_contract_vector_search\` -> ask the agent a question -> record the answer + cited chunk.
2. **Modify** the PDF (change a term, e.g. termination notice 30 -> 60 days) and re-land it.
3. Re-run the pipeline (bronze -> silver -> gold MERGE -> index_sync).
4. Ask the **same** question -> the agent must return the **new** value, cite the new version, and **must not** surface the superseded term.

**What this exercises (nothing else does):** Auto Loader incremental pickup, deterministic \`chunk_id\` re-MERGE, the amendment/\`is_current\` retire-then-merge path in \`03_gold_merge.py\` + \`versioning.detect_amendments\`, TRIGGERED Delta Sync freshness, and the retriever's \`is_current=true\` filter. The SCD versioning layer is currently **speculative — likely never fires in practice**; this test is what would prove it works or prove it's dead weight.

**Ties to:** the 'Amendment correctness' governance gate (0 superseded-term leaks) in docs/agent-evals.md §2D."

# ---------------------------------------------------------------------------
# Tech debt (from the same audit) — track, decide later
# ---------------------------------------------------------------------------
issue "Tech debt: over-engineering review of contract_vector_search" "A6 Behavioral test scenarios" \
  "domain:unstructured,type:techdebt,priority:P2,status:ready" \
  "The audit found the module is heavy for its data volume (**11 chunks from 5 PDFs**). Track and decide (do NOT rewrite blindly):

- **Custom chunker** — \`chunking.py\` is 154 hand-maintained lines reimplementing LangChain's \`RecursiveCharacterTextSplitter\`, which the repo **already depends on**; the delta is ~5 contract-keyword separators. Clearest gold-plating.
- **SCD amendment/versioning** — \`03_gold_merge.py\` + \`versioning.py\` implement full retire-then-merge supersession; the amendment path likely **never fires** for one-off PDFs. (The E2E test above decides this: prove it works, or drop it.)
- **Streaming bronze** — Auto Loader + checkpoints to pick up a handful of PDFs; a batch \`binaryFile\` read would do.
- **4-stage medallion** — bronze exists mainly to hold bytes for a checkpoint you don't need at this volume; dead-letter (real value) could hang off a simpler flow.
- **Always-on cost** — a STANDARD Vector Search endpoint bills continuously for ~11 chunks (open decision #11 in docs/decisions.md).

**Recommendation:** don't rewrite for its own sake — fix correctness first (A1), then revisit."

echo
echo "Done. View: gh issue list --repo $REPO --label status:ready"
echo "By milestone: gh issue list --repo $REPO --milestone 'A1 Agent correctness & safety'"
