# Agent: platform_ops

Answers platform-engineering questions about job/pipeline run health, schema
drift, and SLA breaches.

## Example questions

- "Which jobs failed in the last 24 hours and why?"
- "Show pipelines that breached their SLA this week."
- "Did any pipeline report schema drift / unexpected columns recently?"
- "What's the success rate of the daily orchestration job over 30 days?"

## Approved objects (read-only, operational metadata)

| Object | Why |
|--------|-----|
| `system.lakeflow.job_run_timeline` | Job run status, start/end, result state |
| `system.lakeflow.job_task_run_timeline` | Task-level run detail |
| `system.lakeflow.jobs` | Job catalog metadata |
| Pipeline / DLT **event log** (`event_log(...)` or `system.event_log`) | Expectations, flow progress, schema-drift / SLA signals |

Operational metadata only — no business row data, no PII.

## Guardrails

- Runs as Unity Catalog group **`cdp_ai_app_users`** with `SELECT` on the
  operational system tables / event logs above only.
- **Parameterized `SELECT`** only.
- Declines business-data / analytics questions.
- Every tool call audited.

## Architecture

Function-calling over governed SQL (Mosaic AI Agent Framework) on Lakeflow
system tables and DLT/pipeline event logs. Pairs with the
`notebooks/observability/` dashboards. **This is a stub** — `run_sql()` is a
placeholder with no credentials.
