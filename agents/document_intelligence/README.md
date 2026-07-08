# Agent: document_intelligence

Answers questions about commercial **documents** — contracts, MSAs, SOWs, quotes,
and pricing workbooks — using retrieval-augmented generation (RAG) over the
governed document vector index. Part of the unstructured / RAG track (see
[`docs/rag-unstructured.md`](../../docs/rag-unstructured.md)).

## Example questions

- "What are the termination and renewal terms in Apex's MSA?"
- "Which SOW covers the managed-services scope for this account?"
- "What discount tiers are in the latest pricing workbook?"
- "Summarize the liability cap across this customer's contracts, with citations."

## Approved objects (read-only)

| Object | Why |
|--------|-----|
| `silver.vs_doc_chunks_index` | Databricks Vector Search Delta Sync Index over `silver.doc_chunks`; chunk text is **PII-masked upstream, before embedding** |

The agent reads **only** this index. It cannot see raw files (`bronze_docs_raw_*`),
raw bytes, or unmasked text — by construction, those columns don't exist on the
index.

## Guardrails

- Runs as the Unity Catalog group **`cdp_ai_app_users`**, granted read on exactly
  this index and nothing else — UC privileges, not prompt text, are the boundary.
- **Grounded answers only**: every claim is cited as *(source document, page/sheet)*;
  if retrieval is empty the agent says so rather than guessing.
- **Customer scoping**: when a question targets a customer, retrieval is filtered
  by `master_customer_id` so only that customer's documents are returned.
- Metric/number questions are declined and routed to `revenue_insights` /
  `customer_health`.
- Every retrieval is audited (agent, user, tool, params, target index).

## Architecture

RAG via the **Mosaic AI Agent Framework**: `search_documents` calls Databricks
**Vector Search** `similarity_search` (embedding model `databricks-gte-large-en`),
returning masked chunks + citations that the LLM grounds its answer in.

Unlike the SQL agents, `retrieve()` is **wired** — it makes the real Vector Search
call via `databricks-vector-search` (lazily imported). It needs that connector and
a live index to run; the pure helpers (`build_filters`, `format_citation`,
`_parse_search_response`) are unit-tested off-cluster. Index creation is one-time
workspace setup — see [`docs/rag-unstructured.md`](../../docs/rag-unstructured.md) §6.
