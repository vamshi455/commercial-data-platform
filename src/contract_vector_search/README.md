# contract_vector_search

Incremental ingestion of sales & procurement contract PDFs into **Mosaic AI Vector Search**
for a downstream RAG agent. Additive module — it does not modify existing
pipelines, tables, or jobs. Spec: [`docs/specs/contract-vector-search.md`](../../docs/specs/contract-vector-search.md).

## Architecture

```
raw_contract_files (Volume, *.pdf)
        │  Auto Loader binaryFile, trigger(availableNow=True)  [01_bronze_ingest]
        ▼
bronze_raw_contract_docs ──► ai_parse_document + contract-aware chunking  [02_silver_parse_chunk]
        │                         │                         └─► silver_parse_failures (dead-letter)
        ▼                         ▼
                        silver_parsed_contracts
        │  MERGE on chunk_id + amendment/is_current logic  [03_gold_merge]
        ▼
gold_contract_chunks  (CDF on)
        │  Delta Sync index, TRIGGERED, managed embeddings (gte-large-en)  [04_index_sync]
        ▼
contract_chunks_index ──► retriever.py (HYBRID, is_current=true) ──► LangGraph tool
```

One serverless **Job** (`resources/contract_vector_search.job.yml`) chains the
five tasks and is **file-arrival triggered** on the raw volume.

## Design choices

- **Job of Python tasks**, not a DLT pipeline: the flow needs imperative `MERGE`,
  `is_current` amendment updates, and Vector Search SDK calls, which don't fit
  DLT's declarative streaming-table model.
- **`<catalog>.contracts` schema** per environment (`cdp_dev.contracts`, …) —
  isolated from the medallion domains.
- **Pure, testable core**: `chunking.py`, `metadata_extract.py`, `versioning.py`,
  `config.py` have no Spark/Databricks imports and are covered by
  `tests/test_contract_vector_search.py` (runs off-cluster).

## Run it

```bash
databricks bundle deploy -t dev
databricks bundle run job_contract_vector_search -t dev
```

**Backfill = just run the job.** The Auto Loader checkpoint is the single control:
first run (empty checkpoint) drains every existing PDF; later runs pick up only
new files. Same code path for backfill and incremental — nothing special to do.

## Add a new environment

1. Add a target in `databricks.yml` with its `catalog` (e.g. `cdp_qa`).
2. Provision a **Vector Search endpoint** for it and set `vs_endpoint` in that
   target's `variables:` (a VS endpoint is an always-on billed resource — one per
   env that needs search; today only **dev** is provisioned).
3. `databricks bundle deploy -t <env>` then run the job.

## Re-sync the index manually

The index is `TRIGGERED` (no continuous sync). Re-run just the sync task:

```bash
databricks bundle run job_contract_vector_search -t dev --only index_sync
```

or from a notebook: `vsc.get_index(endpoint, index_name).sync()`.

## Cost note

- Index sync is `TRIGGERED` and bronze uses `trigger(availableNow=True)` — **no
  always-on compute**.
- The **Vector Search endpoint itself is always-on billed** infra (~$/hr while it
  exists), independent of query volume. Delete the endpoint to stop that cost.
