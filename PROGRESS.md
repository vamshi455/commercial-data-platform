# Progress Log

High-level, one-glance history of what got done, day by day. Newest first. For the detailed
narrative (issues hit, fixes, why) see [docs/dev-log.md](docs/dev-log.md) and
[docs/checkpoint.md](docs/checkpoint.md) (pending/resume threads). This file answers "what
happened, roughly, on day X" — not "how."

> **Routine:** update this file by EOD with a short entry for the day. See
> `docs/checkpoint.md` → "Related state" for how that's currently scheduled.

---

### 2026-07-16 — RAG bug-hunt, docs, and a cost-safety net
Root-caused and fixed 3 real correctness bugs the eval suite had never caught: `ai_parse_document`
returning a Spark `VariantVal` that was silently rendering as raw JSON instead of contract text;
counterparty names truncating on PDF line-wraps; golden-set `chunk_id`s drifting silently from
the indexed corpus. Rewrote the golden set to resolve stable `(file, seq)` refs at seed time
instead of hardcoding hashes. Documented the embedding lifecycle (`docs/embedding-lifecycle.md`)
— proved the corpus is currently **append-only**: new docs work, in-place edits and deletes fail
silently. Added the GitHub MCP server. Built and scheduled `scripts/check_idle_compute.sh` (EOD
sweep that stops idle clusters/warehouses/VS endpoints, flags non-scale-to-zero serving
endpoints). Documented it plus a full token/LLM cost breakdown for the agent
(`docs/token-optimization-cost.md`).

### 2026-07-15 — Testing criteria + Rheinhardt domain pivot
Closed all 5 tracked audit gaps from the eval-harness review: implemented PII masking (was
advertised in 5 places, implemented nowhere), unified the served agent (`model.py`) onto the same
HYBRID retrieval + system prompt as the evaluated path (`agent.py`), added acceptance-criteria
tests (`docs/agent-evals.md` §5A). Renamed the fictitious company from an oil/gas theme to
**Rheinhardt Industrial** (pumps/valves/motors) and regenerated the contract corpus to match.

### 2026-07-12 — Knowledge capture
Persisted session knowledge before context loss: agentic-actions direction, agent-memory design
(working/semantic/episodic/procedural), a 5-area maturity scorecard, and a running list of
Databricks/serverless/Vector Search gotchas. Added rich "About" descriptions to Databricks UI
objects (catalogs, jobs) so they're self-explanatory to a new viewer.

### 2026-07-11 — First agentic action goes live
Built and deployed the **collections agent**: anomaly detection → diagnosis → drafted action →
human-in-the-loop approval, the platform's first monitor→act loop (not just BI). Fixed a
serverless compute restriction (`currentRunId()` not whitelisted) and a Claude response-parsing
bug (list-of-content-blocks shape).

### 2026-07-09 — contract_intelligence RAG agent deployed and evaluated green
Stood up the formal `contract_intelligence` agent (Mosaic AI Agent Framework, `ChatAgent`,
model-from-code) and wired it into the eval harness. Fixed a string of real deployment bugs
(job-notebook import path, managed-embeddings `text_column`, `claude-sonnet-5` rejecting
`temperature`, PII detector false-positiving on contract numbers). End-to-end result: **all hard
gates green** — 0 PII leaks, 0 injections obeyed, 1.0 citation accuracy — over an 8-question
golden set.

### 2026-07-08 — contract_vector_search runs end-to-end in dev
Debugged the RAG ingestion pipeline until it ran clean: fixed a DDL primary-key syntax rejection
and a schema-inference failure on all-null metadata columns. First successful run: 5 PDFs → 11
chunks indexed, 0 parse failures. Scaffolded the agent/RAG eval harness (definitions deployed,
not yet run) and a Snowflake-port plan. Added `docs/jobs-and-pipelines.md` as the deployed-jobs
reference.

### 2026-07-07 — Project-review cleanup
Worked through a backlog of open design questions from a project review and resolved them into
a decisions log (D1–D9).

### 2026-07-06 — Domain pivot decided
Decided to reframe the platform's fictitious company from its original theme to an
industrial-equipment manufacturer, and sketched the systems roadmap (MES/PLM/WMS) that
implies.

### 2026-07-05 — Contract RAG module, MDM spec, backlog tooling
Built the first version of `contract_vector_search` (incremental PDF ingestion → Vector Search).
Brainstormed MCP-for-agents and AI-agent use cases. Wrote an MDM/governance spec (Standard scope)
and a GitHub-issue backlog-seeding script. Governance edits + CLAUDE.md guardrails; CRM cutover
work continued.

### 2026-06-29 — Governance, RBAC, ABAC masking
Account-admin access unblocked RBAC work: created 8 account groups + 5 persona test service
principals, 5 AI-facing curated views (PII-free, freshness-tagged), and live ABAC column-masking
policies (governed tag `mask`, 3 policies). Full narrative in `docs/dev-log.md`.

### 2026-06-28 — First deploy to Azure dev
Deployed the bundle to the live Azure Databricks workspace; fixed pipeline, governance
environment-guard, and CI/CD (GitHub OIDC/WIF) issues to get it running for real, not just
validating locally.

### 2026-06-26 — Scaffold
Initial commit: the Commercial Data Platform repo structure (CRM+ERP lakehouse, medallion
architecture, Asset Bundles, CI/CD skeleton).
