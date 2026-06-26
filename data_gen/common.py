"""Shared helpers for the commercial-data-platform synthetic data generators.

Pure standard-library Python 3.10+. No third-party dependencies so the
generators run anywhere (local laptop, CI, a Databricks cluster init script,
etc.).

This module provides:
  * a seeded RNG factory for reproducible output
  * source-style id generators (Salesforce 18-char, SAP numeric KUNNR-style)
  * tiny built-in "fakers" for names / emails / phones / addresses
  * date helpers for dated/incremental batches
  * CSV / JSON writers that partition by date
  * a tax-id tokenizer/mask and a sensitivity-tagging helper
  * a crosswalk registry so independent generators can share keys
    (e.g. align some ERP customers to CRM accounts for identity resolution)
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import string
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

# ---------------------------------------------------------------------------
# Reference vocabularies (small, intentionally compact built-in lists)
# ---------------------------------------------------------------------------

FIRST_NAMES: list[str] = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Priya",
    "Wei", "Mateo", "Sofia", "Aarav", "Yuki", "Omar", "Fatima", "Lars",
    "Ingrid", "Diego", "Chloe", "Hassan", "Mei", "Noah", "Olivia",
]

LAST_NAMES: list[str] = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Patel", "Nguyen", "Kim", "Chen", "Singh", "Khan", "Andersson",
    "Schmidt", "Rossi", "Dubois", "Silva", "Kowalski", "Yamamoto",
]

COMPANY_PREFIXES: list[str] = [
    "Apex", "Summit", "Vertex", "Pioneer", "Quantum", "Nimbus", "Atlas",
    "Beacon", "Cobalt", "Orchid", "Granite", "Northwind", "Cascade",
    "Meridian", "Sterling", "Helios", "Equinox", "Onyx", "Pinnacle", "Vanta",
]

COMPANY_SUFFIXES: list[str] = [
    "Industries", "Logistics", "Manufacturing", "Holdings", "Systems",
    "Solutions", "Technologies", "Partners", "Group", "Corporation",
    "Components", "Materials", "Foods", "Pharma", "Energy", "Retail",
]

STREETS: list[str] = [
    "Maple Ave", "Oak St", "Pine Rd", "Cedar Ln", "Elm Blvd", "Market St",
    "Industrial Pkwy", "Commerce Dr", "Harbor Way", "Lakeshore Dr",
    "Sunset Blvd", "Riverside Dr", "Highland Ave", "Park Pl", "Union St",
]

CITIES: list[tuple[str, str, str]] = [
    # (city, state/region, country_code)
    ("San Francisco", "CA", "US"),
    ("Austin", "TX", "US"),
    ("Chicago", "IL", "US"),
    ("New York", "NY", "US"),
    ("Boston", "MA", "US"),
    ("Toronto", "ON", "CA"),
    ("London", "LDN", "GB"),
    ("Munich", "BY", "DE"),
    ("Paris", "IDF", "FR"),
    ("Singapore", "SG", "SG"),
    ("Sydney", "NSW", "AU"),
    ("Tokyo", "13", "JP"),
    ("Sao Paulo", "SP", "BR"),
    ("Bangalore", "KA", "IN"),
]

EMAIL_DOMAINS_BY_CC: dict[str, str] = {
    "US": "com", "CA": "ca", "GB": "co.uk", "DE": "de", "FR": "fr",
    "SG": "sg", "AU": "com.au", "JP": "jp", "BR": "com.br", "IN": "in",
}

JOB_TITLES: list[str] = [
    "VP of Procurement", "Director of Operations", "Plant Manager",
    "Supply Chain Lead", "CFO", "CTO", "Buyer", "Account Manager",
    "Head of IT", "Logistics Coordinator", "Finance Analyst", "COO",
]

CURRENCIES: list[str] = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "BRL", "INR", "SGD"]

# Approx base rates expressed as units of currency per 1 USD.
CURRENCY_BASE_PER_USD: dict[str, float] = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "JPY": 150.0, "AUD": 1.52,
    "CAD": 1.36, "BRL": 5.05, "INR": 83.0, "SGD": 1.34,
}


# ---------------------------------------------------------------------------
# RNG
# ---------------------------------------------------------------------------

def make_rng(seed: int) -> random.Random:
    """Return a deterministic, isolated Random instance."""
    return random.Random(seed)


# ---------------------------------------------------------------------------
# ID generators
# ---------------------------------------------------------------------------

_SF_ALPHABET = string.ascii_letters + string.digits


def salesforce_id(rng: random.Random, prefix: str = "001") -> str:
    """Return an 18-char Salesforce-style id.

    Real Salesforce ids are 15 case-sensitive chars + a 3-char checksum;
    we approximate the shape (prefix + random body) which is plenty for
    synthetic data. ``prefix`` mimics object key-prefixes
    (001=Account, 003=Contact, 006=Opportunity, ...).
    """
    body = "".join(rng.choice(_SF_ALPHABET) for _ in range(18 - len(prefix)))
    return f"{prefix}{body}"


# Salesforce object key-prefixes used across the CRM generator.
SF_PREFIX = {
    "account": "001",
    "contact": "003",
    "lead": "00Q",
    "opportunity": "006",
    "line_item": "00k",
    "quote": "0Q0",
    "contract": "800",
    "activity": "00T",
    "case": "500",
    "user": "005",
    "territory": "0MI",
}


def sap_id(rng: random.Random, width: int = 10) -> str:
    """Return a zero-padded SAP-style numeric id (e.g. KUNNR / LIFNR / VBELN)."""
    n = rng.randint(1, 10 ** width - 1)
    return str(n).zfill(width)


def seq_sap_id(n: int, width: int = 10, base: int = 1000000) -> str:
    """Deterministic sequential SAP-style id from an integer counter."""
    return str(base + n).zfill(width)


# ---------------------------------------------------------------------------
# Faker-lite helpers
# ---------------------------------------------------------------------------

def full_name(rng: random.Random) -> tuple[str, str]:
    return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)


def company_name(rng: random.Random) -> str:
    return f"{rng.choice(COMPANY_PREFIXES)} {rng.choice(COMPANY_SUFFIXES)}"


def work_email(rng: random.Random, first: str, last: str, company: str,
               country_code: str = "US") -> str:
    domain_root = company.lower().split()[0]
    tld = EMAIL_DOMAINS_BY_CC.get(country_code, "com")
    return f"{first.lower()}.{last.lower()}@{domain_root}.{tld}"


def phone_number(rng: random.Random) -> str:
    return f"+1-{rng.randint(200, 989)}-{rng.randint(200, 989)}-{rng.randint(1000, 9999)}"


def address(rng: random.Random) -> dict[str, str]:
    city, region, cc = rng.choice(CITIES)
    return {
        "street": f"{rng.randint(1, 9999)} {rng.choice(STREETS)}",
        "city": city,
        "region": region,
        "postal_code": str(rng.randint(10000, 99999)),
        "country_code": cc,
    }


def address_str(addr: dict[str, str]) -> str:
    return (f"{addr['street']}, {addr['city']}, {addr['region']} "
            f"{addr['postal_code']}, {addr['country_code']}")


def job_title(rng: random.Random) -> str:
    return rng.choice(JOB_TITLES)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def date_range(start: date, days: int) -> list[date]:
    """Inclusive list of ``days`` dates beginning at ``start``."""
    return [start + timedelta(days=i) for i in range(days)]


def iso(d: date | datetime) -> str:
    return d.isoformat()


def dt_partition(d: date) -> str:
    """Return the ``dt=YYYY-MM-DD`` partition folder name."""
    return f"dt={d.isoformat()}"


def random_datetime_on(rng: random.Random, d: date) -> datetime:
    return datetime(d.year, d.month, d.day,
                    rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59))


def fiscal_year_of(d: date, fy_start_month: int = 2) -> int:
    """SAP-style fiscal year. Default fiscal year starts in February."""
    return d.year + 1 if d.month >= fy_start_month else d.year


def fiscal_period_of(d: date, fy_start_month: int = 2) -> int:
    """Fiscal period 1..12 given a fiscal year start month."""
    return (d.month - fy_start_month) % 12 + 1


# ---------------------------------------------------------------------------
# PII tokenization / masking + sensitivity tagging
# ---------------------------------------------------------------------------

_TOKEN_SALT = "commercial-data-platform-demo-salt"


def tokenize(value: str, salt: str = _TOKEN_SALT, length: int = 16) -> str:
    """Deterministic, non-reversible token for a sensitive value."""
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"tok_{digest[:length]}"


def mask_tax_id(value: str) -> str:
    """Emit a masked/tokenized tax id: keep last 2 chars, tokenize the rest."""
    tail = value[-2:] if len(value) >= 2 else value
    return f"{tokenize(value, length=10)}**{tail}"


def mask_email(value: str) -> str:
    """Partial email mask: a***@domain."""
    if "@" not in value:
        return tokenize(value)
    local, _, domain = value.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def last4(value: str) -> str:
    """Return only the last 4 chars, masking the rest."""
    digits = "".join(ch for ch in value if ch.isalnum())
    if len(digits) <= 4:
        return digits
    return f"****{digits[-4:]}"


# Sensitivity tags consumed by downstream Unity Catalog governance tagging.
SENSITIVITY = {
    "PII": "pii",
    "PII_DIRECT": "pii.direct_identifier",
    "PII_CONTACT": "pii.contact",
    "FINANCIAL": "financial",
    "FREE_TEXT": "free_text.may_contain_pii",
    "TOKENIZED": "tokenized",
    "PUBLIC": "public",
}


def sensitivity_tag(field_name: str, kind: str) -> dict[str, str]:
    """Return a (field -> tag) mapping suitable for a governance manifest."""
    return {"field": field_name, "sensitivity": SENSITIVITY.get(kind, kind)}


# ---------------------------------------------------------------------------
# Writers (CSV / JSON), partitioned by date
# ---------------------------------------------------------------------------

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_csv(rows: Sequence[dict[str, Any]], out_path: Path,
              fieldnames: Sequence[str] | None = None) -> Path:
    """Write rows to a CSV file, creating parent dirs."""
    _ensure_dir(out_path.parent)
    if not rows:
        out_path.write_text("")
        return out_path
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return out_path


def write_jsonl(rows: Sequence[dict[str, Any]], out_path: Path) -> Path:
    """Write rows as newline-delimited JSON."""
    _ensure_dir(out_path.parent)
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    return out_path


def write_entity(rows: Sequence[dict[str, Any]], base_out: Path, entity: str,
                 fmt: str = "csv", partition_date: date | None = None,
                 fieldnames: Sequence[str] | None = None) -> Path:
    """Write an entity either as a dated partition or a full snapshot.

    Layout for incremental loads:
        <base_out>/<entity>/dt=YYYY-MM-DD/<entity>.csv
    Full snapshots (dimensions) omit ``partition_date``:
        <base_out>/<entity>/<entity>.csv
    """
    ext = "json" if fmt == "json" else "csv"
    if partition_date is not None:
        out_path = base_out / entity / dt_partition(partition_date) / f"{entity}.{ext}"
    else:
        out_path = base_out / entity / f"{entity}.{ext}"
    if fmt == "json":
        return write_jsonl(rows, out_path)
    return write_csv(rows, out_path, fieldnames=fieldnames)


def write_json_doc(doc: Any, out_path: Path) -> Path:
    _ensure_dir(out_path.parent)
    out_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Crosswalk registry (shared keys across generators)
# ---------------------------------------------------------------------------

@dataclass
class Crosswalk:
    """Shared identity-resolution map persisted between generators.

    ``accounts`` maps a stable company key to the ids known in each system,
    enabling CRM<->ERP identity resolution downstream.
    """

    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def add_account(self, company_key: str, **ids: Any) -> None:
        self.accounts.setdefault(company_key, {})
        self.accounts[company_key].update(ids)

    def to_dict(self) -> dict[str, Any]:
        return {"meta": self.meta, "accounts": self.accounts}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Crosswalk":
        return cls(accounts=d.get("accounts", {}), meta=d.get("meta", {}))


def crosswalk_path(base_out: Path) -> Path:
    return Path(base_out) / "_crosswalk" / "crm_erp_crosswalk.json"


def save_crosswalk(xwalk: Crosswalk, base_out: Path) -> Path:
    p = crosswalk_path(base_out)
    return write_json_doc(xwalk.to_dict(), p)


def load_crosswalk(base_out: Path) -> Crosswalk | None:
    p = crosswalk_path(base_out)
    if not p.exists():
        return None
    return Crosswalk.from_dict(json.loads(p.read_text(encoding="utf-8")))


def find_crosswalk(*candidate_dirs: str | os.PathLike[str]) -> Crosswalk | None:
    """Search several base dirs for an existing crosswalk file."""
    for d in candidate_dirs:
        xw = load_crosswalk(Path(d))
        if xw is not None:
            return xw
    return None


__all__ = [
    "make_rng", "salesforce_id", "sap_id", "seq_sap_id", "SF_PREFIX",
    "full_name", "company_name", "work_email", "phone_number", "address",
    "address_str", "job_title", "date_range", "iso", "dt_partition",
    "random_datetime_on", "fiscal_year_of", "fiscal_period_of",
    "tokenize", "mask_tax_id", "mask_email", "last4", "SENSITIVITY",
    "sensitivity_tag", "write_csv", "write_jsonl", "write_entity",
    "write_json_doc", "Crosswalk", "crosswalk_path", "save_crosswalk",
    "load_crosswalk", "find_crosswalk", "CURRENCIES", "CURRENCY_BASE_PER_USD",
    "CITIES",
]
