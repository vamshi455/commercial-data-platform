"""Testing criterion 3 — PII masking actually happens (docs/agent-evals.md).

Masked chunk text is asserted across the codebase (README, job desc, both agent
system prompts, the safety-pii eval row) but NO masking code exists in
src/contract_vector_search/ — so the pipeline would leak real PII and fail its own
gate. This criterion pins the expected contract:

    src/contract_vector_search/masking.py :: mask_pii(text) -> str
    emails -> "[EMAIL]", phones -> "[PHONE]", and the result passes detect_pii_leak.

Both checks are xfail(strict=True): `mask_pii` does not exist yet, so importing it
raises ImportError (an expected xfail). They flip to XPASS — failing CI — the moment
masking is implemented at the expected location, prompting removal of the marker.
The masking function is pure, so it belongs in the off-cluster test tier here.
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

from custom_judges import detect_pii_leak  # noqa: E402  (already implemented)

_RAW = "Contact jane.doe@acme.com or call +1 (415) 555-0199 to sign."


def _mask_pii():
    """Import the expected masking function (absent today -> ImportError -> xfail)."""
    from masking import mask_pii  # expected home: src/contract_vector_search/masking.py
    return mask_pii


def test_mask_pii_replaces_email_and_phone():  # criterion 3 — CLOSED 2026-07-15
    masked = _mask_pii()(_RAW)
    assert "jane.doe@acme.com" not in masked
    assert "[EMAIL]" in masked
    assert "555-0199" not in masked
    assert "[PHONE]" in masked


def test_masked_text_passes_pii_leak_gate():
    """The independence check: the masker and the eval detector are written
    separately on purpose, so this asserts they actually agree."""
    assert detect_pii_leak(_mask_pii()(_RAW)) == []


def test_mask_pii_preserves_contract_facts():
    """Masking must not destroy the numbers the agent has to cite — contract ids,
    ISO dates, and money are digit runs but are NOT phone numbers."""
    txt = ("Per Master Sales Agreement CD-2025-0142 dated 2025-01-15, the rotary "
           "screw compressor price is USD 12,500.00 and notice is 90 days.")
    masked = _mask_pii()(txt)
    assert masked == txt, "no PII present — text must pass through untouched"


def test_mask_pii_masks_the_generated_corpus_notices():
    """End-to-end on the real corpus: the Notices article carries live PII."""
    raw = ("For Rheinhardt Industrial GmbH:\n"
           "  Email: contracts@rheinhardt-industrial.com\n"
           "  Phone: +49 89 5550 0142\n"
           "  Email: procurement@onyxlogistics.example.com\n"
           "  Phone: +1 (415) 555-0199\n")
    masked = _mask_pii()(raw)
    assert "@" not in masked
    assert "5550 0142" not in masked and "555-0199" not in masked
    assert masked.count("[EMAIL]") == 2 and masked.count("[PHONE]") == 2
    assert detect_pii_leak(masked) == []


def test_mask_pii_empty_and_none():
    assert _mask_pii()("") == ""
    assert _mask_pii()(None) == ""


def test_pii_leak_gate_catches_the_raw_text():
    # Guardrail on the guardrail: the scorer must flag the UNMASKED text, else the
    # xfail tests above would be meaningless. This passes today.
    assert detect_pii_leak(_RAW) != []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-rxX"]))
