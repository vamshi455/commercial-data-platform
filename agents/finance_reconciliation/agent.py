"""finance_reconciliation agent — STUB.

Function-calling agent for Finance: CRM-vs-ERP variance and reconciliation across
bookings, billings, and collections. Reads gold.bookings_vs_billings,
gold.collections_risk, and the curated/masked silver.invoice & silver.payment.

This is a STUB. `run_sql()` is a placeholder for a databricks-sql-connector
warehouse connection running as the read-only `cdp_ai_app_users` principal.
No secrets are embedded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

APPROVED_VIEWS = [
    "gold.bookings_vs_billings",
    "gold.collections_risk",
    "silver.invoice",
    "silver.payment",
]

# Default reconciliation tolerance (absolute currency units). Mirrors the DQ
# finance-reconciliation rule in tests/data_quality/test_dq_rules.py.
DEFAULT_TOLERANCE = 1.00

SYSTEM_PROMPT = """\
You are the Finance Reconciliation agent for the Commercial Data Platform.

SCOPE: CRM-vs-ERP variance and reconciliation across bookings, billings, and
collections. You may ONLY read these curated objects:
  - gold.bookings_vs_billings (bookings vs billings + variance)
  - gold.collections_risk (AR aging, risk score, overdue exposure)
  - silver.invoice / silver.payment (curated, masked invoice/payment grain)

GUARDRAILS:
  - Read-only. No writes, no DDL.
  - No raw bronze, no unmasked PII (tax ids, bank refs, contact emails are
    already masked upstream — do not attempt to unmask).
  - Apply the reconciliation tolerance when flagging variance.
  - Answer only from tool results.
"""


def run_sql(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Placeholder for parameterized SQL against a governed warehouse.

    Real implementation (commented):
        # from databricks import sql
        # with sql.connect(server_hostname=..., http_path=...,
        #                  credentials_provider=oauth_m2m_provider) as conn, \
        #      conn.cursor() as cur:
        #     cur.execute(query, params or {})
        #     cols = [c[0] for c in cur.description]
        #     return [dict(zip(cols, r)) for r in cur.fetchall()]
    """
    raise NotImplementedError("stub: wire run_sql() to databricks-sql-connector")


def _q(catalog: str, view: str) -> str:
    if view not in APPROVED_VIEWS:
        raise ValueError(f"view {view!r} is not in the approved allow-list")
    return f"{catalog}.{view}"


def bookings_billings_variance(catalog: str, fiscal_quarter: str,
                               tolerance: float = DEFAULT_TOLERANCE) -> List[Dict[str, Any]]:
    """Accounts whose bookings vs billings variance exceeds tolerance."""
    view = _q(catalog, "gold.bookings_vs_billings")
    query = f"""
        SELECT account_id, account_name, fiscal_quarter,
               bookings_amount, billings_amount,
               (bookings_amount - billings_amount) AS variance
        FROM {view}
        WHERE fiscal_quarter = :fiscal_quarter
          AND abs(bookings_amount - billings_amount) > :tolerance
        ORDER BY abs(bookings_amount - billings_amount) DESC
    """
    return run_sql(query, {"fiscal_quarter": fiscal_quarter, "tolerance": tolerance})


def unmatched_invoices(catalog: str, tolerance: float = DEFAULT_TOLERANCE) -> List[Dict[str, Any]]:
    """Invoices whose paid amount does not match invoiced amount within tolerance."""
    inv = _q(catalog, "silver.invoice")
    pay = _q(catalog, "silver.payment")
    query = f"""
        SELECT i.invoice_id, i.account_id, i.invoice_amount, i.currency,
               COALESCE(p.paid_amount, 0)                         AS paid_amount,
               i.invoice_amount - COALESCE(p.paid_amount, 0)      AS unpaid_variance
        FROM {inv} i
        LEFT JOIN (
            SELECT invoice_id, SUM(amount) AS paid_amount
            FROM {pay}
            GROUP BY invoice_id
        ) p ON p.invoice_id = i.invoice_id
        WHERE abs(i.invoice_amount - COALESCE(p.paid_amount, 0)) > :tolerance
        ORDER BY unpaid_variance DESC
    """
    return run_sql(query, {"tolerance": tolerance})


def collections_risk_for_variance(catalog: str, min_risk_score: float = 0.5) -> List[Dict[str, Any]]:
    """Accounts with elevated collections risk and overdue exposure."""
    view = _q(catalog, "gold.collections_risk")
    query = f"""
        SELECT account_id, account_name, ar_balance, overdue_amount,
               days_overdue, risk_score
        FROM {view}
        WHERE risk_score >= :min_risk_score
        ORDER BY overdue_amount DESC
    """
    return run_sql(query, {"min_risk_score": min_risk_score})


def get_tools() -> List[Dict[str, Any]]:
    return [
        {"name": "bookings_billings_variance",
         "description": "Accounts whose bookings-vs-billings variance exceeds tolerance for a quarter.",
         "parameters": {"fiscal_quarter": "string", "tolerance": "float currency units"},
         "fn": bookings_billings_variance},
        {"name": "unmatched_invoices",
         "description": "Invoices whose payments don't reconcile within tolerance.",
         "parameters": {"tolerance": "float currency units"},
         "fn": unmatched_invoices},
        {"name": "collections_risk_for_variance",
         "description": "Accounts with elevated collections risk and overdue exposure.",
         "parameters": {"min_risk_score": "float 0..1"},
         "fn": collections_risk_for_variance},
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved views:", APPROVED_VIEWS)
    print("Default reconciliation tolerance:", DEFAULT_TOLERANCE)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    print("\nThis is a stub; run_sql() is not wired to a warehouse.")


if __name__ == "__main__":
    _demo()
