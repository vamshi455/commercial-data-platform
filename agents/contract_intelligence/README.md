# Agent: contract_intelligence

RAG agent that answers questions about commercial **contracts** (MSA, supply,
distributor, pricing, NDA, warranty) — retrieve → generate → cite. Part of the
unstructured/RAG track ([`docs/rag-unstructured.md`](../../docs/rag-unstructured.md))
and the target of the eval harness ([`docs/agent-evals.md`](../../docs/agent-evals.md)).

## Example questions
- "What are the termination and renewal terms in this contract?"
- "What is the effective date of the term PSA?"
- "Summarize the delivery/FOB terms."

## Approved objects (read-only)
| Object | Why |
|--------|-----|
| contract vector index (via `contract_vector_search/retriever.py`) | HYBRID search over `gold_contract_chunks`; PII-masked, `is_current=true` only |

Reads **only** through the retriever — no raw files, no unmasked PII, no
superseded contract versions.

## How it works
1. `retrieve()` — HYBRID search, current contracts only (shared `retriever.py`).
2. `answer()` — `format_context` → generate with **`databricks-claude-sonnet-5`**
   under a grounded, cite-or-refuse, ignore-injected-instructions system prompt.
3. Returns the answer + `retrieved_context` + `citations` for evals/consumers.

Pure helpers (`format_context`, `build_prompt`, `extract_cited_docs`) are
unit-tested off-cluster; retrieval + generation need a live index + served model.

## Guardrails
- Runs as `cdp_ai_app_users`; grounded-only with (document, page) citations;
  refuses when context is insufficient; ignores in-context injected instructions;
  routes metric/number questions to `revenue_insights` / `customer_health`.
- Evaluated by `job_agent_eval` — hard gates: 0 PII leaks, 0 obeyed injections,
  0 superseded-term leaks (see `docs/agent-evals.md`).
