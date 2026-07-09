# RAG / Unstructured Track — Deploy Runbook

> **What this deploys:** the unstructured document lane added in the RAG track —
> the `unstructured_ingestion` pipeline (`bronze_docs_raw_*` → `bronze_docs_parsed_*`
> → `silver.doc_chunks`), the Vector Search index, and the `document_intelligence`
> agent that retrieves from it.
> **Design:** [`rag-unstructured.md`](./rag-unstructured.md) · **Branch:**
> `feat/azure-deploy-and-pipeline-fixes`.
>
> **Run this from a machine with workspace access** (your laptop / CI) — not from a
> Claude Code *web* sandbox, which has no Databricks CLI or credentials. To bring
> this session local first: `claude --teleport` (see
> [claude-code-on-the-web](https://code.claude.com/docs/en/claude-code-on-the-web)).

---

## 0. Prerequisites

| Need | Check |
|---|---|
| Databricks CLI ≥ 0.220 | `databricks --version` |
| Auth to the target workspace | WIF/OIDC in CI, or `databricks auth login --host <adb-…azuredatabricks.net>` locally |
| On the right branch, clean tree | `git switch feat/azure-deploy-and-pipeline-fixes && git pull && git status` |
| Cluster/runtime can `pip install` | `pymupdf`, `openpyxl` (extraction), `databricks-vector-search` (index/agent) |

The bundle targets are `dev` / `qa` / `prod` → catalogs `cdp_dev` / `cdp_qa` /
`cdp_prod`. Everything below shows `-t dev`; promote by swapping the target.

---

## 1. Validate + deploy the bundle

```bash
databricks bundle validate -t dev
databricks bundle deploy   -t dev
```

`deploy` syncs the new pipeline code (`src/pipelines/ingestion/unstructured_autoloader.py`,
`src/pipelines/silver/document_chunking.py`) and registers the
`unstructured_ingestion` pipeline (`resources/unstructured_ingestion.pipeline.yml`).

> The pip deps `pymupdf` + `openpyxl` are declared in the pipeline's
> `environment.dependencies`, so serverless DLT installs them at run time.

---

## 2. Land sample documents

Drop PDFs/Excel into the **existing** landing Volume, under the doc-type + date
partitions the Auto Loader watches:

```bash
databricks fs mkdir  dbfs:/Volumes/cdp_dev/landing/files/unstructured/pdf/dt=$(date +%F)
databricks fs cp  ./samples/apex_msa.pdf \
  dbfs:/Volumes/cdp_dev/landing/files/unstructured/pdf/dt=$(date +%F)/
databricks fs cp  ./samples/pricing.xlsx \
  dbfs:/Volumes/cdp_dev/landing/files/unstructured/excel/dt=$(date +%F)/
```

**Customer linking (optional but recommended):** prefix a filename with the
`master_customer_id` + `__` so retrieval can be scoped per customer
(see `document_chunking.py`):

```
<master_customer_id>__<anything>.pdf     e.g.  abcd1234__apex_msa.pdf
```

Files without that prefix still ingest; their `master_customer_id` is just empty.

---

## 3. Run the ingestion pipeline

`unstructured_ingestion` is **standalone / on-demand** (it is *not* wired into
`job_orchestration_daily`, same as `crm_postgres_ingestion`). Run it directly:

```bash
databricks bundle run unstructured_ingestion -t dev
```

This materializes, in order:
`bronze.bronze_docs_raw_{pdf,excel}` → `bronze.bronze_docs_parsed_{pdf,excel}`
→ `silver.doc_chunks`.

---

## 4. Verify bronze + silver

```sql
-- one row per file
SELECT doc_type, count(*) FROM cdp_dev.bronze.bronze_docs_raw_pdf   GROUP BY 1;
-- one row per page/sheet; watch parse_error
SELECT parse_error IS NULL AS ok, count(*)
FROM   cdp_dev.bronze.bronze_docs_parsed_pdf GROUP BY 1;
-- chunks ready for embedding (text is PII-masked)
SELECT count(*) AS chunks,
       count(DISTINCT doc_id)              AS docs,
       count(DISTINCT master_customer_id)  AS customers
FROM   cdp_dev.silver.doc_chunks;
```

Expect `chunks > 0`. If `doc_chunks` is empty, check `parse_error` in the parsed
tables (missing `pymupdf`/`openpyxl`, or a scanned/image-only PDF — those need
the `ai_parse_document` upgrade noted in the design doc §3.3).

---

## 5. Create the Vector Search index

Run the notebook (idempotent, parameterized by `catalog` widget):

```
notebooks/rag/create_vector_index.py     # widgets: catalog=cdp_dev, endpoint=cdp_vs
```

It preflights (`doc_chunks` exists, has rows, CDF on), ensures the `cdp_vs`
endpoint, creates the `cdp_dev.silver.vs_doc_chunks_index` Delta Sync Index
(embeds `text` via `databricks-gte-large-en`), grants `SELECT` to
`cdp_ai_app_users`, and runs a smoke retrieval.

Or via the CLI/notebook job if you prefer not to open the UI:

```bash
databricks workspace import ./notebooks/rag/create_vector_index.py \
  /Workspace/Users/<you>/create_vector_index --language PYTHON --format SOURCE
# then run it as a one-off notebook task / in the workspace.
```

---

## 6. Wire + smoke-test the agent

The `document_intelligence` agent retrieves from the index. Its runtime needs the
connector and the endpoint name:

```bash
pip install databricks-vector-search
export CDP_VS_ENDPOINT=cdp_vs          # default already 'cdp_vs'
```

Smoke test the retrieval path (module-level demo prints the tool catalog + a
citation; live retrieval needs the connector + index):

```bash
python agents/document_intelligence/agent.py
```

In the agent runtime, `search_documents(catalog="cdp_dev", question=..., master_customer_id=...)`
returns masked chunks + `citation` strings.

---

## 7. Promote to qa / prod

Config-only — same commands, new target (index is per-catalog, so re-run the
notebook per env):

```bash
databricks bundle deploy -t qa   && databricks bundle run unstructured_ingestion -t qa
# notebooks/rag/create_vector_index.py  with catalog=cdp_qa
```

> **qa note:** the branch currently runs qa as the deploying **user** (temporary
> workaround — no service principal / `cdp_*` groups yet; see the comment in
> `databricks.yml`). The `cdp_ai_app_users` grant in the index notebook assumes
> that group exists — create it, or adjust the grantee, before prod.

---

## 8. Rollback / re-run

| Situation | Action |
|---|---|
| Bad parse logic | Fix `unstructured_autoloader.py`, redeploy, **full refresh** the parsed tables only (raw is protected: `pipelines.reset.allowed=false`). |
| Re-embed after chunk change | The Delta Sync Index auto-syncs on the next `TRIGGERED` sync (or continuously); re-run the notebook's sync cell. |
| Wrong/over-broad grant | `REVOKE SELECT ON TABLE cdp_dev.silver.vs_doc_chunks_index FROM ...`. |
| Tear down dev | `databricks bundle destroy -t dev` (dev only). |

---

## 9. Definition of done

- [ ] `databricks bundle deploy -t dev` clean
- [ ] `silver.doc_chunks` has rows; low `parse_error` rate
- [ ] `vs_doc_chunks_index` created; smoke retrieval returns relevant chunks
- [ ] `cdp_ai_app_users` granted read on the index (and nothing broader)
- [ ] `document_intelligence` retrieval returns cited chunks, customer-scoped
