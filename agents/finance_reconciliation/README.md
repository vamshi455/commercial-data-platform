# Agent: finance_reconciliation

Answers Finance questions about CRM-vs-ERP variance and reconciliation across
bookings, billings, and collections.

## Example questions

- "Where do CRM bookings and ERP billings disagree this quarter?"
- "List invoices with no matching payment beyond the tolerance window."
- "What's the collections risk on accounts with billings variance?"
- "Reconcile bookings vs billings by account, flagging variance over tolerance."

## Approved objects (read-only)

| Object | Why |
|--------|-----|
| `gold.bookings_vs_billings` | Period/account bookings vs billings + variance |
| `gold.collections_risk` | AR aging, collection risk score, overdue exposure |
| `silver.invoice` | Conformed invoice grain (masked/curated; no raw bronze) |
| `silver.payment` | Conformed payment grain (masked/curated; no raw bronze) |

`silver.invoice` / `silver.payment` are the **curated, masked** silver views —
tax ids, bank references, and contact emails are already tokenized/masked
upstream. The agent never reads raw bronze.

## Guardrails

- Runs as Unity Catalog group **`cdp_ai_app_users`** with `SELECT` on the four
  curated objects above only.
- **Parameterized `SELECT`** only; a configurable reconciliation **tolerance**
  is a bound parameter.
- Declines requests for unmasked PII or raw bronze.
- Every tool call audited.

## Architecture

Function-calling over governed SQL (Mosaic AI Agent Framework). Reconciliation
tolerance mirrors the DQ rule in `tests/data_quality/`. **This is a stub** —
`run_sql()` is a placeholder with no credentials.
