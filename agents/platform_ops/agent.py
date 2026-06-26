"""platform_ops agent — STUB.

Function-calling agent for platform engineering: job/pipeline run health, schema
drift, and SLA breaches. Reads Lakeflow system tables and DLT/pipeline event
logs (operational metadata only).

This is a STUB. `run_sql()` is a placeholder for a databricks-sql-connector
warehouse connection running as the read-only `cdp_ai_app_users` principal.
No secrets are embedded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

APPROVED_OBJECTS = [
    "system.lakeflow.job_run_timeline",
    "system.lakeflow.job_task_run_timeline",
    "system.lakeflow.jobs",
    "pipeline.event_log",  # DLT/pipeline event log (event_log(...) TVF or system.event_log)
]

SYSTEM_PROMPT = """\
You are the Platform Ops agent for the Commercial Data Platform.

SCOPE: operational health of jobs and Lakeflow/DLT pipelines — failed runs,
schema drift, and SLA breaches. You read OPERATIONAL METADATA ONLY:
  - system.lakeflow.job_run_timeline / job_task_run_timeline / jobs
  - DLT/pipeline event logs (expectations, flow progress, schema-drift signals)

GUARDRAILS:
  - Read-only, operational metadata only. Never read business row data or PII.
  - Decline analytics/business questions (route to the right agent).
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


def failed_runs(lookback_hours: int = 24) -> List[Dict[str, Any]]:
    """Job runs that ended in a non-success state within the lookback window."""
    query = """
        SELECT job_id, run_id, run_name, result_state, termination_code,
               period_start_time, period_end_time
        FROM system.lakeflow.job_run_timeline
        WHERE period_end_time >= current_timestamp() - make_interval(0,0,0,0,:lookback_hours)
          AND result_state IN ('FAILED', 'TIMEDOUT', 'ERROR', 'CANCELED')
        ORDER BY period_end_time DESC
    """
    return run_sql(query, {"lookback_hours": lookback_hours})


def sla_breaches(sla_minutes: int = 60, lookback_hours: int = 168) -> List[Dict[str, Any]]:
    """Runs whose wall-clock duration exceeded an SLA threshold."""
    query = """
        SELECT job_id, run_id, run_name, result_state,
               period_start_time, period_end_time,
               timestampdiff(MINUTE, period_start_time, period_end_time) AS duration_min
        FROM system.lakeflow.job_run_timeline
        WHERE period_end_time >= current_timestamp() - make_interval(0,0,0,0,:lookback_hours)
          AND timestampdiff(MINUTE, period_start_time, period_end_time) > :sla_minutes
        ORDER BY duration_min DESC
    """
    return run_sql(query, {"sla_minutes": sla_minutes, "lookback_hours": lookback_hours})


def schema_drift_events(pipeline_id: str, lookback_hours: int = 168) -> List[Dict[str, Any]]:
    """Schema-change / unexpected-column events from a pipeline's event log."""
    query = """
        SELECT timestamp, event_type, message,
               details:flow_definition.output_dataset AS dataset
        FROM event_log(TABLE(:pipeline_id))
        WHERE event_type IN ('schema_change', 'flow_definition', 'update_progress')
          AND lower(message) RLIKE 'schema|unexpected column|incompatible'
          AND timestamp >= current_timestamp() - make_interval(0,0,0,0,:lookback_hours)
        ORDER BY timestamp DESC
    """
    return run_sql(query, {"pipeline_id": pipeline_id, "lookback_hours": lookback_hours})


def job_success_rate(job_id: int, lookback_days: int = 30) -> List[Dict[str, Any]]:
    """Success rate for a job over a lookback window."""
    query = """
        SELECT job_id,
               COUNT(*)                                                      AS total_runs,
               SUM(CASE WHEN result_state = 'SUCCEEDED' THEN 1 ELSE 0 END)   AS succeeded,
               ROUND(100.0 * SUM(CASE WHEN result_state = 'SUCCEEDED' THEN 1 ELSE 0 END)
                     / NULLIF(COUNT(*), 0), 2)                               AS success_pct
        FROM system.lakeflow.job_run_timeline
        WHERE job_id = :job_id
          AND period_end_time >= current_timestamp() - make_interval(0,0,:lookback_days)
        GROUP BY job_id
    """
    return run_sql(query, {"job_id": job_id, "lookback_days": lookback_days})


def get_tools() -> List[Dict[str, Any]]:
    return [
        {"name": "failed_runs",
         "description": "Job runs that ended non-successfully within a lookback window.",
         "parameters": {"lookback_hours": "int"},
         "fn": failed_runs},
        {"name": "sla_breaches",
         "description": "Runs whose duration exceeded an SLA threshold (minutes).",
         "parameters": {"sla_minutes": "int", "lookback_hours": "int"},
         "fn": sla_breaches},
        {"name": "schema_drift_events",
         "description": "Schema-change / unexpected-column events from a pipeline event log.",
         "parameters": {"pipeline_id": "string pipeline id", "lookback_hours": "int"},
         "fn": schema_drift_events},
        {"name": "job_success_rate",
         "description": "Success rate for a job over a lookback window (days).",
         "parameters": {"job_id": "int", "lookback_days": "int"},
         "fn": job_success_rate},
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved operational objects:", APPROVED_OBJECTS)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    print("\nThis is a stub; run_sql() is not wired to a warehouse.")


if __name__ == "__main__":
    _demo()
