# Checkpoint — resume points

Running list of parked/pending threads to pick up. Newest first.

## ⏳ PENDING

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

### contract_vector_search — built, NOT yet run
Module complete + tested + bundle-validated; dev VS endpoint `cdp_contracts_vs`
is ONLINE (⚠️ always-on billed). To run: move the 5 contract PDFs from
`cdp_dev.bronze.test/input/` → `/Volumes/cdp_dev/contracts/raw_contract_files/`,
then `databricks bundle run job_contract_vector_search -t dev` (needs compute).
Spec: [specs/contract-vector-search.md](specs/contract-vector-search.md).

## Related state
- QA + PROD Databricks workspaces deleted 2026-07-04 (NAT-gateway cost cut).
- Git: main-only workflow (commit/push straight to main).
