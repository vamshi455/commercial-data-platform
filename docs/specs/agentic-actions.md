# Spec — Agentic Actions (Agents Beyond BI)

> Moving from *dashboards a human must watch* to *agents that monitor → diagnose →
> draft → get human approval → learn*. The flagship **collections agent is built +
> live in dev**; this spec is the portfolio + architecture. Related:
> [`agent-memory.md`](./agent-memory.md), [`agent-evals.md`](../agent-evals.md).

## The thesis
Today a BA builds a dashboard, **manually** hunts anomalies, writes them up, and
hands off to a human who *then* acts — slow, unscalable, most anomalies never seen.
**Replace with agents that continuously detect, diagnose, and propose specific
actions; the human is reduced to approving.** That's the business-hour saving.

## Architecture (human-in-the-loop, feedback-driven)
```
 gold metrics ─► [Monitor]  detect anomalies (rules + stats + LLM reasoning)
                    │
                    ▼
              [Diagnose]  root-cause: pull related data a BA would (correlate, explain)
                    │
                    ▼
              [Draft]  the specific action (email / task / adjustment)
                    │
             ┌──────┴──────┐
             ▼             ▼
      ops.action_queue  (status=pending)  ── guardrails + audit; NEVER auto-sent
             │
      [HUMAN approve / reject / edit]  (review_queue.sql → Databricks App later)
             │
             ▼
      ops.action_feedback  ── decision + outcome ─► learning signal (memory + evals)
```

## Shared infrastructure (build once, reuse everywhere)
- **`ops.action_queue`** — proposals awaiting approval (agent, account, signal,
  priority, action_type, diagnosis, draft, status). **Draft-only.**
- **`ops.action_feedback`** — approvals/edits/outcomes → the feedback loop that
  tunes prompts, becomes the eval set, and feeds episodic/procedural memory.
- **`review_queue.sql`** — table-based HITL (v1); a **Databricks App** is the next
  UX step. Same surface serves the **MDM steward app**.
- DDL: [`ddl/agentic_actions.sql`](../../ddl/agentic_actions.sql).

## The portfolio (same pattern, same infra)
| Agent | Gold source | Detects → Acts | Status |
|---|---|---|---|
| **Collections** ⭐ | `collections_risk` | AR risk → dunning / CSM escalation draft | **✅ built, live** |
| Revenue leakage | `bookings_vs_billings` | booked-not-billed → trace stuck order → ops task | planned |
| Churn / renewal save | `renewal_risk`, `account_health` | at-risk renewal → CSM save-play draft | planned |
| Pipeline hygiene | `revenue_pipeline` | stalled / regressed deals → sales nudge | planned |
| Pipeline self-healing | `system.lakeflow` | pipeline failure → root-cause + fix | (demoed manually) |

## Guardrails (non-negotiable)
- **Draft-only** — the agent never executes/sends; a human is always the gate.
- **Read-only** over governed gold; every proposal audited in the queue.
- Reuse **eval hard gates** (no PII leak, grounded-in-data) from `agent-evals.md`.
- Priority routing (P1/P2/P3) sends high-value/critical to a human touch (call),
  lower to automated-draft channels.

## Collections agent — reference implementation
- Code: [`agents/collections/agent.py`](../../agents/collections/agent.py) — pure
  detect/priority/routing (unit-tested) + LLM `diagnose_and_draft` + `propose_actions`.
- Job: `job_collections_agent` (ddl → seed → run). **No vector endpoint → zero
  standing cost** (gold SQL + `claude-sonnet-5`).
- Proven run: 8 accounts → 5 prioritized proposals with genuine "oversight vs
  distress" reasoning, queued `pending`.
- ⚠️ Currently on a **synthetic `collections_risk` seed** (decoupled from the
  half-done CRM cutover / D6); swap to real gold after D6.

## Roadmap
1. **Memory layer** ([`agent-memory.md`](./agent-memory.md)) — episodic recall +
   procedural few-shot from `action_feedback` (biggest value; makes it learn).
2. **Expand portfolio** — revenue-leakage + churn agents (cheap on shared infra).
3. **Databricks App** HITL UI (replaces `review_queue.sql`).
4. **Wire to real gold** post-D6; add **structured outputs** (fix occasional
   LLM-JSON misses).
5. **Continuous eval** — `action_feedback` becomes the eval/few-shot set.
