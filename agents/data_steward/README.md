# Agent: data_steward

Answers governance / stewardship questions about lineage, metadata, freshness,
and data sensitivity across the platform.

## Example questions

- "What downstream tables depend on silver.invoice?"
- "Which gold tables have a column tagged `sensitivity = pii`?"
- "When was each gold table last refreshed, and which are stale?"
- "Show the column-level lineage feeding gold.customer_360.health_score."

## Approved objects (read-only, metadata only)

| Object | Why |
|--------|-----|
| `system.access.table_lineage` | Table-to-table upstream/downstream lineage |
| `system.access.column_lineage` | Column-to-column lineage |
| `<catalog>.information_schema.*` | Tables, columns, views catalog metadata |
| UC tag system tables (`*.information_schema.*_tags`) | metadata / lineage / freshness / sensitivity tags |

The steward agent reads **metadata only** — never row data from bronze/silver/
gold business tables, so no business PII is ever returned.

## Guardrails

- Runs as Unity Catalog group **`cdp_ai_app_users`** with `SELECT` on the system
  / information_schema metadata objects above only.
- **Parameterized `SELECT`** only.
- Declines requests for actual business row data (that's other agents' scope).
- Every tool call audited.

## Architecture

Function-calling over governed SQL (Mosaic AI Agent Framework) atop Unity
Catalog system tables and `information_schema`. **This is a stub** — `run_sql()`
is a placeholder with no credentials.
