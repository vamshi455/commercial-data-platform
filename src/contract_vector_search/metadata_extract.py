"""Best-effort contract metadata extraction — PURE PYTHON, unit-testable.

Derives the per-chunk metadata the spec requires (``contract_id``,
``counterparty``, ``contract_type``, ``effective_date``, ``expiry_date``,
``version``) from the source filename and the parsed document text. This is
deterministic and heuristic — it does NOT call an LLM. Anything it cannot find
is returned as ``None`` and surfaced downstream (chunks are still indexed; the
missing field just can't be filtered on).

Filename convention observed in the landing volume, e.g.::

    01_Master_Sales_Agreement_CD-2025-0142.pdf -> id CD-2025-0142, type "Master Sales Agreement"
    02_Distributor_Agreement_CD-2025-0197.pdf  -> id CD-2025-0197, type "Distributor Agreement"
    03_Supply_Agreement_CF-2025-3081.pdf       -> id CF-2025-3081, type "Supply Agreement"

If the filename doesn't carry an id we fall back to scanning the text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# Contract id like CD-2025-0142, CF-2025-3081, EX-2025-0076, TD-2025-0210.
# No \b at the start: filenames prefix the id with '_' (also a word char), which
# would suppress a leading word boundary.
_ID_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}-\d{4}-\d{3,})(?![0-9])")

# Contract-type keywords -> canonical label. Checked against filename then text.
# B2B industrial-equipment manufacturer contract taxonomy (sell-side + procurement).
_TYPE_KEYWORDS = [
    ("master sales agreement", "Master Sales Agreement"),
    ("msa", "Master Sales Agreement"),
    ("distributor", "Distributor Agreement"),
    ("reseller", "Reseller Agreement"),
    ("pricing agreement", "Pricing Agreement"),
    ("pricing", "Pricing Agreement"),
    ("supply agreement", "Supply Agreement"),
    ("supply", "Supply Agreement"),
    ("non-disclosure", "NDA"),
    ("nda", "NDA"),
    ("warranty", "Warranty / SLA"),
    ("service level", "Warranty / SLA"),
    ("sla", "Warranty / SLA"),
]

# Date patterns: ISO (2025-04-01) and long form (April 1, 2025 / 1 April 2025).
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}"
    r"|[A-Z][a-z]+\s+\d{1,2},\s*\d{4}"
    r"|\d{1,2}\s+[A-Z][a-z]+\s+\d{4})"
)
_EFFECTIVE_RE = re.compile(r"(?:effective\s+date|effective\s+as\s+of)[:\s]+" + _DATE_RE.pattern, re.I)
_EXPIRY_RE = re.compile(r"(?:expir\w*|termination|end\s+date)[:\s]+" + _DATE_RE.pattern, re.I)
# "between X and Y" / "by and between X ... and Y"
_PARTIES_RE = re.compile(r"by\s+and\s+between\s+(.+?)\s+and\s+(.+?)[\.,\n]", re.I | re.S)


@dataclass(frozen=True)
class ContractMeta:
    contract_id: str | None
    counterparty: str | None
    contract_type: str | None
    effective_date: str | None
    expiry_date: str | None
    version: int
    is_current: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


def extract_contract_id(source_file: str, text: str) -> str | None:
    m = _ID_RE.search(_basename(source_file))
    if m:
        return m.group(1)
    m = _ID_RE.search(text or "")
    return m.group(1) if m else None


def extract_contract_type(source_file: str, text: str) -> str | None:
    hay = (_basename(source_file).replace("_", " ") + " " + (text or "")[:2000]).lower()
    for kw, label in _TYPE_KEYWORDS:
        if kw in hay:
            return label
    return None


def _first_date(regex: re.Pattern, text: str) -> str | None:
    m = regex.search(text or "")
    return m.group(1) if m else None


def extract_counterparty(text: str) -> str | None:
    m = _PARTIES_RE.search(text or "")
    if not m:
        return None
    # Return the second named party as the counterparty; trim legal noise.
    party = re.sub(r"\s+", " ", m.group(2)).strip(" .,\n")
    return party[:200] or None


def extract_metadata(
    source_file: str,
    text: str,
    version: int = 1,
    is_current: bool = True,
) -> ContractMeta:
    """Build the metadata record for a document from its filename + text."""
    return ContractMeta(
        contract_id=extract_contract_id(source_file, text),
        counterparty=extract_counterparty(text),
        contract_type=extract_contract_type(source_file, text),
        effective_date=_first_date(_EFFECTIVE_RE, text) or _first_date(_DATE_RE, text),
        expiry_date=_first_date(_EXPIRY_RE, text),
        version=version,
        is_current=is_current,
    )
