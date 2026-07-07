"""Pure-python unit tests for the RAG chunker (src/pipelines/silver/_text_chunking).

Runs under plain pytest — no Spark / DLT — so CI fast-fails on a broken chunking
contract before anything deploys. `_text_chunking.py` is the source of truth that
`document_chunking.py` inlines (see docs/rag-unstructured.md §3.4).
"""
from __future__ import annotations

import os
import sys

import pytest

# Make src/pipelines/silver importable without installing the package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SILVER = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir,
                                       "src", "pipelines", "silver"))
if _SILVER not in sys.path:
    sys.path.insert(0, _SILVER)

from _text_chunking import chunk_text  # noqa: E402


def test_blank_or_none_yields_no_chunks():
    assert chunk_text(None) == []
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_single_chunk():
    out = chunk_text("alpha beta gamma", max_tokens=800, overlap=100)
    assert out == ["alpha beta gamma"]


def test_long_text_splits_with_overlap():
    words = [f"w{i}" for i in range(1000)]
    out = chunk_text(" ".join(words), max_tokens=400, overlap=100)
    # step = 300 -> windows start at 0, 300, 600; the 600 window already reaches
    # the end (600+400 >= 1000) so we stop => 3 chunks, no redundant tail.
    assert len(out) == 3
    first = out[0].split()
    second = out[1].split()
    assert len(first) == 400
    # Overlap: last 100 words of chunk 0 == first 100 words of chunk 1.
    assert first[-100:] == second[:100]


def test_covers_all_words_in_order():
    words = [f"w{i}" for i in range(1000)]
    out = chunk_text(" ".join(words), max_tokens=400, overlap=100)
    seen = []
    for c in out:
        seen.extend(c.split())
    # Every source word appears (dedup preserves first-seen order).
    assert set(seen) == set(words)
    assert seen[0] == "w0" and words[-1] in out[-1].split()


def test_no_overlap_tiles_exactly():
    words = [f"w{i}" for i in range(10)]
    out = chunk_text(" ".join(words), max_tokens=5, overlap=0)
    assert out == ["w0 w1 w2 w3 w4", "w5 w6 w7 w8 w9"]


def test_last_window_not_duplicated_on_exact_multiple():
    # 900 words, window 300, step 300 -> exactly 3 chunks, no empty trailing one.
    words = [f"w{i}" for i in range(900)]
    out = chunk_text(" ".join(words), max_tokens=300, overlap=0)
    assert len(out) == 3


@pytest.mark.parametrize("bad", [0, -1])
def test_invalid_max_tokens_raises(bad):
    with pytest.raises(ValueError):
        chunk_text("a b c", max_tokens=bad)


@pytest.mark.parametrize("bad", [-1, 800, 900])
def test_invalid_overlap_raises(bad):
    with pytest.raises(ValueError):
        chunk_text("a b c", max_tokens=800, overlap=bad)
