"""PII masking for contract text — applied in silver, BEFORE chunks are embedded.

Contracts carry real contact details (the Notices article: signatory emails and
phone numbers). Those must never reach the vector index, the retrieved context,
or an agent answer. Masking here — upstream of chunking/embedding — is what makes
the agents' "chunk text is PII-masked" claim true and lets the PII hard gate
(evals: detect_pii_leak) mean "the mask failed" rather than "we never masked".

Deliberately independent of src/evals/custom_judges.py::detect_pii_leak. Sharing
one regex would make the detector blind to exactly the PII the masker misses — a
safety gate that can't fail is not a gate. The two are kept honest by a test
asserting mask_pii output passes detect_pii_leak
(tests/pipeline_validation/test_pii_masking.py), not by shared code.

Pure Python (no Spark) so it unit-tests off-cluster like the rest of the module.
"""
from __future__ import annotations

import re

EMAIL_MASK = "[EMAIL]"
PHONE_MASK = "[PHONE]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Phone CANDIDATE: a separated digit run that is NOT embedded in an alphanumeric
# token, so contract ids like `CD-2025-0142` are excluded by the boundaries. A
# candidate is only masked if it normalizes to a real phone length (10-15 digits),
# which spares ISO dates (2025-01-15 -> 8 digits), 8-digit contract numbers, and
# money amounts. Same reasoning as the eval-side detector, reached independently.
_PHONE_CAND = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{7,}\d(?![\w-])")
_PHONE_MIN_DIGITS, _PHONE_MAX_DIGITS = 10, 15


def _digit_count(s: str) -> int:
    return len(re.sub(r"\D", "", s))


def is_phone_like(s: str) -> bool:
    """True if a phone candidate has a real phone's digit count (10-15)."""
    return _PHONE_MIN_DIGITS <= _digit_count(s) <= _PHONE_MAX_DIGITS


def mask_pii(text: str) -> str:
    """Replace emails with [EMAIL] and phone numbers with [PHONE].

    Order matters: emails are masked first so their local-parts/domains can't be
    re-scanned as digit runs. Non-phone digit runs (dates, ids, amounts) are left
    untouched — masking them would destroy the contract facts the agent must cite.
    """
    if not text:
        return text or ""
    out = _EMAIL.sub(EMAIL_MASK, text)
    out = _PHONE_CAND.sub(
        lambda m: PHONE_MASK if is_phone_like(m.group()) else m.group(), out
    )
    return out
