"""revenue_insights agent — STUB.

Function-calling agent that answers RevOps/Finance questions over two curated
gold views: gold.revenue_pipeline and gold.bookings_vs_billings.

This is a STUB. `run_sql()` is a placeholder: the real implementation connects
to a Databricks SQL warehouse with the databricks-sql-connector, running as a
principal in the Unity Catalog group `cdp_ai_app_users` (read-only on the
approved views). No secrets are embedded here.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Catalog is environment-specific (cdp_dev / cdp_qa / cdp_prod) and injected at
# runtime; views are addressed as <catalog>.gold.<view>.
APPROVED_VIEWS = [
    "gold.revenue_pipeline",
    "gold.bookings_vs_billings",
]

SYSTEM_PROMPT = """\
You are the Revenue Insights agent for the Commercial Data Platform.

SCOPE: pipeline, bookings, and billings analytics for RevOps and Finance.
You may ONLY read these curated gold views:
  - gold.revenue_pipeline (open/won/lost pipeline by stage, amount, probability,
    close date, owner team, region)
  - gold.bookings_vs_billings (period bookings vs billings, recognized revenue,
    variance)

GUARDRAILS:
  - Read-only. Never attempt INSERT/UPDATE/DELETE/DDL.
  - Never request raw bronze tables or personal PII (emails, phone, addresses).
  - If a question is outside pipeline/bookings/billings, politely decline and
    point the user to the right agent.
  - Always answer from tool results; do not invent numbers.
"""


# --- SQL execution placeholder --------------------------------------------
def run_sql(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Placeholder for parameterized SQL execution against a governed warehouse.

    Real implementation (commented) — credentials come from the environment /
    Databricks secrets, never from source:

        # from databricks import sql
        # with sql.connect(
        #     server_hostname=os.environ["DATABRICKS_HOST"],
        #     http_path=os.environ["DATABRICKS_HTTP_PATH"],
        #     credentials_provider=oauth_m2m_provider,  # cdp_ai_app_users SP
        # ) as conn, conn.cursor() as cur:
        #     cur.execute(query, params or {})
        #     cols = [c[0] for c in cur.description]
        #     return [dict(zip(cols, row)) for row in cur.fetchall()]
    """
    raise NotImplementedError("stub: wire run_sql() to databricks-sql-connector")


def _catalog_prefix(catalog: str, view: str) -> str:
    if view not in APPROVED_VIEWS:
        raise ValueError(f"view {view!r} is not in the approved allow-list")
    return f"{catalog}.{view}"


# --- Tool functions (each runs one parameterized SELECT) ------------------
def pipeline_by_stage(catalog: str, fiscal_quarter: str, region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Open pipeline amount and deal count grouped by stage for a fiscal quarter."""
    view = _catalog_prefix(catalog, "gold.revenue_pipeline")
    query = f"""
        SELECT stage,
               COUNT(*)                 AS deal_count,
               SUM(amount)              AS total_amount,
               SUM(amount * probability) AS weighted_amount
        FROM {view}
        WHERE fiscal_quarter = :fiscal_quarter
          AND status = 'Open'
          AND (:region IS NULL OR region = :region)
        GROUP BY stage
        ORDER BY total_amount DESC
    """
    return run_sql(query, {"fiscal_quarter": fiscal_quarter, "region": region})


def bookings_vs_billings(catalog: str, period_start: str, period_end: str,
                         region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Bookings, billings, and variance by period for an optional region."""
    view = _catalog_prefix(catalog, "gold.bookings_vs_billings")
    query = f"""
        SELECT period,
               region,
               SUM(bookings_amount)  AS bookings,
               SUM(billings_amount)  AS billings,
               SUM(bookings_amount - billings_amount) AS variance
        FROM {view}
        WHERE period BETWEEN :period_start AND :period_end
          AND (:region IS NULL OR region = :region)
        GROUP BY period, region
        ORDER BY period
    """
    return run_sql(query, {"period_start": period_start, "period_end": period_end, "region": region})


def get_tools() -> List[Dict[str, Any]]:
    """Return the tool catalog (schema + callable) for the agent runtime."""
    return [
        {
            "name": "pipeline_by_stage",
            "description": "Open pipeline amount, deal count, and weighted amount by stage for a fiscal quarter.",
            "parameters": {
                "fiscal_quarter": "string, e.g. 'FY26-Q2'",
                "region": "optional string region filter",
            },
            "fn": pipeline_by_stage,
        },
        {
            "name": "bookings_vs_billings",
            "description": "Bookings vs billings and variance between two period dates, optionally by region.",
            "parameters": {
                "period_start": "date string YYYY-MM-DD",
                "period_end": "date string YYYY-MM-DD",
                "region": "optional string region filter",
            },
            "fn": bookings_vs_billings,
        },
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved views:", APPROVED_VIEWS)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    print("\nThis is a stub; run_sql() is not wired to a warehouse.")


if __name__ == "__main__":
    _demo()
