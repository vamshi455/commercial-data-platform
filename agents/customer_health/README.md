# Agent: customer_health

Answers Customer Success / Account Management questions about account health,
renewal and churn risk, and support posture.

## Example questions

- "Which accounts are at high renewal risk in the next 90 days?"
- "Show the health score and trend for account ACME."
- "List accounts with declining support performance and open escalations."
- "Give me the customer 360 snapshot for our top 20 accounts by ARR."

## Approved objects (read-only)

| Object | Why |
|--------|-----|
| `gold.customer_360` | Unified account profile, ARR, segment, lifecycle, usage rollups |
| `gold.account_health` | Composite health score, drivers, trend |
| `gold.renewal_risk` | Renewal date, risk tier, churn probability |
| `gold.support_performance` | Ticket volume, SLA attainment, CSAT, escalations |

PII-bearing contact fields are excluded from these curated views; the agent
sees account-level attributes, not personal contact details.

## Guardrails

- Runs as Unity Catalog group **`cdp_ai_app_users`** with `SELECT` on only the
  four views above.
- **Parameterized `SELECT`** only; bound inputs, no string interpolation.
- Declines out-of-scope or unmasked-PII requests (see `SYSTEM_PROMPT`).
- Every tool call audited (agent, user, tool, params, target).

## Architecture

Function-calling over governed SQL (Mosaic AI Agent Framework); same views back
a Databricks **Genie** space for CS analysts. **This is a stub** — `run_sql()`
is a placeholder with no credentials.
