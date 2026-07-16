"""Testing criteria for the golden eval set — docs/agent-evals.md criteria 1, 2, 6, 7.

Pure-python (no Spark): imports the shared `golden_set` rows and the industrial
contract-type taxonomy from `metadata_extract`, and asserts the golden set is
well-formed, adequately covers the safety lanes, and (the audit gaps) carries
ground-truth chunk ids + matches the platform's contract taxonomy.

Criteria that depend on deferred fixes (backfilling expected_chunk_ids; reframing
the oil-themed corpus/questions to the industrial domain) are xfail(strict=True) —
CI tracks them as known gaps and fails loudly (XPASS) the moment the fix lands.
"""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_EVALS = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir, "src", "evals"))
_MODULE = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir, "src", "contract_vector_search"))
for _p in (_EVALS, _MODULE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from golden_set import (  # noqa: E402
    COLUMNS, CATEGORIES, RETRIEVAL_CATEGORIES, REQUIRED_SAFETY_CATEGORIES, as_dicts,
)
import metadata_extract as meta  # noqa: E402

ROWS = as_dicts()
TAXONOMY_KEYWORDS = [kw for kw, _ in meta._TYPE_KEYWORDS]


# --------------------------------------------------------------------------- #
# Well-formedness + coverage (pass today — lock in good behavior)
# --------------------------------------------------------------------------- #
def test_seed_rows_have_full_schema():
    assert ROWS, "golden set is empty"
    for r in ROWS:
        assert set(r) == set(COLUMNS)
        assert r["request"] and r["category"], f"blank request/category: {r}"


def test_categories_are_recognized():  # criterion 2a
    for r in ROWS:
        assert r["category"] in CATEGORIES, f"unknown category: {r['category']}"


def test_required_safety_categories_covered():  # criterion 6
    present = {r["category"] for r in ROWS}
    missing = REQUIRED_SAFETY_CATEGORIES - present
    assert not missing, f"missing safety coverage: {missing}"


def test_suite_covers_content_and_safety_lanes():  # criterion 7
    present = {r["category"] for r in ROWS}
    assert present & RETRIEVAL_CATEGORIES, "no retrieval/groundedness (content) rows"
    assert REQUIRED_SAFETY_CATEGORIES <= present, "safety lane incomplete"


# --------------------------------------------------------------------------- #
# Audit gaps — tracked as xfail(strict) until the underlying data is fixed
# --------------------------------------------------------------------------- #
@pytest.mark.xfail(strict=True, reason=(
    "expected_chunk_ids not backfilled -> retrieval recall/precision/MRR are dead "
    "(docs/agent-evals.md criterion 1). Remove xfail once the golden set is labeled."))
def test_retrieval_rows_have_ground_truth_chunk_ids():  # criterion 1
    offenders = [r["request"] for r in ROWS
                 if r["category"] in RETRIEVAL_CATEGORIES and not r["expected_chunk_ids"]]
    assert not offenders, f"no expected_chunk_ids for: {offenders}"


def test_content_rows_reference_known_contract_type():  # criterion 2b — CLOSED 2026-07-15
    """Golden set reframed to the Rheinhardt Industrial corpus; every content row
    now names a contract_type in metadata_extract._TYPE_KEYWORDS, so retrieval
    filters can match. Was xfail while the set was oil/trading-themed."""
    def mentions_taxonomy(text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in TAXONOMY_KEYWORDS)
    offenders = [r["request"] for r in ROWS
                 if r["category"] in RETRIEVAL_CATEGORIES and not mentions_taxonomy(r["request"])]
    assert not offenders, f"requests reference no known contract type: {offenders}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-rxX"]))
