"""Testing criterion 4 — served-vs-eval retrieval parity (docs/agent-evals.md).

The eval path (agent.py -> retriever.py) uses HYBRID search with an is_current
filter. The SERVED artifact (model.py `_retrieve`) must do the same, or production
answers differ from what the eval harness scores. We inspect model.py's source
statically (AST) rather than importing it, so the test needs no mlflow / databricks
deps and runs off-cluster.

The HYBRID assertion is xfail(strict=True): model.py currently calls
`similarity_search(...)` with NO `query_type` (pure vector). It flips to XPASS —
failing CI — the moment model.py is unified onto the shared retriever.
"""
from __future__ import annotations

import ast
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
_MODEL = os.path.join(_ROOT, "agents", "contract_intelligence", "model.py")

# Governance/metadata columns the eval retriever (retriever.py) pulls back.
GOVERNANCE_COLUMNS = [
    "chunk_id", "contract_id", "counterparty", "contract_type",
    "effective_date", "source_file", "page_number", "is_current",
]


def _retrieve_source() -> str:
    """Return the source text of model.py's `_retrieve` function."""
    with open(_MODEL, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_retrieve":
            seg = ast.get_source_segment(src, node)
            assert seg, "could not extract _retrieve source segment"
            return seg
    raise AssertionError("model.py has no _retrieve function")


def test_model_has_retrieve_function():
    assert _retrieve_source()  # sanity: the served retrieval path exists


def test_served_retrieval_filters_current():
    # is_current governance filter must be applied on the served path (passes today).
    assert "is_current" in _retrieve_source()


def test_served_retrieval_pulls_governance_columns():
    src = _retrieve_source() + open(_MODEL, encoding="utf-8").read()
    missing = [c for c in GOVERNANCE_COLUMNS if c not in src]
    assert not missing, f"served retrieval omits governance columns: {missing}"


@pytest.mark.xfail(strict=True, reason=(
    "model.py._retrieve calls similarity_search with no query_type -> pure vector, "
    "while retriever.py uses query_type='HYBRID'. Served agent diverges from the "
    "evaluated path (docs/agent-evals.md criterion 4). Remove xfail once model.py "
    "reuses the shared retriever / passes HYBRID."))
def test_served_retrieval_is_hybrid():
    assert "HYBRID" in _retrieve_source()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-rxX"]))
