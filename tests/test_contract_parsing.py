"""Unit tests for parsing.py — text + real page numbers from ai_parse_document.

Regression-tests the JSON-blob bug that reached production: the old inline
`_extract_text` probed for shapes the parser doesn't emit and fell back to
`str(parsed)`, so `chunk_text` was filled with the raw parse JSON. Every test
here exists because something real broke.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_MODULE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "src", "contract_vector_search")
)
sys.path.insert(0, _MODULE_DIR)

import parsing  # noqa: E402


def _result(elements):
    """An ai_parse_document-shaped result (as the JSON string it really returns)."""
    return json.dumps({"document": {"elements": elements}})


def _el(content, page_id, eid=0):
    return {"id": eid, "type": "text", "confidence": 0.99,
            "bbox": [{"coord": [110, 97, 415, 143], "page_id": page_id}],
            "content": content}


# --------------------------------------------------------------------------- #
# extract_elements — the shape that actually ships
# --------------------------------------------------------------------------- #
def test_extracts_content_and_1_based_page_from_elements():
    parsed = _result([_el("ARTICLE I", 0), _el("ARTICLE V", 1)])
    assert parsing.extract_elements(parsed) == [("ARTICLE I", 1), ("ARTICLE V", 2)]


def test_accepts_a_json_string_result():
    # ai_parse_document hands back a JSON *string* on this runtime; the old
    # helper did dict(parsed) -> TypeError -> str(parsed) -> raw JSON in chunk_text.
    out = parsing.extract_elements(_result([_el("body", 0)]))
    assert out == [("body", 1)]


def test_accepts_a_dict_result():
    parsed = json.loads(_result([_el("body", 0)]))
    assert parsing.extract_elements(parsed) == [("body", 1)]


class _FakeVariantVal:
    """Stand-in for pyspark's VariantVal — what ai_parse_document ACTUALLY returns.

    Mirrors the two traits that caused the original bug: dict() raises, and
    __str__ renders the JSON (so a str() fallback looks like it "worked").
    """
    def __init__(self, payload: str):
        self._payload = payload

    def toJson(self) -> str:
        return self._payload

    def __str__(self) -> str:      # the trap the old helper fell into
        return self._payload

    def keys(self):                # makes dict(x) attempt -> and fail, like the real type
        raise TypeError("VariantVal is not iterable")


def test_accepts_spark_variantval():
    """THE regression: DBR returns VariantVal. dict() raises, the old code caught
    that and str()'d it into raw JSON, silently embedding JSON as chunk_text."""
    parsed = _FakeVariantVal(_result([_el("ARTICLE I", 0), _el("ARTICLE V", 1)]))
    assert parsing.extract_elements(parsed) == [("ARTICLE I", 1), ("ARTICLE V", 2)]


def test_variantval_with_topython_dict():
    class _V:
        def toPython(self):
            return json.loads(_result([_el("body", 1)]))
    assert parsing.extract_elements(_V()) == [("body", 2)]


def test_unparseable_variant_raises_not_str_fallback():
    with pytest.raises(parsing.ParseShapeError):
        parsing.extract_elements(_FakeVariantVal("<<not json>>"))


def test_skips_empty_elements():
    parsed = _result([_el("real", 0), _el("   ", 0), _el("", 1)])
    assert parsing.extract_elements(parsed) == [("real", 1)]


def test_never_returns_raw_json_blob_for_an_unknown_shape():
    """The whole point: fail loudly instead of silently embedding JSON."""
    with pytest.raises(parsing.ParseShapeError):
        parsing.extract_elements(json.dumps({"unexpected": {"foo": "bar"}}))


def test_raises_on_none_and_garbage():
    with pytest.raises(parsing.ParseShapeError):
        parsing.extract_elements(None)
    with pytest.raises(parsing.ParseShapeError):
        parsing.extract_elements("not json at all")


def test_falls_back_to_pages_shape():
    parsed = json.dumps({"document": {"pages": [{"content": "p one"}, {"content": "p two"}]}})
    assert parsing.extract_elements(parsed) == [("p one", 1), ("p two", 2)]


def test_falls_back_to_document_text_shape():
    parsed = json.dumps({"document": {"text": "whole doc"}})
    assert parsing.extract_elements(parsed) == [("whole doc", 1)]


# --------------------------------------------------------------------------- #
# page mapping — replaces the _page_for stub that always returned 1
# --------------------------------------------------------------------------- #
def test_page_map_offsets_track_the_joined_text():
    els = [("aaa", 1), ("bbb", 2)]
    text = parsing.elements_to_text(els)
    assert text == "aaa\n\nbbb"
    pm = parsing.build_page_map(els)
    assert parsing.page_at_offset(pm, 0) == 1     # in "aaa"
    assert parsing.page_at_offset(pm, 6) == 2     # in "bbb"


def test_page_for_chunk_finds_the_right_page():
    els = [("alpha " * 60, 1), ("bravo " * 60, 2), ("charlie " * 60, 3)]
    text = parsing.elements_to_text(els)
    pm = parsing.build_page_map(els)
    assert parsing.page_for_chunk(text, pm, "bravo " * 30) == 2
    assert parsing.page_for_chunk(text, pm, "charlie " * 30) == 3


def test_page_for_chunk_ignores_prepended_overlap():
    """A chunk starts with the PREVIOUS page's overlap tail; the page must come
    from the chunk's own content, not that tail — which is why we probe the middle."""
    els = [("alpha " * 60, 1), ("bravo " * 60, 2)]
    text = parsing.elements_to_text(els)
    pm = parsing.build_page_map(els)
    chunk = ("alpha " * 5) + ("bravo " * 60)   # overlap tail + real page-2 content
    assert parsing.page_for_chunk(text, pm, chunk) == 2


def test_page_for_chunk_degrades_to_1_when_unlocatable():
    assert parsing.page_for_chunk("text", [], "anything") == 1
    assert parsing.page_for_chunk("", [(4, 1)], "") == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
