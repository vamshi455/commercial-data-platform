"""Pure-python unit tests for the document_intelligence RAG agent helpers.

Exercises the off-cluster logic — filter construction, response parsing, citation
formatting, and the tool catalog — without the databricks-vector-search connector
or a live index. Retrieval itself (`retrieve`) needs the connector and is not
tested here.
"""
from __future__ import annotations

import importlib.util
import os

# Load agents/document_intelligence/agent.py by path (agents/ isn't a package).
_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT = os.path.abspath(os.path.join(
    _HERE, os.pardir, os.pardir, "agents", "document_intelligence", "agent.py"))
_spec = importlib.util.spec_from_file_location("document_intelligence_agent", _AGENT)
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)


def test_build_filters_scopes_to_customer():
    assert agent.build_filters("abc123") == {"master_customer_id": "abc123"}


def test_build_filters_none_when_unscoped():
    assert agent.build_filters(None) is None
    assert agent.build_filters("") is None


def test_parse_response_maps_columns_to_dicts():
    resp = {
        "manifest": {"columns": [{"name": "chunk_id"}, {"name": "text"},
                                 {"name": "page_or_sheet"}, {"name": "score"}]},
        "result": {"data_array": [
            ["c1", "termination clause", "page_2", 0.91],
            ["c2", "renewal terms", "page_5", 0.87],
        ]},
    }
    out = agent._parse_search_response(resp)
    assert len(out) == 2
    assert out[0] == {"chunk_id": "c1", "text": "termination clause",
                      "page_or_sheet": "page_2", "score": 0.91}
    assert out[1]["chunk_id"] == "c2"


def test_parse_response_empty_is_empty_list():
    assert agent._parse_search_response({}) == []
    assert agent._parse_search_response({"result": {"data_array": []}}) == []


def test_parse_response_tolerates_short_rows():
    resp = {"manifest": {"columns": [{"name": "a"}, {"name": "b"}, {"name": "c"}]},
            "result": {"data_array": [["x", "y"]]}}  # row shorter than columns
    assert agent._parse_search_response(resp) == [{"a": "x", "b": "y"}]


def test_format_citation_uses_filename_and_unit():
    hit = {"source_path": "/Volumes/cdp_dev/landing/files/unstructured/pdf/"
                          "dt=2026-07-08/abcd1234__apex_msa.pdf",
           "page_or_sheet": "page_3"}
    assert agent.format_citation(hit) == "abcd1234__apex_msa.pdf (page_3)"


def test_format_citation_without_unit():
    assert agent.format_citation({"source_path": "/x/y/quote.xlsx"}) == "quote.xlsx"


def test_format_citation_unknown_document():
    assert agent.format_citation({}) == "unknown document"


def test_tool_catalog_exposes_search_documents():
    tools = agent.get_tools()
    names = {t["name"] for t in tools}
    assert "search_documents" in names
    tool = next(t for t in tools if t["name"] == "search_documents")
    assert callable(tool["fn"])
    assert "master_customer_id" in tool["parameters"]


def test_approved_index_is_governed_silver_surface():
    # Guardrail: the agent's only approved object is the governed vector index.
    assert agent.APPROVED_INDEX == "silver.vs_doc_chunks_index"
    # No raw-file / bytes column is exposed for retrieval.
    assert "content" not in agent.RETRIEVAL_COLUMNS
