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
    m = meta.extract_metadata("/Volumes/x/01_Spot_Purchase_CD-2025-0142.pdf", "body text")
    assert m.contract_id == "CD-2025-0142"
    assert m.contract_type == "Spot Purchase"
    assert m.version == 1 and m.is_current is True


def test_contract_id_falls_back_to_text():
    m = meta.extract_metadata("scan.pdf", "Reference EX-2025-0076 herein.")
    assert m.contract_id == "EX-2025-0076"


def test_effective_date_extracted():
    m = meta.extract_metadata("f.pdf", "This agreement, Effective Date: 2025-04-01, between ...")
    assert m.effective_date == "2025-04-01"


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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
