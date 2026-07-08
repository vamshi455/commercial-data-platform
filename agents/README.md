# AI Agents — Commercial Data Platform

A small fleet of **governed, read-only** AI agents that answer natural-language
questions over the platform's curated data products. Every agent is a thin
function-calling layer: the LLM picks a tool, the tool runs a **parameterized
SELECT against an approved Unity Catalog view**, and the result is summarized.
Agents never write data, never see raw bronze, and never see unmasked PII.

## The fleet

| Agent | Purpose | Reads (approved objects only) |
|-------|---------|-------------------------------|
| `revenue_insights` | Pipeline, bookings vs billings, forecast questions for RevOps/Finance | `gold.revenue_pipeline`, `gold.bookings_vs_billings` |
| `customer_health` | Account health, renewal/churn risk, support posture for CS/AM | `gold.customer_360`, `gold.account_health`, `gold.renewal_risk`, `gold.support_performance` |
| `data_steward` | Lineage, metadata, freshness, sensitivity for stewards/governance | `system.access.table_lineage`, `system.access.column_lineage`, `information_schema.*`, UC tags |
| `platform_ops` | Job/pipeline run health, schema drift, SLA breaches for platform eng | `system.lakeflow.*` job/run tables, DLT/pipeline event logs |
| `finance_reconciliation` | CRM-vs-ERP variance, bookings/billings/collections reconciliation | `gold.bookings_vs_billings`, `gold.collections_risk`, `silver.invoice`, `silver.payment` |
| `document_intelligence` | RAG over commercial documents (contracts, MSAs, quotes) with citations | `silver.vs_doc_chunks_index` (Vector Search; PII-masked chunks) |

## Shared guardrails

- **Identity & access**: agents run as / on behalf of members of the Unity
  Catalog group **`cdp_ai_app_users`**. UC privileges — not prompt text — are
  the real boundary: the group is granted `SELECT` on exactly the curated
  objects listed above and nothing else.
- **No raw bronze, no unmasked PII**: agents read curated **gold/silver views**
  only. PII columns are dropped or covered by UC column masks / row filters, so
  even a "clever" query cannot surface raw identifiers.
- **Read-only**: tools issue `SELECT` only. No DML/DDL surface is exposed.
- **Parameterized SQL**: tool inputs are bound as parameters, never string-
  concatenated, to prevent SQL injection and to keep query shapes auditable.
- **Auditability**: every tool call logs the agent, the user, the tool, the
  bound parameters, and the target object. Unity Catalog + `system.access`
  audit logs capture the underlying query for governance review.
- **Scope in the system prompt**: each `agent.py` defines a `SYSTEM_PROMPT`
  that states the agent's scope and refusal behavior (decline out-of-scope or
  PII requests) — defense in depth on top of UC grants.

## Architecture

These stubs illustrate the intended production pattern on Databricks:

- **Databricks Genie** spaces for conversational, governed text-to-SQL over the
  same curated gold/silver objects (no-code analyst surface).
- **Mosaic AI Agent Framework** for code-first agents: tools are registered
  functions, traced and evaluated, deployed as Model Serving endpoints.
- **Function-calling over governed SQL**: the LLM is given a typed tool schema
  (`get_tools()`); each tool runs a fixed, parameterized query via a
  `databricks-sql-connector` warehouse connection. The warehouse runs as the
  governed principal, so UC enforces access on every call.

Each agent folder has its own `README.md` (scope, example questions, exact
objects, guardrails) and an `agent.py`. The five **SQL** agents are stubs —
`run_sql()` is a placeholder and no credentials are embedded. `document_intelligence`
is a **RAG** agent whose retrieval (`retrieve()`) is **wired** to Databricks Vector
Search (lazily imported); it needs the `databricks-vector-search` connector and a
live index to run. No credentials are embedded in any agent.
