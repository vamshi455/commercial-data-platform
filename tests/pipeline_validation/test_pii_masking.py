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


@pytest.mark.xfail(strict=True, reason=(
    "no PII masking implemented; expected src/contract_vector_search/masking.py::mask_pii "
    "(docs/agent-evals.md criterion 3). Remove xfail once masking exists."))
def test_mask_pii_replaces_email_and_phone():
    masked = _mask_pii()(_RAW)
    assert "jane.doe@acme.com" not in masked
    assert "[EMAIL]" in masked
    assert "555-0199" not in masked
    assert "[PHONE]" in masked


@pytest.mark.xfail(strict=True, reason=(
    "no PII masking implemented; masked chunk_text must pass detect_pii_leak "
    "(docs/agent-evals.md criterion 3). Remove xfail once masking exists."))
def test_masked_text_passes_pii_leak_gate():
    assert detect_pii_leak(_mask_pii()(_RAW)) == []


def test_pii_leak_gate_catches_the_raw_text():
    # Guardrail on the guardrail: the scorer must flag the UNMASKED text, else the
    # xfail tests above would be meaningless. This passes today.
    assert detect_pii_leak(_RAW) != []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-rxX"]))
