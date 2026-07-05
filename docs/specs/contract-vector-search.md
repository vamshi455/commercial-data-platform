# Spec: Contract Vector Search Module

**Status:** Built (code + tests + bundle validated) — NOT yet run against compute
**Owner:** vamshi
**Module name:** `contract_vector_search`
**Resolved decisions (2026-07-04):**
- Execution model: **Job of Python tasks** (not DLT) — `resources/contract_vector_search.job.yml`
- Placement: **`<catalog>.contracts`** schema per env (`cdp_dev.contracts`, …)
- `<CATALOG>` = `${var.catalog}` · `<SCHEMA>` = `contracts` · `<VS_ENDPOINT>` = `cdp_contracts_vs`
- Vector Search endpoint **provisioned in dev only** (`cdp_contracts_vs`, STANDARD, ONLINE) — ⚠️ always-on billed

> Additive module. Do NOT restructure or refactor existing pipelines. Reuse the
> project's existing conventions (bundle vars + `spark.conf` `cdp.*` keys, `src/pipelines/`
> layout, `resources/*.yml`, secret scope `cdp`) wherever they exist.

## Business context

Crude oil contract documents (PDFs, occasionally scanned) land in a Unity Catalog
Volume. They must be searchable via Databricks Mosaic AI Vector Search for a
downstream RAG agent. Ingestion is fully incremental — new files processed exactly
once, no reprocessing. Historical backfill and ongoing incremental loads share ONE
code path (Auto Loader checkpoint: first run drains everything, later runs drain only
new files).

## Environment / naming

- Catalog: `<CATALOG>` (this repo: `cdp_dev` / `cdp_qa` / `cdp_prod` via `${var.catalog}`)
- Schema: `<SCHEMA>`
- Landing Volume: `/Volumes/<CATALOG>/<SCHEMA>/raw_contract_files/`
- Checkpoint Volume: `/Volumes/<CATALOG>/<SCHEMA>/checkpoints/`
- Vector Search endpoint: `<VS_ENDPOINT>` (standard, NOT storage-optimized)
- Embedding model endpoint: `databricks-gte-large-en` (managed embeddings)
- Environments: dev / qa / prod parameterized the same way the rest of this repo does
  (bundle `variables:` + target overrides; `spark.conf` `cdp.*` at runtime)

## Architecture (implement exactly this)

Medallion flow, all incremental:

### 1. Bronze — `bronze_raw_contract_docs`
- Auto Loader structured stream: `cloudFiles.format = binaryFile`,
  `pathGlobFilter = *.pdf` (also accept `*.PDF`), source = landing Volume.
- `trigger(availableNow=True)` — drain-and-stop, no always-on compute.
- Checkpoint under the checkpoint Volume, one checkpoint dir per stream.
- Capture file metadata: path, modificationTime, length.

### 2. Silver — `silver_parsed_contracts`
- Parse PDFs with `ai_parse_document()`. On parse failure / empty text, write to
  dead-letter table `silver_parse_failures` (file path, error, timestamp) — never
  silently drop.
- Chunking: recursive splitter with contract-aware separators (section headers,
  numbered clauses like "1.", "ARTICLE", "SECTION", "WHEREAS") before falling back to
  paragraph and sentence splits. Target ~1000 tokens/chunk, ~150 token overlap. Never
  split mid-clause when a separator is available.
- Attach metadata to every chunk: `contract_id`, `counterparty`, `contract_type`,
  `effective_date`, `expiry_date`, `source_file`, `page_number`, `version`, `is_current`.

### 3. Gold — `gold_contract_chunks`
- `chunk_id STRING NOT NULL` primary key = `sha2(source_file || ':' || chunk_seq, 256)`.
- `TBLPROPERTIES (delta.enableChangeDataFeed = true)` — REQUIRED for Delta Sync.
- Write via MERGE keyed on `chunk_id` — never blind append.
- Amendment handling: when a new version of an existing `contract_id` arrives, set
  `is_current = false` on prior-version chunks and insert new chunks with incremented
  `version`. Retrieval filters on `is_current = true` by default.

### 4. Vector index — Delta Sync
- `create_delta_sync_index` on `gold_contract_chunks`, `pipeline_type = "TRIGGERED"`,
  `primary_key = "chunk_id"`, `embedding_source_column = "chunk_text"`,
  `embedding_model_endpoint_name = "databricks-gte-large-en"`,
  `columns_to_sync = [contract_id, counterparty, contract_type, effective_date,
  source_file, page_number, is_current]`.
- Idempotent: check-if-exists before create; if it exists, skip create and only `.sync()`.

### 5. Orchestration — one Databricks Job
- File arrival trigger on the landing Volume path.
- Task chain: bronze ingest → silver parse/chunk → gold merge → index sync.
- Deploy as a Databricks Asset Bundle (`databricks.yml`) with dev/qa/prod targets
  (this repo already uses DABs — match it).

## Deliverables

- `src/contract_vector_search/` (or repo-equivalent source layout): bronze, silver,
  gold notebooks/scripts + a shared `config` module.
- `ddl/` — SQL for all tables incl. dead-letter table, with CDF property.
- Job definition (asset bundle) incl. the file arrival trigger.
- `retriever.py` — thin retrieval helper using `databricks-langchain`'s
  `DatabricksVectorSearch`, `query_type="HYBRID"`, metadata filter support
  (`is_current = true` default), exposed so a LangGraph agent can wrap it as a tool later.
- `tests/` — unit tests for chunking logic (separator behavior, overlap, chunk_id
  determinism) and the amendment/versioning MERGE logic. Match repo's test framework.
- `README.md` for the module: architecture summary, how to run backfill (= run the job;
  empty checkpoint drains everything), how to add a new environment, how to re-sync the
  index manually.

## Hard constraints

- Idempotent everywhere: re-running any task must not duplicate chunks or vectors.
- No CONTINUOUS index sync, no always-on streams — cost matters.
- No secrets in code; use existing secret scope / env config patterns.
- Do not modify existing pipelines, tables, or jobs in this repo.
- Ask before any choice that deviates from this spec.

## Order of work

1. Read the repo, summarize conventions, confirm module location before writing code.
2. DDL + bronze.
3. Silver parse/chunk + dead-letter + chunking unit tests.
4. Gold MERGE + amendment logic + tests.
5. Index creation/sync + retriever helper.
6. Job definition + README.

## Open decisions (to resolve before build)

See the implementation plan discussion. Key forks: execution model (Job of notebook
tasks vs DLT), catalog/schema placement, and the Vector Search endpoint cost model
(the standard endpoint is an always-on billed resource).
