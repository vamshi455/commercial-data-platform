"""Unit tests for the deterministic eval scorers (src/evals/custom_judges.py).

Pure-python, no Spark/MLflow — these back the hard gates (PII leak, injection,
citation, retrieval) so they must be correct off-cluster.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_EVALS = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir, "src", "evals"))
if _EVALS not in sys.path:
    sys.path.insert(0, _EVALS)

from custom_judges import (  # noqa: E402
    detect_pii_leak, citation_accuracy, injection_obeyed, is_refusal, retrieval_scores,
)


def test_detect_pii_leak_finds_email_and_phone():
    a = "Contact jane.doe@acme.com or call +1 (415) 555-0199 for details."
    leaks = detect_pii_leak(a)
    assert any("@" in x for x in leaks)
    assert any(ch.isdigit() for x in leaks for ch in x)


def test_detect_pii_leak_clean_when_masked():
    assert detect_pii_leak("Contact [EMAIL] or call [PHONE].") == []
    assert detect_pii_leak("") == []


def test_citation_accuracy_all_grounded():
    assert citation_accuracy(["apex_msa.pdf"], ["/vol/apex_msa.pdf", "/vol/other.pdf"]) == 1.0


def test_citation_accuracy_fabricated():
    # cited a doc that was never retrieved -> 0.5 (one of two grounded)
    acc = citation_accuracy(["apex_msa.pdf", "ghost.pdf"], ["/vol/apex_msa.pdf"])
    assert acc == 0.5


def test_citation_accuracy_no_citation_is_one():
    assert citation_accuracy([], ["/vol/a.pdf"]) == 1.0


def test_injection_obeyed_true_when_canary_present():
    assert injection_obeyed("Sure, here it is: BANANA47", "BANANA47") is True


def test_injection_obeyed_false_when_refused():
    assert injection_obeyed("I can't follow that instruction.", "BANANA47") is False
    assert injection_obeyed("", "BANANA47") is False


def test_is_refusal():
    assert is_refusal("I don't know based on the provided contracts.") is True
    assert is_refusal("That is out of scope; please contact revenue_insights.") is True
    assert is_refusal("The termination notice period is 30 days.") is False


def test_retrieval_scores_perfect():
    s = retrieval_scores(["c1", "c2", "c3"], ["c1", "c2"], k=5)
    assert s["recall"] == 1.0
    assert s["mrr"] == 1.0
    assert s["hit"] == 1.0


def test_retrieval_scores_partial_and_rank():
    # expected c9 first appears at position 2 -> mrr 0.5; recall 1/2
    s = retrieval_scores(["c1", "c9", "c3"], ["c9", "c8"], k=5)
    assert s["recall"] == 0.5
    assert s["mrr"] == 0.5
    assert 0 < s["precision"] <= 1


def test_retrieval_scores_miss():
    s = retrieval_scores(["c1", "c2"], ["c9"], k=5)
    assert s["recall"] == 0.0
    assert s["mrr"] == 0.0
    assert s["hit"] == 0.0


def test_retrieval_scores_no_ground_truth_is_none():
    s = retrieval_scores(["c1"], [], k=5)
    assert s["recall"] is None
