"""customer_health agent — STUB.

Function-calling agent for Customer Success / Account Management. Reads four
curated gold views: customer_360, account_health, renewal_risk,
support_performance.

This is a STUB. `run_sql()` is a placeholder for a databricks-sql-connector
warehouse connection running as the read-only `cdp_ai_app_users` principal.
No secrets are embedded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

APPROVED_VIEWS = [
    "gold.customer_360",
    "gold.account_health",
    "gold.renewal_risk",
    "gold.support_performance",
]

SYSTEM_PROMPT = """\
You are the Customer Health agent for the Commercial Data Platform.

SCOPE: account health, renewal/churn risk, and support posture for Customer
Success and Account Management. You may ONLY read these curated gold views:
  - gold.customer_360 (account profile, ARR, segment, lifecycle)
  - gold.account_health (composite health score, drivers, trend)
  - gold.renewal_risk (renewal date, risk tier, churn probability)
  - gold.support_performance (ticket volume, SLA, CSAT, escalations)

GUARDRAILS:
  - Read-only. No writes, no DDL.
  - No raw bronze, no personal PII (contact emails, phone, addresses).
  - Decline questions outside customer health / renewal / support.
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


def accounts_at_renewal_risk(catalog: str, within_days: int = 90,
                             min_risk_tier: str = "High") -> List[Dict[str, Any]]:
    """Accounts renewing within N days at or above a risk tier."""
    view = _q(catalog, "gold.renewal_risk")
    query = f"""
        SELECT account_id, account_name, renewal_date, risk_tier,
               churn_probability, arr
        FROM {view}
        WHERE renewal_date <= date_add(current_date(), :within_days)
          AND risk_tier = :min_risk_tier
        ORDER BY churn_probability DESC, renewal_date ASC
    """
    return run_sql(query, {"within_days": within_days, "min_risk_tier": min_risk_tier})


def account_health_detail(catalog: str, account_id: str) -> List[Dict[str, Any]]:
    """Health score, drivers, and trend for a single account."""
    view = _q(catalog, "gold.account_health")
    query = f"""
        SELECT account_id, account_name, health_score, health_trend,
               top_negative_driver, top_positive_driver, scored_at
        FROM {view}
        WHERE account_id = :account_id
    """
    return run_sql(query, {"account_id": account_id})


def support_watchlist(catalog: str, min_open_escalations: int = 1) -> List[Dict[str, Any]]:
    """Accounts with open escalations and SLA/CSAT context."""
    view = _q(catalog, "gold.support_performance")
    query = f"""
        SELECT account_id, account_name, open_tickets, open_escalations,
               sla_attainment_pct, csat_avg
        FROM {view}
        WHERE open_escalations >= :min_open_escalations
        ORDER BY open_escalations DESC, sla_attainment_pct ASC
    """
    return run_sql(query, {"min_open_escalations": min_open_escalations})


def top_accounts_360(catalog: str, top_n: int = 20) -> List[Dict[str, Any]]:
    """Customer 360 snapshot for the top N accounts by ARR."""
    view = _q(catalog, "gold.customer_360")
    query = f"""
        SELECT account_id, account_name, segment, lifecycle_stage,
               arr, active_products, lifetime_value
        FROM {view}
        ORDER BY arr DESC
        LIMIT :top_n
    """
    return run_sql(query, {"top_n": top_n})


def get_tools() -> List[Dict[str, Any]]:
    return [
        {"name": "accounts_at_renewal_risk",
         "description": "Accounts renewing within N days at a given risk tier.",
         "parameters": {"within_days": "int", "min_risk_tier": "string risk tier"},
         "fn": accounts_at_renewal_risk},
        {"name": "account_health_detail",
         "description": "Health score, drivers, and trend for one account.",
         "parameters": {"account_id": "string"},
         "fn": account_health_detail},
        {"name": "support_watchlist",
         "description": "Accounts with open escalations and SLA/CSAT context.",
         "parameters": {"min_open_escalations": "int"},
         "fn": support_watchlist},
        {"name": "top_accounts_360",
         "description": "Customer 360 snapshot for the top N accounts by ARR.",
         "parameters": {"top_n": "int"},
         "fn": top_accounts_360},
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved views:", APPROVED_VIEWS)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    print("\nThis is a stub; run_sql() is not wired to a warehouse.")


if __name__ == "__main__":
    _demo()
