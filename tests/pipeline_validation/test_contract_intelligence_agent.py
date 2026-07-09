"""Unit tests for the contract_intelligence agent's pure helpers (off-cluster)."""
from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT = os.path.abspath(os.path.join(
    _HERE, os.pardir, os.pardir, "agents", "contract_intelligence", "agent.py"))
_spec = importlib.util.spec_from_file_location("contract_intelligence_agent", _AGENT)
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)


def test_format_context_labels_file_and_page():
    hits = [{"source_file": "/v/abc__spot_purchase.pdf", "page_number": 2,
             "text": "30 days notice."}]
    ctx = agent.format_context(hits)
    assert "[abc__spot_purchase.pdf p2]" in ctx      # full basename, prefix kept
    assert "30 days notice." in ctx


def test_format_context_supports_chunk_text_key():
    hits = [{"source_file": "/v/x.pdf", "page_number": 1, "chunk_text": "body"}]
    assert "body" in agent.format_context(hits)


def test_build_prompt_contains_context_and_question():
    p = agent.build_prompt("CTX", "What is the term?")
    assert "CTX" in p and "What is the term?" in p


def test_extract_cited_docs():
    ans = "Per [spot_purchase.pdf p2] and [pricing.xlsx p1], the term is 30 days."
    docs = agent.extract_cited_docs(ans)
    assert "spot_purchase.pdf" in docs and "pricing.xlsx" in docs


def test_extract_cited_docs_none():
    assert agent.extract_cited_docs("No citations here.") == []


def test_tool_catalog():
    tools = agent.get_tools()
    assert any(t["name"] == "answer_contract_question" and callable(t["fn"]) for t in tools)


def test_gen_model_is_configured():
    assert agent.GEN_MODEL == "databricks-claude-sonnet-5"
