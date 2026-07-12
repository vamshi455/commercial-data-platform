# Databricks Gotchas & Lessons (Serverless / Agents / Vector Search)

> Hard-won lessons from building + running the contract RAG pipeline, the eval
> harness, the deployed agent, and the collections agentic-action loop. Each cost
> a failed run to discover — read this before the next serverless/agent build.

## Serverless notebooks & imports
- **No `__file__` in a serverless job notebook.** Relative paths fall back to `.`
  and cross-dir imports fail (`ModuleNotFoundError`). **Fix:** pass the deployed
  root as a param — `source_root: ${workspace.file_path}` — and build `sys.path`
  from it: `sys.path.insert(0, f"{root}/agents/contract_intelligence")`. Keep a
  `__file__`-relative fallback for local/pytest.
- **Sibling imports DO work** in a job notebook (same dir is on the path); only
  *cross-directory* imports need `source_root`.
- **DLT (Lakeflow) serverless cannot reliably import a `.py` from `/Workspace`**
  (OSError Errno 5) — inline shared helpers into each pipeline module. (Plain
  *jobs* can import siblings; this is DLT-specific.)
- **`currentRunId()` is not whitelisted on serverless** (`Py4JSecurityException`).
  Use the `{{job.run_id}}` base-parameter, or a `uuid` fallback — never the
  `dbutils…getContext().currentRunId()` API.

## LLM / model serving
- **Claude returns `message.content` as a LIST of blocks** (`[{"type":"text",
  "text":…}]`), not a string. Normalize: `"".join(b["text"] for b in content)` if
  it's a list. (It sometimes returns a plain string too — handle both.)
- **`claude-sonnet-5` rejects the `temperature` parameter** (`400 BAD_REQUEST`).
  Omit it; `max_tokens` is fine.
- Response shape from `mlflow.deployments.get_deploy_client("databricks").predict`
  is OpenAI-style: `resp["choices"][0]["message"]["content"]`.

## Spark / Delta / SQL
- **`ALTER TABLE … ADD CONSTRAINT IF NOT EXISTS … PRIMARY KEY` is invalid** in
  Databricks SQL (`PARSE_SYNTAX_ERROR`). Define the **PK inline** in
  `CREATE TABLE IF NOT EXISTS` (idempotent) instead.
- **`spark.createDataFrame(rows)` infers `NullType`** when a column is `None` for
  *every* row → `[CANNOT_DETERMINE_TYPE]`. **Always pass an explicit `StructType`**
  when building DataFrames from Python objects (data-dependent — it "works" until
  all values in a column are null).

## Vector Search
- **A Delta Sync index REQUIRES a PK + Change Data Feed** on the source table —
  they're how it does incremental upserts. Not optional.
- **Don't pass `text_column` to `DatabricksVectorSearch`** for a *managed-embeddings*
  index — it already knows its `embedding_source_column`; passing it raises
  `ValueError`. (Only pass it for self-managed-embedding indexes.)
- **Deleting a VS endpoint ORPHANS the index's UC entity.** `get-index` then
  reports missing, but `create_delta_sync_index` fails "UC entity … already
  exists". **Fix:** `databricks vector-search-indexes delete-index <name>` BEFORE
  re-running `index_sync`. (Bit us twice.)
- **`04_index_sync` is idempotent** — `create_endpoint_and_wait` if missing,
  create index if missing else `.sync()`. One run rebuilds both (after clearing
  the orphaned index).
- **CLI quirks:** `get-endpoint` outputs JSON by default — don't add `-o json` in
  a poll loop (returns empty). `vector-search-indexes query-index` has an SDK
  unmarshalling bug — query via the retriever/SDK, not the CLI.

## Deployment / bundle
- **`bundle deploy` can trigger a destructive-action prompt** (e.g. deleting a
  pipeline no longer in the bundle — our `crm_ingestion` cutover). It needs
  `--auto-approve`; **get explicit human OK first** (irreversible).
- **`{{job.run_id}}` / `${workspace.file_path}`** are the two substitutions that
  fixed most of our "runs locally, breaks in the job" issues.

## Cost model (what actually bills)
- **Vector Search endpoint = always-on billed** while it exists (no pause — only
  delete/recreate). This is the main standing cost; delete when idle.
- **Model Serving / agent endpoints support scale-to-zero** (`agents.deploy(
  scale_to_zero=True)`) → ≈no idle cost.
- **`TRIGGERED` Delta Sync index + `availableNow` Auto Loader** = no continuous
  compute. SQL warehouses **auto-suspend**. Batch action agents (collections)
  have **no serving endpoint → zero standing cost**.
- Pattern we used for cost-bounded validation: **recreate → run → delete**.

## The meta-lesson
Every one of these surfaced **only on a live run**, never in unit tests or
`bundle validate`. Budget for 2–5 "fix a real integration bug, re-run" cycles per
new serverless/agent pipeline — it's normal, not a sign something's wrong.
