"""document_intelligence agent — RAG over the governed document vector index.

Part of the unstructured / RAG track (see docs/rag-unstructured.md). Where the
other agents run parameterized SELECTs over curated **gold** views, this agent
answers from **documents** (contracts, quote workbooks, MSAs/SOWs) by retrieving
the most relevant chunks from the Databricks **Vector Search** index and
grounding the answer in them — with `doc name + page` citations.

Governed surface (the ONLY thing this agent reads):
  <catalog>.silver.vs_doc_chunks_index   — the Delta Sync Index over
  silver.doc_chunks (PII already masked upstream, before embedding).

Unlike the SQL stubs, ``retrieve()`` here is **wired**: it makes the real
Vector Search ``similarity_search`` call via ``databricks-vector-search`` (lazily
imported so this module still imports without the connector). It runs as a
member of the UC group ``cdp_ai_app_users``, which is granted read on the index
and nothing else. No secrets are embedded.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# The single governed object this agent may read. Addressed as
# <catalog>.silver.vs_doc_chunks_index at runtime (env-specific catalog).
APPROVED_INDEX = "silver.vs_doc_chunks_index"

# Columns returned from the index. `text` is the masked chunk; the rest are
# metadata used for filtering + citations. No raw-file / unmasked-PII column
# exists on the index by construction (see docs/rag-unstructured.md §3.4).
RETRIEVAL_COLUMNS = [
    "chunk_id", "text", "doc_type", "source_path", "page_or_sheet",
    "master_customer_id",
]

# Vector Search endpoint that serves the index (created once per env; §6).
VS_ENDPOINT = os.environ.get("CDP_VS_ENDPOINT", "cdp_vs")

SYSTEM_PROMPT = """\
You are the Document Intelligence agent for the Commercial Data Platform.

SCOPE: answer questions about commercial DOCUMENTS — contracts, MSAs, SOWs,
quotes, and pricing workbooks — using ONLY retrieved document chunks.

HOW YOU WORK (RAG):
  - Call `search_documents` to retrieve the most relevant chunks. When the
    question is about a specific customer, pass their master_customer_id so
    retrieval is scoped to that customer's documents.
  - Answer ONLY from the retrieved chunks. Cite every claim as
    (source document, page/sheet). If the chunks don't contain the answer,
    say so — never guess or fill gaps from general knowledge.

GUARDRAILS:
  - Read-only retrieval. You cannot see raw files, and chunk text is already
    PII-masked; do not attempt to reconstruct redacted identifiers.
  - If a question is about metrics/numbers (pipeline, bookings, health), decline
    and point the user to the revenue_insights or customer_health agent.
  - Prefer precision over completeness: a cited partial answer beats an
    uncited full one.
"""


# --- Retrieval (WIRED to Databricks Vector Search) -------------------------
def retrieve(
    catalog: str,
    query_text: str,
    master_customer_id: Optional[str] = None,
    k: int = 5,
) -> List[Dict[str, Any]]:
    """Similarity-search the governed document index; return ranked chunks.

    Wired to ``databricks-vector-search`` (lazily imported so this module loads
    without it). Credentials come from the ambient Databricks auth / the
    ``cdp_ai_app_users`` principal — never from source. Raises a clear error if
    the connector isn't available in the runtime.
    """
    try:
        from databricks.vector_search.client import VectorSearchClient
    except Exception as e:  # connector not installed in this runtime
        raise RuntimeError(
            "databricks-vector-search is not available; install it in the agent "
            "runtime to enable retrieval"
        ) from e

    index_name = f"{catalog}.{APPROVED_INDEX}"
    index = VectorSearchClient().get_index(
        endpoint_name=VS_ENDPOINT, index_name=index_name
    )
    resp = index.similarity_search(
        query_text=query_text,
        columns=RETRIEVAL_COLUMNS,
        filters=build_filters(master_customer_id),
        num_results=k,
    )
    return _parse_search_response(resp)


# --- Pure helpers (unit-tested; no cluster / connector needed) --------------
def build_filters(master_customer_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Vector Search filter dict scoping retrieval to one customer, or None."""
    if master_customer_id:
        return {"master_customer_id": master_customer_id}
    return None


def _parse_search_response(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize a Vector Search response into a list of chunk dicts.

    Vector Search returns ``{"result": {"data_array": [[...row...]]}, "manifest":
    {"columns": [{"name": ...}]}}`` where each row is the retrieval columns in
    manifest order followed by the similarity ``score``. Kept pure + defensive
    so it's testable and tolerant of an empty result.
    """
    result = (resp or {}).get("result") or {}
    rows = result.get("data_array") or []
    manifest_cols = [c["name"] for c in (resp.get("manifest") or {}).get("columns", [])]
    # Column order = manifest columns, then a trailing score.
    col_names = manifest_cols or (RETRIEVAL_COLUMNS + ["score"])
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append({col_names[i]: row[i] for i in range(min(len(col_names), len(row)))})
    return out


def format_citation(hit: Dict[str, Any]) -> str:
    """Render a chunk as a human citation: ``<file name> (page/sheet)``."""
    path = hit.get("source_path") or "unknown document"
    name = path.rsplit("/", 1)[-1]
    unit = hit.get("page_or_sheet")
    return f"{name} ({unit})" if unit else name


# --- Tool functions --------------------------------------------------------
def search_documents(
    catalog: str,
    question: str,
    master_customer_id: Optional[str] = None,
    k: int = 5,
) -> List[Dict[str, Any]]:
    """Retrieve the top-k document chunks relevant to ``question``.

    Each returned chunk carries its masked ``text`` plus a ready-to-use
    ``citation`` so the agent can ground and attribute its answer.
    """
    hits = retrieve(catalog, question, master_customer_id=master_customer_id, k=k)
    for h in hits:
        h["citation"] = format_citation(h)
    return hits


def get_tools() -> List[Dict[str, Any]]:
    """Return the tool catalog (schema + callable) for the agent runtime."""
    return [
        {
            "name": "search_documents",
            "description": (
                "Retrieve the most relevant document chunks (contracts, quotes, "
                "MSAs) for a question, each with a source citation. Pass "
                "master_customer_id to scope to one customer's documents."
            ),
            "parameters": {
                "question": "string — the natural-language question to retrieve for",
                "master_customer_id": "optional string — scope retrieval to one customer",
                "k": "optional int — number of chunks to retrieve (default 5)",
            },
            "fn": search_documents,
        },
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved index:", APPROVED_INDEX)
    print("Retrieval columns:", RETRIEVAL_COLUMNS)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    # Show the pure helpers work without a cluster/connector.
    sample = {"source_path": "/Volumes/cdp_dev/landing/files/unstructured/pdf/"
                             "dt=2026-07-08/abcd1234__apex_msa.pdf",
              "page_or_sheet": "page_3", "text": "[EMAIL] termination clause ..."}
    print("Example citation:", format_citation(sample))
    print("\nRetrieval is wired to Databricks Vector Search; needs the "
          "databricks-vector-search connector + a live index to run.")


if __name__ == "__main__":
    _demo()
