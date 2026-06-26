"""Pure-python unit tests for data-quality rule definitions.

These tests assert the SHAPE and INTERNAL CONSISTENCY of the DQ rule catalog
(`RULES`) that the Databricks DLT expectations are generated from. They run
under plain pytest with no Spark / cluster, so CI can fast-fail on a malformed
or self-contradictory rule before anything is deployed.

The full row-level enforcement runs in Databricks as DLT expectations; here we
only validate the rule *definitions* and exercise the small pure-python
validators those rules describe.
"""
from __future__ import annotations

import datetime as _dt
import re

# ---------------------------------------------------------------------------
# RULES catalog — single source of truth for the DQ definitions under test.
# ---------------------------------------------------------------------------
RULES = {
    # Columns that must never be null, by curated table.
    "not_null": {
        "silver.invoice": ["invoice_id", "account_id", "invoice_amount", "currency", "invoice_date"],
        "silver.payment": ["payment_id", "invoice_id", "amount", "payment_date"],
        "gold.bookings_vs_billings": ["account_id", "fiscal_quarter", "bookings_amount", "billings_amount"],
        "gold.collections_risk": ["account_id", "ar_balance", "risk_score"],
    },
    # Allowed value domains (enums).
    "enums": {
        "opportunity.stage": [
            "Prospecting", "Qualification", "Proposal", "Negotiation",
            "Closed Won", "Closed Lost",
        ],
        "payment.status": ["on_time", "late", "partial", "disputed", "open"],
        "renewal.risk_tier": ["Low", "Medium", "High"],
    },
    # Currency codes accepted across the platform (ISO-4217 subset).
    "currency_codes": ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "INR"],
    # Numeric sanity bounds (inclusive).
    "ranges": {
        "probability": (0.0, 1.0),
        "risk_score": (0.0, 1.0),
        "invoice_amount": (0.0, 1_000_000_000.0),
        "amount": (0.0, 1_000_000_000.0),
    },
    # Date sanity: nothing before the platform epoch, nothing absurdly future.
    "date_bounds": {
        "min": _dt.date(2015, 1, 1),
        "max_days_in_future": 365,
    },
    # Referential integrity: child column -> (parent_table, parent_key).
    "referential_integrity": {
        "silver.payment.invoice_id": ("silver.invoice", "invoice_id"),
        "gold.collections_risk.account_id": ("gold.customer_360", "account_id"),
    },
    # Finance reconciliation tolerance (absolute currency units). Mirrors the
    # finance_reconciliation agent's DEFAULT_TOLERANCE.
    "reconciliation_tolerance": 1.00,
}


# ---------------------------------------------------------------------------
# Small pure-python validators the rules describe (no Spark).
# ---------------------------------------------------------------------------
def is_within_range(value: float, bounds: tuple) -> bool:
    lo, hi = bounds
    return lo <= value <= hi


def is_valid_currency(code: str) -> bool:
    return code in RULES["currency_codes"]


def is_date_sane(d: _dt.date) -> bool:
    db = RULES["date_bounds"]
    if d < db["min"]:
        return False
    horizon = _dt.date.today() + _dt.timedelta(days=db["max_days_in_future"])
    return d <= horizon


def reconciles(bookings: float, billings: float, tolerance: float | None = None) -> bool:
    tol = RULES["reconciliation_tolerance"] if tolerance is None else tolerance
    return abs(bookings - billings) <= tol


# ---------------------------------------------------------------------------
# Structural tests over the RULES catalog.
# ---------------------------------------------------------------------------
def test_not_null_columns_are_unique_non_empty():
    for table, cols in RULES["not_null"].items():
        assert cols, f"{table} has no not-null columns"
        assert len(cols) == len(set(cols)), f"{table} has duplicate not-null columns"
        assert all(isinstance(c, str) and c for c in cols)


def test_enum_domains_non_empty_and_unique():
    for name, values in RULES["enums"].items():
        assert values, f"enum {name} is empty"
        assert len(values) == len(set(values)), f"enum {name} has duplicates"


def test_currency_codes_are_three_letter_iso():
    assert RULES["currency_codes"], "no currency codes defined"
    assert len(RULES["currency_codes"]) == len(set(RULES["currency_codes"]))
    for code in RULES["currency_codes"]:
        assert re.fullmatch(r"[A-Z]{3}", code), f"bad currency code {code!r}"


def test_ranges_are_ordered():
    for name, (lo, hi) in RULES["ranges"].items():
        assert lo < hi, f"range {name} is not ordered ({lo} >= {hi})"


def test_referential_integrity_points_to_known_parents():
    for child, (parent_table, parent_key) in RULES["referential_integrity"].items():
        assert "." in child, f"child ref {child} should be table.column"
        assert parent_table and parent_key
        # parent table should be addressable schema.table form
        assert re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", parent_table), parent_table


def test_reconciliation_tolerance_is_positive():
    assert RULES["reconciliation_tolerance"] > 0


# ---------------------------------------------------------------------------
# Behavioral tests over the validators.
# ---------------------------------------------------------------------------
def test_probability_range_enforced():
    lo, hi = RULES["ranges"]["probability"]
    assert is_within_range(0.0, (lo, hi))
    assert is_within_range(1.0, (lo, hi))
    assert not is_within_range(1.5, (lo, hi))
    assert not is_within_range(-0.1, (lo, hi))


def test_risk_score_range_enforced():
    bounds = RULES["ranges"]["risk_score"]
    assert is_within_range(0.5, bounds)
    assert not is_within_range(2.0, bounds)


def test_currency_validation():
    assert is_valid_currency("USD")
    assert is_valid_currency("EUR")
    assert not is_valid_currency("XYZ")
    assert not is_valid_currency("usd")  # case-sensitive ISO codes


def test_date_sanity():
    assert is_date_sane(_dt.date(2024, 6, 1))
    assert not is_date_sane(_dt.date(1999, 1, 1))          # before epoch
    far_future = _dt.date.today() + _dt.timedelta(days=400)
    assert not is_date_sane(far_future)                     # beyond horizon


def test_reconciliation_within_tolerance():
    assert reconciles(100.00, 100.50)        # within default 1.00
    assert reconciles(100.00, 99.01)
    assert not reconciles(100.00, 102.00)    # beyond tolerance
    assert reconciles(100.00, 105.00, tolerance=10.0)  # custom tolerance


def test_enum_membership_examples():
    stages = RULES["enums"]["opportunity.stage"]
    assert "Closed Won" in stages
    assert "Bananas" not in stages
    assert "open" in RULES["enums"]["payment.status"]
