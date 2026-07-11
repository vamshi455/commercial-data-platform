# Agent: collections (agentic action — beyond BI)

The flagship **anomaly → action** agent: instead of a dashboard a human must watch,
it continuously **monitors** AR risk, **diagnoses** the likely cause, **drafts** a
tailored action, and queues it for a **human to approve** — then **learns** from the
decision. Saves the finance analyst the hunt-and-write; scales to every account.

## Loop
```
gold.collections_risk ─► detect actionable (rules) ─► LLM diagnose + draft
      ─► ops.action_queue (status=pending)  ─► HUMAN approve/reject/edit
      ─► ops.action_feedback (decision + outcome) ─► improves future drafts
```

## What it reads / writes
| | |
|---|---|
| Reads | `gold.collections_risk` (governed; synthetic seed for now, real after D6) |
| Writes | `ops.action_queue` (proposals, **draft-only**), never an external system |
| Model | `databricks-claude-sonnet-5` (diagnose + draft) — **no vector endpoint needed** |

## Guardrails
- **Draft-only** — the agent never sends; a human is always the gate (`review_queue.sql`).
- Read-only over governed gold; every proposal audited in the queue.
- Priority (P1/P2/P3) routes high-value/critical accounts to a CSM call, others to a dunning email.
- Feedback (`ops.action_feedback`) is the learning signal — approvals/edits/outcomes tune prompts + become the eval set.

## Run
```bash
databricks bundle run job_collections_agent -t dev   # ddl → seed → agent → queue
```
Then review in `notebooks/agentic_actions/review_queue.sql`.

## Portfolio (same shared infra)
`action_queue` + `action_feedback` + the review surface are **reused** by the next
action agents — revenue-leakage (`bookings_vs_billings`), churn/renewal-save
(`renewal_risk`), pipeline hygiene (`revenue_pipeline`) — and the MDM steward app.
