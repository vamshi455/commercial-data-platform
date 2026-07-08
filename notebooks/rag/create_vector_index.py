# Databricks notebook source
# MAGIC %md
# MAGIC # RAG — Create the Document Vector Search Index
# MAGIC One-time (per environment) setup for the unstructured / RAG track. Turns the
# MAGIC `silver.doc_chunks` Delta table produced by the `unstructured_ingestion`
# MAGIC pipeline into a **Databricks Vector Search Delta Sync Index** that the
# MAGIC `document_intelligence` agent retrieves from.
# MAGIC
# MAGIC **Prerequisites**
# MAGIC - The `unstructured_ingestion` pipeline has run and `<catalog>.silver.doc_chunks`
# MAGIC   exists and has rows (`delta.enableChangeDataFeed = true`, set by the pipeline).
# MAGIC - You are running as a principal allowed to create Vector Search endpoints/indexes.
# MAGIC - Cluster has `databricks-vector-search` available (`%pip install` cell below).
# MAGIC
# MAGIC See **docs/rag-unstructured.md §6**. This notebook is idempotent — re-running
# MAGIC reuses an existing endpoint/index rather than failing.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-vector-search
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "cdp_dev", "Target catalog (cdp_dev/qa/prod)")
dbutils.widgets.text("endpoint", "cdp_vs", "Vector Search endpoint name")
dbutils.widgets.text("embedding_model", "databricks-gte-large-en", "Embedding model endpoint")
dbutils.widgets.dropdown("pipeline_type", "TRIGGERED", ["TRIGGERED", "CONTINUOUS"], "Sync mode")

CATALOG = dbutils.widgets.get("catalog")
ENDPOINT = dbutils.widgets.get("endpoint")
EMBEDDING_MODEL = dbutils.widgets.get("embedding_model")
PIPELINE_TYPE = dbutils.widgets.get("pipeline_type")

SOURCE_TABLE = f"{CATALOG}.silver.doc_chunks"
INDEX_NAME = f"{CATALOG}.silver.vs_doc_chunks_index"
PRIMARY_KEY = "chunk_id"
EMBEDDING_SOURCE_COLUMN = "text"        # the masked chunk text Vector Search embeds

print(f"catalog={CATALOG}\nendpoint={ENDPOINT}\nsource={SOURCE_TABLE}\nindex={INDEX_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Preflight — source table exists, has rows, and has CDF enabled
# MAGIC A Delta Sync Index requires Change Data Feed on the source. The
# MAGIC `unstructured_ingestion` pipeline sets it; we assert here so failures are
# MAGIC explicit rather than surfacing later inside Vector Search.

# COMMAND ----------

from pyspark.sql.utils import AnalysisException

try:
    n = spark.table(SOURCE_TABLE).count()
except AnalysisException as e:
    raise AssertionError(
        f"{SOURCE_TABLE} not found — run the unstructured_ingestion pipeline first."
    ) from e

assert n > 0, f"{SOURCE_TABLE} has 0 rows — land some PDFs/Excel and re-run the pipeline."

cdf = (spark.sql(f"SHOW TBLPROPERTIES {SOURCE_TABLE}")
       .filter("key = 'delta.enableChangeDataFeed'").collect())
assert cdf and cdf[0]["value"].lower() == "true", (
    f"{SOURCE_TABLE} must have delta.enableChangeDataFeed=true for a Delta Sync Index."
)
print(f"OK — {SOURCE_TABLE}: {n} rows, CDF enabled.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Ensure the Vector Search endpoint (idempotent)

# COMMAND ----------

from databricks.vector_search.client import VectorSearchClient

vsc = VectorSearchClient(disable_notice=True)

existing_endpoints = {e["name"] for e in vsc.list_endpoints().get("endpoints", [])}
if ENDPOINT in existing_endpoints:
    print(f"Endpoint '{ENDPOINT}' already exists — reusing.")
else:
    print(f"Creating endpoint '{ENDPOINT}' (STANDARD)…")
    vsc.create_endpoint(name=ENDPOINT, endpoint_type="STANDARD")
    vsc.wait_for_endpoint(name=ENDPOINT, timeout=1800)
print("Endpoint ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create (or reuse) the Delta Sync Index
# MAGIC Vector Search computes embeddings itself from `text` via the model endpoint;
# MAGIC we do not manage an embedding job. `TRIGGERED` syncs on demand (cheap);
# MAGIC `CONTINUOUS` keeps it near-real-time.

# COMMAND ----------

def _index_exists(name: str) -> bool:
    try:
        return any(ix.get("name") == name
                   for ix in vsc.list_indexes(name=ENDPOINT).get("vector_indexes", []))
    except Exception:
        return False

if _index_exists(INDEX_NAME):
    print(f"Index '{INDEX_NAME}' already exists — triggering a sync instead.")
    index = vsc.get_index(endpoint_name=ENDPOINT, index_name=INDEX_NAME)
    if PIPELINE_TYPE == "TRIGGERED":
        index.sync()
else:
    print(f"Creating Delta Sync Index '{INDEX_NAME}'…")
    index = vsc.create_delta_sync_index(
        endpoint_name=ENDPOINT,
        index_name=INDEX_NAME,
        source_table_name=SOURCE_TABLE,
        pipeline_type=PIPELINE_TYPE,
        primary_key=PRIMARY_KEY,
        embedding_source_column=EMBEDDING_SOURCE_COLUMN,
        embedding_model_endpoint_name=EMBEDDING_MODEL,
    )
    vsc.wait_for_index(endpoint_name=ENDPOINT, index_name=INDEX_NAME, timeout=1800)
print("Index ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Grant retrieval to the agent group ONLY
# MAGIC The index is a UC securable — the governance boundary is the grant, not the
# MAGIC agent prompt. `cdp_ai_app_users` (the group the `document_intelligence` agent
# MAGIC runs as) gets read; nobody else does.

# COMMAND ----------

spark.sql(f"GRANT SELECT ON TABLE {INDEX_NAME} TO `cdp_ai_app_users`")
print(f"Granted SELECT on {INDEX_NAME} to cdp_ai_app_users.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Smoke test — retrieve like the agent does
# MAGIC Mirrors `agents/document_intelligence/agent.py::retrieve()`: same columns,
# MAGIC same optional `master_customer_id` filter.

# COMMAND ----------

hits = index.similarity_search(
    query_text="termination and renewal terms",
    columns=["chunk_id", "text", "doc_type", "source_path", "page_or_sheet",
             "master_customer_id"],
    num_results=5,
)
for row in hits.get("result", {}).get("data_array", []):
    print(row)

print("\nDone. The document_intelligence agent can now retrieve from",
      INDEX_NAME)
