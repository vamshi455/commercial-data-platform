# Agent: revenue_insights

Answers RevOps / Finance questions about the sales pipeline and how bookings
convert to billings.

## Example questions

- "What's the total open pipeline by stage for this quarter?"
- "Which deals slipped out of the current quarter?"
- "Show bookings vs billings variance by region for the last 3 months."
- "What's our weighted forecast for the top 10 accounts?"

## Approved objects (read-only)

| Object | Why |
|--------|-----|
| `gold.revenue_pipeline` | Open/won/lost pipeline with stage, amount, probability, close date, owner, region |
| `gold.bookings_vs_billings` | Period-grain bookings vs billings, recognized revenue, variance |

The agent may read **only** these two curated gold views. No bronze, no silver,
no PII columns (owner is exposed at team/region grain, not personal contact data).

## Guardrails

- Runs as the Unity Catalog group **`cdp_ai_app_users`**, which is granted
  `SELECT` on exactly the two views above.
- Tools issue **parameterized `SELECT`** statements only; inputs are bound, not
  interpolated.
- Out-of-scope or PII requests are declined (see `SYSTEM_PROMPT` in `agent.py`).
- Every tool call is audited (agent, user, tool, params, target).

## Architecture

Function-calling over governed SQL (Mosaic AI Agent Framework). The same gold
views back a Databricks **Genie** space for ad-hoc analyst use. **This is a
stub** — `run_sql()` is a placeholder and carries no credentials.
