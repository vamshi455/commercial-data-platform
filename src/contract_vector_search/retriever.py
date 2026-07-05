"""Thin retrieval helper over the contract Delta Sync index.

Wraps ``databricks-langchain``'s ``DatabricksVectorSearch`` with HYBRID search and
an ``is_current = true`` default filter, exposed so a LangGraph agent can wrap
``get_retriever_tool()`` as a tool node later. No Spark required — this runs
anywhere with workspace auth (job, model-serving, or a notebook).
"""

from __future__ import annotations

from typing import Any

try:  # config is a sibling module when deployed; fall back for standalone use.
    from config import Config, load_config
except Exception:  # pragma: no cover
    from .config import Config, load_config  # type: ignore

DEFAULT_FILTER = {"is_current": True}


def get_vectorstore(cfg: Config):
    """Return a DatabricksVectorSearch handle for the contract index."""
    from databricks_langchain import DatabricksVectorSearch

    return DatabricksVectorSearch(
        endpoint=cfg.endpoint,
        index_name=cfg.index_name,
        text_column="chunk_text",
        columns=[
            "chunk_id", "contract_id", "counterparty", "contract_type",
            "effective_date", "source_file", "page_number", "is_current",
        ],
    )


def search(
    query: str,
    cfg: Config | None = None,
    k: int = 5,
    filters: dict[str, Any] | None = None,
    only_current: bool = True,
) -> list[dict]:
    """HYBRID search the contract index; defaults to current contracts only."""
    cfg = cfg or load_config({})
    flt = dict(filters or {})
    if only_current:
        flt.setdefault("is_current", True)
    vs = get_vectorstore(cfg)
    docs = vs.similarity_search(query=query, k=k, filter=flt, query_type="HYBRID")
    return [{"text": d.page_content, **d.metadata} for d in docs]


def get_retriever(cfg: Config | None = None, k: int = 5, only_current: bool = True):
    """LangChain retriever (HYBRID, is_current filter) for agent tool wrapping."""
    cfg = cfg or load_config({})
    return get_vectorstore(cfg).as_retriever(
        search_kwargs={
            "k": k,
            "query_type": "HYBRID",
            "filter": DEFAULT_FILTER if only_current else {},
        }
    )
