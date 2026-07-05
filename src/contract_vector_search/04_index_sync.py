# Databricks notebook source
# =============================================================================
# 04_index_sync — create (idempotent) + TRIGGERED sync of the Delta Sync index
# -----------------------------------------------------------------------------
# * Endpoint: STANDARD (not storage-optimized). Created if missing.
# * Index: create_delta_sync_index on gold_contract_chunks, pipeline_type
#   TRIGGERED (NO continuous sync — cost matters), managed embeddings via
#   databricks-gte-large-en.
# * Idempotent: if the index exists we skip creation and only call .sync().
# =============================================================================
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")
from config import from_widgets  # noqa: E402

from databricks.vector_search.client import VectorSearchClient  # noqa: E402

cfg = from_widgets(dbutils)  # noqa: F821
vsc = VectorSearchClient(disable_notice=True)

# COMMAND ----------
# Ensure a STANDARD endpoint exists (idempotent).
existing_endpoints = {e["name"] for e in (vsc.list_endpoints().get("endpoints") or [])}
if cfg.endpoint not in existing_endpoints:
    print(f"[index] creating STANDARD endpoint {cfg.endpoint}")
    vsc.create_endpoint_and_wait(name=cfg.endpoint, endpoint_type="STANDARD")
else:
    print(f"[index] endpoint {cfg.endpoint} already exists")

# COMMAND ----------
# Create the Delta Sync index if missing, else just sync.
def _index_exists(name: str) -> bool:
    try:
        vsc.get_index(endpoint_name=cfg.endpoint, index_name=name)
        return True
    except Exception:
        return False

COLUMNS_TO_SYNC = [
    "chunk_id", "contract_id", "counterparty", "contract_type",
    "effective_date", "source_file", "page_number", "is_current",
]

if not _index_exists(cfg.index_name):
    print(f"[index] creating Delta Sync index {cfg.index_name}")
    vsc.create_delta_sync_index_and_wait(
        endpoint_name=cfg.endpoint,
        index_name=cfg.index_name,
        source_table_name=cfg.gold_table,
        pipeline_type="TRIGGERED",           # no always-on sync
        primary_key="chunk_id",
        embedding_source_column="chunk_text",
        embedding_model_endpoint_name=cfg.embedding_model,
        columns_to_sync=COLUMNS_TO_SYNC,
    )
else:
    print(f"[index] syncing existing index {cfg.index_name}")
    vsc.get_index(endpoint_name=cfg.endpoint, index_name=cfg.index_name).sync()

print("[index] done")
