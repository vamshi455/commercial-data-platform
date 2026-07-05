"""Environment config for the contract_vector_search module.

Same philosophy as ``src/pipelines/_common.py``: the SAME code runs against
``cdp_dev`` / ``cdp_qa`` / ``cdp_prod`` and only the config differs. Because this
module runs as a **Databricks Job** (notebook tasks), config arrives as job/task
parameters (widgets) rather than DLT ``spark.conf`` keys. ``load_config`` is pure
so it can be unit-tested; ``from_widgets`` is the notebook entry point.

All object names are derived from ``catalog`` + ``schema`` so there is a single
source of truth. Nothing here has side effects or imports Spark.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_SCHEMA = "contracts"
DEFAULT_ENDPOINT = "cdp_contracts_vs"
EMBEDDING_MODEL = "databricks-gte-large-en"


@dataclass(frozen=True)
class Config:
    catalog: str
    schema: str
    endpoint: str
    embedding_model: str = EMBEDDING_MODEL

    # ---- Volumes -----------------------------------------------------------
    @property
    def raw_volume(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/raw_contract_files"

    @property
    def checkpoint_volume(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/checkpoints"

    def checkpoint(self, stream: str) -> str:
        """One checkpoint dir per stream (bronze ingest, etc.)."""
        return f"{self.checkpoint_volume}/{stream}"

    # ---- Fully-qualified table names --------------------------------------
    @property
    def bronze_table(self) -> str:
        return f"{self.catalog}.{self.schema}.bronze_raw_contract_docs"

    @property
    def silver_table(self) -> str:
        return f"{self.catalog}.{self.schema}.silver_parsed_contracts"

    @property
    def failures_table(self) -> str:
        return f"{self.catalog}.{self.schema}.silver_parse_failures"

    @property
    def gold_table(self) -> str:
        return f"{self.catalog}.{self.schema}.gold_contract_chunks"

    @property
    def index_name(self) -> str:
        return f"{self.catalog}.{self.schema}.contract_chunks_index"


def load_config(params: dict) -> Config:
    """Pure builder from a plain dict (widgets, env, or a test)."""
    catalog = params.get("catalog") or "cdp_dev"
    return Config(
        catalog=catalog,
        schema=params.get("schema") or DEFAULT_SCHEMA,
        endpoint=params.get("vs_endpoint") or DEFAULT_ENDPOINT,
        embedding_model=params.get("embedding_model") or EMBEDDING_MODEL,
    )


def from_widgets(dbutils) -> Config:  # pragma: no cover - needs Databricks runtime
    """Notebook entry point: read task widgets set by the Job (see job yml)."""
    def w(name: str, default: str) -> str:
        try:
            dbutils.widgets.text(name, default)
        except Exception:
            pass
        return dbutils.widgets.get(name) or default

    return load_config(
        {
            "catalog": w("catalog", "cdp_dev"),
            "schema": w("schema", DEFAULT_SCHEMA),
            "vs_endpoint": w("vs_endpoint", DEFAULT_ENDPOINT),
            "embedding_model": w("embedding_model", EMBEDDING_MODEL),
        }
    )
