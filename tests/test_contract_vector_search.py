"""Unit tests for the contract_vector_search module (pure logic — no Spark).

Covers the spec's required tests:
  * chunking: separator behavior, overlap, chunk_id determinism
  * amendment/versioning MERGE logic (detect_amendments)
Plus metadata extraction and config derivation.

The module lives in src/contract_vector_search/; we add it to sys.path so the
pure modules import cleanly off-cluster.
"""
from __future__ import annotations

import hashlib
import os
import sys

import pytest

_MODULE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "src", "contract_vector_search")
)
sys.path.insert(0, _MODULE_DIR)

import chunking  # noqa: E402
import versioning  # noqa: E402
import metadata_extract as meta  # noqa: E402
import config as cfgmod  # noqa: E402


# --------------------------------------------------------------------------- #
# chunking
# --------------------------------------------------------------------------- #
def test_chunk_id_is_deterministic_and_matches_spec():
    a = chunking.make_chunk_id("/Volumes/c/s/raw/f.pdf", 3)
    b = chunking.make_chunk_id("/Volumes/c/s/raw/f.pdf", 3)
    assert a == b
    # Must equal sha2(source_file || ':' || seq, 256) — same as Spark sha2(...,256).
    expected = hashlib.sha256(b"/Volumes/c/s/raw/f.pdf:3").hexdigest()
    assert a == expected


def test_chunk_id_varies_by_seq_and_file():
    base = chunking.make_chunk_id("f.pdf", 0)
    assert base != chunking.make_chunk_id("f.pdf", 1)
    assert base != chunking.make_chunk_id("g.pdf", 0)


def test_empty_text_yields_no_chunks():
    assert chunking.chunk_text("") == []
    assert chunking.chunk_text("   \n  ") == []


def test_chunks_are_contiguously_sequenced():
    text = ("ARTICLE I\n" + "clause body. " * 300) + ("\nARTICLE II\n" + "more. " * 300)
    chunks = chunking.chunk_text(text, target_tokens=100, overlap_tokens=10)
    assert len(chunks) > 1
    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_prefers_clause_separator_over_midsentence():
    # Two clauses, each under target -> should split on the ARTICLE boundary,
    # keeping each clause intact rather than cutting mid-sentence.
    text = "ARTICLE I\nThe seller shall deliver crude oil.\nARTICLE II\nThe buyer shall pay."
    chunks = chunking.chunk_text(text, target_tokens=12, overlap_tokens=0)
    assert any("ARTICLE II" in c.text for c in chunks)
    # No chunk should start in the middle of "shall deliver" etc. — boundaries
    # land on ARTICLE headers.
    assert chunks[0].text.startswith("ARTICLE")


def test_overlap_prepends_previous_context():
    text = "SECTION 1\n" + "alpha " * 200 + "\nSECTION 2\n" + "bravo " * 200
    no_ov = chunking.chunk_text(text, target_tokens=80, overlap_tokens=0)
    ov = chunking.chunk_text(text, target_tokens=80, overlap_tokens=20)
    # With overlap, total character volume grows (context is duplicated).
    assert sum(len(c.text) for c in ov) > sum(len(c.text) for c in no_ov)


# --------------------------------------------------------------------------- #
# versioning / amendments
# --------------------------------------------------------------------------- #
def test_brand_new_contract_is_not_an_amendment():
    bumps = versioning.detect_amendments(current=[], incoming=[("CD-1", "a.pdf")])
    assert bumps == {}


def test_same_file_rerun_is_not_an_amendment():
    current = [("CD-1", "a.pdf", 1)]
    bumps = versioning.detect_amendments(current, incoming=[("CD-1", "a.pdf")])
    assert bumps == {}  # idempotent re-run must not bump versions


def test_new_file_for_existing_contract_bumps_version():
    current = [("CD-1", "a.pdf", 1)]
    bumps = versioning.detect_amendments(current, incoming=[("CD-1", "b.pdf")])
    assert bumps == {"CD-1": 2}


def test_amendment_uses_max_existing_version_plus_one():
    current = [("CD-1", "a.pdf", 1), ("CD-1", "b.pdf", 2)]
    bumps = versioning.detect_amendments(current, incoming=[("CD-1", "c.pdf")])
    assert bumps == {"CD-1": 3}


def test_none_contract_id_ignored():
    bumps = versioning.detect_amendments([(None, "a.pdf", 1)], [(None, "b.pdf")])
    assert bumps == {}


# --------------------------------------------------------------------------- #
# metadata extraction
# --------------------------------------------------------------------------- #
def test_contract_id_from_filename():
    m = meta.extract_metadata("/Volumes/x/01_Master_Sales_Agreement_CD-2025-0142.pdf", "body text")
    assert m.contract_id == "CD-2025-0142"
    assert m.contract_type == "Master Sales Agreement"
    assert m.version == 1 and m.is_current is True


def test_contract_id_falls_back_to_text():
    m = meta.extract_metadata("scan.pdf", "Reference EX-2025-0076 herein.")
    assert m.contract_id == "EX-2025-0076"


def test_counterparty_survives_a_pdf_line_wrap():
    """Real PDFs hard-wrap prose, so the parties clause spans lines. The bare
    newline used to terminate the regex, truncating "Caldwell Engineering
    Partners" to "Caldwell"."""
    text = ("This NDA (the \"Agreement\") is made by and between Rheinhardt "
            "Industrial GmbH and Caldwell\nEngineering Partners.")
    assert meta.extract_counterparty(text) == "Caldwell Engineering Partners"


def test_counterparty_still_bounded_by_a_paragraph_break():
    # A blank line is a real boundary — it must still stop the match.
    text = ("made by and between Rheinhardt Industrial GmbH and Onyx Logistics GmbH\n\n"
            "ARTICLE I - SCOPE")
    assert meta.extract_counterparty(text) == "Onyx Logistics GmbH"


def test_counterparty_unwrapped_single_line():
    text = "made by and between Rheinhardt Industrial GmbH and Vertex Components AG."
    assert meta.extract_counterparty(text) == "Vertex Components AG"


def test_effective_date_extracted():
    m = meta.extract_metadata("f.pdf", "This agreement, Effective Date: 2025-04-01, between ...")
    assert m.effective_date == "2025-04-01"


def test_filename_type_beats_a_type_mentioned_in_the_body():
    # An SLA that references the MSA in its body must stay a Warranty/SLA — the
    # filename is authoritative. (Regression: body text used to outvote it.)
    m = meta.extract_metadata(
        "/v/06_Warranty_SLA_Agreement_TD-2025-0210.pdf",
        "This Agreement runs concurrently with the Master Sales Agreement.",
    )
    assert m.contract_type == "Warranty / SLA"


def test_nda_not_misread_as_pricing_when_body_mentions_pricing():
    # NDAs protect "customer lists and pricing" — must not classify as Pricing.
    m = meta.extract_metadata(
        "/v/05_Non-Disclosure_Agreement_EX-2025-0076.pdf",
        "Confidential Information includes customer lists, and pricing.",
    )
    assert m.contract_type == "NDA"


def test_longest_keyword_wins_over_list_order():
    # "pricing agreement" must beat the shorter "pricing" alias.
    m = meta.extract_metadata("/v/04_Pricing_Agreement_CD-2025-0233.pdf", "body")
    assert m.contract_type == "Pricing Agreement"


def test_body_text_still_classifies_when_filename_is_uninformative():
    # Scanned/opaque filename -> fall back to the body.
    m = meta.extract_metadata("/v/scan_0001.pdf", "This Distributor Agreement is made ...")
    assert m.contract_type == "Distributor Agreement"


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def test_config_derives_names_from_catalog_schema():
    c = cfgmod.load_config({"catalog": "cdp_dev"})
    assert c.raw_volume == "/Volumes/cdp_dev/contracts/raw_contract_files"
    assert c.gold_table == "cdp_dev.contracts.gold_contract_chunks"
    assert c.index_name == "cdp_dev.contracts.contract_chunks_index"
    assert c.embedding_model == "databricks-gte-large-en"


def test_config_defaults_and_overrides():
    c = cfgmod.load_config({"catalog": "cdp_prod", "vs_endpoint": "custom_ep"})
    assert c.catalog == "cdp_prod"
    assert c.endpoint == "custom_ep"
    assert c.checkpoint("bronze") == "/Volumes/cdp_prod/contracts/checkpoints/bronze"


# --------------------------------------------------------------------------- #
# page numbers (criterion 5b — docs/agent-evals.md)
# --------------------------------------------------------------------------- #
def test_silver_uses_real_page_extraction_not_a_stub():  # criterion 5 — CLOSED 2026-07-16
    """Silver must derive pages from the parser (parsing.page_for_chunk), not a
    hardcoded constant. `_page_for` used to `return 1` forever, so every citation's
    page was fiction. Page logic + its tests now live in tests/test_contract_parsing.py.
    """
    import ast
    silver = os.path.join(_MODULE_DIR, "02_silver_parse_chunk.py")
    with open(silver, encoding="utf-8") as fh:
        src = fh.read()
    assert "page_for_chunk" in src, "silver no longer derives real page numbers"
    tree = ast.parse(src)
    stub = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_page_for"), None)
    assert stub is None, "the _page_for constant stub is back — citations would be fabricated"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-rxX"]))
