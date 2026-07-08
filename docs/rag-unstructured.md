# RAG / Unstructured Track — PDF & Excel → Embeddings → Vector Search

> **Audience:** Platform + AI engineers extending the Commercial Data Platform (CDP) with an
> unstructured-document ingestion + retrieval path.
> **Status:** **Design + spike** (this document is the design; `src/pipelines/ingestion/
> unstructured_autoloader.py` and `src/pipelines/silver/document_chunking.py` are the thin
> spike). Not yet production-hardened.
>
> **Related:** [`architecture.md`](./architecture.md) (structured medallion), [`governance.md`](./governance.md)
> (masking, agent access), [`agents.md`](./agents.md) (agent guardrails).

---

## 1. Why this track exists

The structured CDP unifies CRM + ERP **rows**. But a lot of commercial context lives in
**documents** — signed contracts (PDF), pricing/quote workbooks (Excel), MSAs, SOWs, support
attachments. Analysts and agents can't answer "what are the termination terms for Apex's MSA?"
from tables alone.

This track adds an **unstructured lane** that lands PDF/Excel, extracts + chunks their text,
embeds it, and serves it through a **UC-governed vector index** that the existing CDP agents
query via retrieval-augmented generation (RAG) — **without** ever exposing raw files or PII to
the model.

It reuses everything the platform already has: the same **ADLS Gen2 landing Volume**, the same
**medallion layers**, the same **Auto Loader** ingestion engine, the same **PII masking**, and
the same **agents-consume-governed-surfaces-only** principle.

---

## 2. Where it fits the medallion

```
 landing/unstructured/{pdf,excel}/dt=YYYY-MM-DD/*.{pdf,xlsx}     (ADLS Gen2 UC Volume)
        │  Auto Loader  (cloudFiles, format=binaryFile — streaming, incremental, exactly-once)
        ▼
 BRONZE   bronze_docs_raw        one row per file: content (binary), path, length, modTime + audit
        │  parse: PDF → text/tables · Excel → sheet text     (ai_parse_document OR pandas_udf)
        ▼
 BRONZE   bronze_docs_parsed     one row per (file, page/sheet): extracted_text + doc metadata
        │  chunk (token window + overlap) · attach metadata · MASK PII on chunk text
        ▼
 SILVER   silver_doc_chunks      one row per chunk: chunk_id, doc_id, page, text (masked), embeddable
        │  Databricks Vector Search — Delta Sync Index (auto-embeds via model endpoint)
        ▼
 SERVE    vs_doc_chunks_index    UC-governed vector index (databricks-gte-large-en embeddings)
        │  similarity_search(top_k)  ← agents only; cdp_ai_app_users; no bronze / no raw file access
        ▼
 AI AGENT  RAG answer with citations (doc name + page)   ← extends existing agents/ stubs
```

**Design rule (unchanged from the structured platform):** the model/agent only ever sees the
**governed serving surface** (`vs_doc_chunks_index` + the masked `silver_doc_chunks`). It never
reads `bronze_docs_raw` (raw bytes) or unmasked text.

---

## 3. Layer-by-layer design

### 3.1 Landing
- New sub-tree in the **existing** landing Volume: `<landing>/unstructured/pdf/…` and
  `<landing>/unstructured/excel/…`, partitioned `dt=YYYY-MM-DD/` like the structured feeds.
- Files are immutable and replayable — same guarantee as the rest of landing.

### 3.2 Bronze — raw capture (`bronze_docs_raw`)
- Auto Loader with `cloudFiles.format = binaryFile` streams **one row per file**:
  `path`, `modificationTime`, `length`, `content` (binary) + standard audit columns
  (`_ingested_at`, `_source_file`, `_batch_id`, `_source_system='docs'`).
- `pipelines.reset.allowed=false` protects raw history from full refresh.
- **Why binaryFile, not text:** PDFs/XLSX are binary; we capture bytes faithfully in bronze and
  defer parsing to a separate step, so a parser change never requires re-landing files.

### 3.3 Bronze — parse (`bronze_docs_parsed`)
One row per **logical unit** (PDF page / Excel sheet), carrying `doc_id`, `page_or_sheet`,
`extracted_text`, `doc_type`, `source_path`. Two extraction options:

| Option | PDF | Excel | Trade-off |
|---|---|---|---|
| **A. Managed** (recommended once GA in-region) | `ai_parse_document()` built-in | (n/a — use B) | No deps, layout-aware, but Azure-region/runtime availability varies |
| **B. Library** (spike default) | `pymupdf`/`fitz` in a `pandas_udf` | `openpyxl`/`pandas` in a `pandas_udf` | Works anywhere; pipeline must declare the pip deps |

The spike ships **Option B** (portable) with `ai_parse_document` documented as the drop-in
upgrade. Parsing failures don't fail the batch — the row is kept with `extracted_text=NULL` and a
`parse_error`, and surfaced as a soft DQ expectation.

### 3.4 Silver — chunk + mask (`silver_doc_chunks`)
- **Chunking:** token-approximate sliding window (default **~800 tokens, 100 overlap**) so a
  chunk is retrieval-sized and self-contained. Implemented as a **pure Python function**
  (`chunk_text()`) so it's unit-testable off-cluster (see `tests/`).
- **Stable IDs:** `chunk_id = sha2(doc_id || chunk_index)` (reuses the platform's `surrogate_key`
  convention) so re-runs are idempotent and the vector index syncs deterministically.
- **Metadata:** `doc_id`, `doc_type`, `source_path`, `page_or_sheet`, `chunk_index`, and —
  where a document is customer-associated — `master_customer_id` (via filename convention now;
  content-based entity linking is a later enhancement). This lets retrieval be **filtered by
  customer**, so an agent answering about Apex only retrieves Apex's documents.
- **PII masking:** chunk text passes through the **same masking** used for CRM/ERP free-text
  (see `governance/masking_functions.sql`) **before** it's embedded. The prod-strict env guard
  (`gold.is_prod`) applies — enforce in prod, relax on synthetic dev/qa.

### 3.5 Serve — Databricks Vector Search (`vs_doc_chunks_index`)
- A **Delta Sync Index** over `silver_doc_chunks`: Vector Search watches the Delta table (CDF)
  and **auto-computes embeddings** via a model-serving endpoint — we don't manage an embedding
  job. Embedding model: **`databricks-gte-large-en`** (Foundation Model API; swap-able).
- The index is a **UC securable** — same RBAC/lineage/tags as every other object. Grant
  `SELECT`-equivalent only to `cdp_ai_app_users`.
- Retrieval is `similarity_search(query_text, columns=[text, doc_type, source_path,
  page_or_sheet, master_customer_id], num_results=k, filters={...})`.

### 3.6 AI Agent — RAG
Extends the existing `agents/` stubs (which today only do structured SQL). A doc-aware agent:
1. Optionally resolves the customer → `master_customer_id` (reuse existing identity resolution).
2. `similarity_search` on `vs_doc_chunks_index` filtered by that customer, `k≈5`.
3. Composes an answer **grounded in retrieved chunks**, citing `doc name + page`.
4. Never fabricates; if retrieval is empty it says so. Same guardrails as `revenue_insights`.

---

## 4. The one real decision: which vector store

**Recommendation: Databricks Vector Search (native).** Rationale:

| | **Databricks Vector Search** (recommended) | External (Pinecone / Chroma / pgvector) |
|---|---|---|
| Governance | **UC securable** — RBAC, lineage, tags, audit inherited | Separate access model to build + audit |
| Sync | **Delta Sync Index** auto-tracks the chunk table (CDF) | You own an embed+upsert job |
| Embeddings | Managed via FM endpoint (`databricks-gte-large-en`) | You call an embedding API + store vectors |
| PII posture | Masking + `cdp_ai_app_users` grant already fit | PII leaves UC's control boundary |
| Cost/ops | One platform, serverless | Extra service, egress, key mgmt |
| When to pick external | — | Only if a non-Databricks consumer *requires* it (mirrors the Delta-vs-Iceberg rule in architecture.md §7) |

Native keeps the platform's core promise intact: **agents consume UC-governed surfaces only**.

---

## 5. Spike scope (what's in this commit vs. later)

**In this commit (design + thin spike):**
- This document.
- `src/pipelines/ingestion/unstructured_autoloader.py` — `bronze_docs_raw` (binaryFile Auto
  Loader) + `bronze_docs_parsed` (portable pandas_udf extraction).
- `src/pipelines/silver/document_chunking.py` — `silver_doc_chunks` with a pure-Python,
  unit-tested `chunk_text()` and PII masking hook.
- `resources/unstructured_ingestion.pipeline.yml` — the DLT pipeline wiring.
- Unit tests for `chunk_text()` and the agent's pure helpers.
- `agents/document_intelligence/` — a RAG agent whose `retrieve()` is **wired** to
  Vector Search `similarity_search` (customer-scoped filter + doc/page citations),
  with the connector lazily imported so the module loads off-cluster.

**Deferred (not today):**
- Vector Search index creation DDL + endpoint (one-time, run in the workspace — sketched in §6).
- Content-based customer/entity linking (beyond filename convention).
- `ai_parse_document` upgrade + table extraction fidelity.
- Governance grants/tags for the index; DQ/SLA on parse success rate.

---

## 6. Vector index — one-time setup (run in the workspace, not a DLT table)

```python
# Databricks notebook / job — creates the endpoint + Delta Sync Index once.
from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient()

vsc.create_endpoint(name="cdp_vs", endpoint_type="STANDARD")  # idempotent per-env

vsc.create_delta_sync_index(
    endpoint_name="cdp_vs",
    index_name=f"{CATALOG}.silver.vs_doc_chunks_index",
    source_table_name=f"{CATALOG}.silver.doc_chunks",
    pipeline_type="TRIGGERED",           # or CONTINUOUS for near-real-time
    primary_key="chunk_id",
    embedding_source_column="text",       # Vector Search embeds this column
    embedding_model_endpoint_name="databricks-gte-large-en",
)
# Grant retrieval to the agent group only:
# GRANT SELECT ON TABLE {CATALOG}.silver.vs_doc_chunks_index TO `cdp_ai_app_users`;
```

Retrieval from an agent:

```python
idx = vsc.get_index(endpoint_name="cdp_vs",
                    index_name=f"{CATALOG}.silver.vs_doc_chunks_index")
hits = idx.similarity_search(
    query_text="termination and renewal terms",
    columns=["text", "doc_type", "source_path", "page_or_sheet", "master_customer_id"],
    filters={"master_customer_id": mcid},
    num_results=5,
)
```

---

## 7. Open questions for review
- **Chunk size / overlap** — 800/100 is a default; tune per doc corpus (contracts vs. workbooks).
- **Customer linking** — filename convention now; do we invest in content-based linking soon?
- **Excel semantics** — treat each sheet as prose, or preserve tabular structure for numeric Q&A?
- **Index refresh cadence** — TRIGGERED (cheap) vs CONTINUOUS (fresh) for the Delta Sync Index.
- **Managed parsing** — is `ai_parse_document` GA in our Azure region/runtime yet (Option A)?
