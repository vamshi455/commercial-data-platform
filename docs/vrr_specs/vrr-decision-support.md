# VRR Decision-Support — Master Design

**Status:** design (supersedes the "VRR chat agent" framing for production use)
**Reframe:** from a *VRR reasoning chat agent* → an **app-centric Reservoir Management
decision-support system**. The VRR number is the *trigger*; the product value is the
**governed decision** to adjust a valve/pressure — grounded in deterministic math,
engineers' tacit knowledge (RAG), historical precedent, and **multi-level human approval**.
Chat/Genie remains, but **secondary** (embedded ad-hoc Q&A inside the app).

Builds on what already exists in this repo:
- Deterministic VRR engine + value-level lineage (`src/vrr_agent/*`, `vrr_agent.lineage_*`).
- The **monitor → diagnose → draft → approve → learn** pattern from `agents/collections/`.
- PDF → parse → chunk → embed → Vector Search from `src/contract_vector_search/`.
- Input-confidence signals already emitted: `pvt_method`, `missing_input`, `any_extrapolated`.
- `cdp_*` UC groups for role-based approval.

---

## 1. End-to-end flow

```mermaid
flowchart TD
    A["job_vrr_build → anomaly detected (VRR out of band / mismatches)"] --> AUD
    AUD["① INPUT-AUDIT GATE (IPTC-style model-assessment)<br/>real reservoir signal, or DATA artifact?<br/>extrapolated PVT · missing pressure · stale factor · legacy mismatch"]
    AUD -->|data artifact| FIX["route to Data Steward → fix inputs → re-run (NO valve rec)"]
    AUD -->|clean inputs| DIAG["DIAGNOSE (deterministic)<br/>VRR_DECOMPOSE + VRR_LINEAGE/IMPACT → driver + wells"]
    DIAG --> KN["KNOWLEDGE + HISTORY<br/>engineer PDFs (vector search) + past adjustments on this pattern"]
    KN --> REC["RECOMMEND (math + knowledge + precedent)<br/>bounded valve/pressure change, fully cited"]
    REC --> W
    subgraph W["② THE APP — multi-level approval (primary surface)"]
      A1["RM Analyst: reviews evidence, recommends change"] -->
      A2["Reservoir Manager: approves final change (safety limits)"] -->
      A3["Site/Field Engineer: operational + safety checks → executes"]
    end
    A3 --> OUT["outcome recorded → ③ adjustment_history"]
    OUT -->|learn: precedent + threshold tuning| KN
```

---

## 2. Phase-1 vertical slices (build these first — they unlock the rest)

### Slice A — Input-audit gate (inspired by Reservoir Model Assessment Agents, IPTC 26IPTC/794894)
Before ANY recommendation, validate the inputs feeding the VRR — auto-audit, the way the
paper auto-audits simulation-model inputs. Reuse the signals already on `completion_contrib`
(`pvt_method` extrapolated, `missing_input`, `any_extrapolated`) + a legacy/reconciliation
mismatch check. Output a verdict per flagged pattern:
- **DATA_ARTIFACT** → route to Data Steward (fix inputs, re-run); do **not** propose a valve change.
- **REAL_SIGNAL** → proceed to diagnose + recommend.
This is the single highest-value guardrail: never adjust a valve because of a PVT-extrapolation bug.
Artifact: `src/vrr_agent/audit.py` (rules) + `vrr_agent.input_audit` table + a `VRR_AUDIT` surface.

### Slice B — Multi-stage `action_queue` (staged approval state machine + RBAC)
Extend the collections `action_queue` idea into a **staged workflow**; each stage = a role + audit,
all seeing the same evidence bundle (decompose driver, lineage proof, knowledge citations,
historical precedent, audit verdict).

| Stage (status) | Role (UC group) | Action | Gate |
|---|---|---|---|
| `proposed` | system | draft rec + evidence bundle | input-audit = REAL_SIGNAL |
| `analyst_review` | `cdp_rm_analysts` | Analyst edits/recommends | must cite evidence |
| `rm_approved` | `cdp_reservoir_mgrs` | RM approves final change | within safety limits |
| `site_check` | `cdp_field_engineers` | operational/safety checks | valve rate · injection pressure · fracture gradient |
| `executed` → `outcome` | field | adjustment made, result recorded | logged to history |

Tables: `vrr_agent.action_queue` (staged) + `vrr_agent.action_audit` (every transition, who/when).
(Roles are a sound default; refine during app iteration — they're status values + RBAC.)

### Slice C — Knowledge-ingestion index (reuse `contract_vector_search`)
Ingest engineers' tacit knowledge as PDFs → parse → chunk → embed (`databricks-gte-large-en`)
→ Vector Search index `reservoir_knowledge`. Near-verbatim reuse of `src/contract_vector_search/`.
**Frame of what the knowledge carries** (the "in their brain" taxonomy):

| Knowledge type | Example | Role in the decision |
|---|---|---|
| Well/reservoir behavior | "PROD_WELL_003 gasses out above 2800 psi" | qualifies the free-gas driver |
| Operational constraints | valve max rate; well on ESP/artificial lift | bounds the recommendation |
| Safety / regulatory | max injection pressure; fracture gradient; MER | hard limits on the change |
| Field / geologic context | fault compartmentalization; aquifer support; offset-well interference | explains VRR move beyond the math |
| Adjustment heuristics | "don't chase daily VRR noise; act on 3-mo trend" | when to act / not |
| Prior studies | PVT lab reports; sim-model assumptions; surveillance plots | validates inputs (feeds Slice A) |

---

## 3. Recommendation = math + knowledge + precedent
The proposal is assembled deterministically-then-narrated (same "LLM drafts, deterministic gate"
principle):
- **Math** (deterministic): `VRR_DECOMPOSE` → what changed & why; `VRR_LINEAGE/IMPACT` → which wells/inputs.
- **Knowledge** (RAG): retrieve relevant engineer notes/constraints/heuristics from `reservoir_knowledge`.
- **Precedent** (history): retrieve similar past anomalies + the adjustment made + its outcome.
→ a **bounded** valve/pressure change with citations to all three. The LLM phrases; it never
computes the numbers and may only claim a driver the decomposition supports.

## 4. Historical adjustments (case-based reasoning + learning)
`vrr_agent.adjustment_history(pattern, anomaly, driver, change_made, pre_vrr, post_vrr, approved_by, outcome, ts)`
- **At recommend-time**: "last 3 times this pattern over-replaced from a pressure drop, injection
  was cut X% → VRR settled to Y" → precedent cited in the proposal.
- **As learning**: outcomes tune thresholds + the recommended magnitude (did the last change over/under-correct?).

## 5. Reuse map (this is an extension, not a rebuild)
| Need | Reuse |
|---|---|
| PDF → vector knowledge | `src/contract_vector_search/` (RAG, VS index, masking) |
| draft → approve → learn + queue | `agents/collections/` |
| deterministic diagnosis | VRR tools (`VRR_DECOMPOSE`/`LINEAGE`/`IMPACT`) |
| input-confidence flags | `completion_contrib.pvt_method`/`missing_input`, `any_extrapolated` |
| role-based stages | `cdp_*` UC groups |
| app shell | the §9.5 report app pattern (Streamlit / Databricks App) |
| logged transformation ("how is it calc'd") | `vrr_agent.pattern_vrr_log` + `VRR_EXPLAIN_CALC` |

## 5.1 Agent tools inventory (8 tools, all deterministic)
Backed by 4 UC functions (`vrr_get`, `vrr_lineage`, `vrr_impact`, `vrr_trace`).

| # | Tool | Purpose | Backing |
|---|---|---|---|
| 1 | `VRR_LIST_PATTERNS` | discovery — what patterns/periods exist | `pattern_vrr_monthly` |
| 2 | `VRR_OVERVIEW` | portfolio — all patterns vs target, ranked by drift | `pattern_vrr_*` |
| 3 | `VRR_GET` | a specific VRR value + target/prior/peer refs | `vrr_get` UC fn |
| 4 | `VRR_DECOMPOSE` | exact LMDI attribution ("why did it change") | `completion_contrib` |
| 5 | `VRR_LINEAGE` | on-the-fly root-trace tree | `completion_contrib` |
| 6 | `VRR_LINEAGE_GRAPH` | persisted root-trace | `vrr_trace` UC fn / `lineage_edge` |
| 7 | `VRR_IMPACT` | what-if / impact (forward reachability) | `vrr_impact` UC fn / `lineage_edge` |
| 8 | `VRR_EXPLAIN_CALC` | retrieve the actual logged build SQL | `pattern_vrr_log` |

```mermaid
flowchart LR
    U(["question"]) --> AG
    subgraph AG["Agent (LLM — the ONLY non-deterministic part)"]
      R["route (pick tool)"] --> P["parse args (pattern/date/grain)"] --> N["narrate"]
    end
    AG -->|tool calls| T["8 deterministic tools"]
    T --> D[("vrr_curated · lineage_node/edge · pattern_vrr_log")]
    AG --> G["faithfulness gate (deterministic)"]
```

## 5.2 Determinism model
**Deterministic (same input → same output):** all 8 tools, the VRR math (`vrr_build.sql`/
`physics.py`), the lineage-graph build, and the faithfulness gate. The numbers people act on
never vary.

**Non-deterministic (the LLM), in exactly three places:**
1. **Tool routing** — which tools it calls, in what order.
2. **Argument extraction / parsing** — turning `"UNITY April"` into the exact fields a tool
   needs: `{pattern: "PUNITY", date: "2026-04-01", grain: "monthly"}` (name→id, month→date,
   grain default). Today the LLM does this → it can misparse.
3. **Narration** — phrasing the final answer (numbers are safe; wording varies).

**How to shrink each:**
- Routing → a deterministic **intent router** (classify → fixed tool pipeline per intent).
- Parsing → **deterministic date parser + `resolve_pattern` against the catalog + validate**;
  clarify if the parsed pattern/date isn't real. Don't trust the LLM's free-form arg fill.
- Narration → **templated output** (LLM polish only) + a **number-level faithfulness gate**
  (every figure in the answer must exist in the tool payload) + **cache** per (intent, pattern,
  date, run_id).

Principle: make the LLM do the least — ideally only NL→(validated intent+args) and light polish.

## 5.3 Genie integration (a choice; not yet wired)
Genie is NOT currently in the workflow (today = custom agent + 8 tools). Two opposite ways to
combine — pick one:

| | Option A — Genie *inside* our agent | Option B — our functions *inside* Genie (recommended) |
|---|---|---|
| Shape | agent keeps 8 tools + a `GENIE_QUERY` tool; routes known→tools, ad-hoc→Genie | Genie is primary; register `vrr_get/impact/trace` UC functions + `vrr_*` tables in a Genie space; thin/no custom agent |
| Pros | one entry point, deterministic core kept | least to maintain, native NL→SQL flexibility |
| Cons | more agent code to maintain | lose the faithfulness gate unless `vrr_decompose` is kept as a UC function |
| Make deterministic | intent router + templates (5.2) | **Metric Views** (VRR/target/verdict) + **certified queries** + read-only guardrails |

Recommendation: **Option B** for production (Genie chats over the governed tables + our UC
functions), keeping the deterministic UC functions for the answers that must be exact.

## 5.4 Agentic loop — memory + monitor→act→learn (what makes it a true AI agent)
Today the VRR agent is agentic Q&A (tool-use + reasoning + self-verification). These three
additions make it an autonomous decision agent: it **remembers**, **acts** (with sign-off),
and **learns**.

```mermaid
flowchart TD
    T["⏰ job_vrr_anomaly (after job_vrr_build)"] --> DET["DETECT anomalies (deterministic rules)"]
    DET --> MEM1["retrieve MEMORY for the pattern:<br/>entity state · past anomalies/decisions/outcomes · knowledge"]
    MEM1 --> REC["RECOMMEND valve/injection change<br/>= physics target + precedent calibration + safety bound"]
    REC --> Q[("action_queue (staged: analyst→RM→site)")]
    Q --> H["👤 multi-level approval"] --> ACT["field executes"]
    ACT --> OUT[("adjustment_history: pre/post VRR, outcome")]
    OUT -->|update per-pattern response factor ρ| LEARN["LEARN (calibrate)"]
    LEARN -.feeds next.-> REC
    OUT -.episodic memory.-> MEM1
```

### A. Memory (persist context so it reasons with history) — see also `docs/specs/agent-memory.md`
Four tiers. **Design decision (2026-07-21): source what you can from MLflow traces; only
materialize what traces structurally cannot hold.** A trace records what the *agent did*
(request/response/tool spans); the learning tables record real-world *decisions + outcomes*
(approved? executed at the field? did VRR actually move days later?) — none of which is in a trace.

| Tier | Store | From traces? | Used for |
|---|---|---|---|
| **Working / conversation** | **MLflow traces** (session/user IDs) — *no dedicated table* | ✅ yes | continuity within/across a user's sessions |
| **Episodic (long-term)** | `vrr_agent.adjustment_history` (anomaly → decision → outcome) | ❌ no — outcome arrives later, human-entered | "what happened last time on this pattern" |
| **Semantic** | `reservoir_knowledge` vector index (engineer PDFs, Slice C) | ❌ no — external knowledge | constraints, well behavior, heuristics |
| **Entity** | `vrr_agent.pattern_memory(pattern_id, latest_state, tendencies, response_factor, recent_anomalies)` | ❌ no — materialized learned ρ | per-pattern rolling summary + learned gain |

Rationale for keeping episodic + entity as governed tables (not derived from traces): the
recommendation engine needs **structured, queryable** inputs (pre/post VRR, ρ, safety limits);
they're written by the **approval/outcome jobs**, not the chat endpoint; the ρ-learning loop and
precedent retrieval require **reliable joins/aggregations**; and traces are **sampled/retention-
limited** and tied to the endpoint experiment — not a system-of-record. Conversation memory has
none of these needs, so it rides on traces and we **drop the planned `session_memory` table**.

At reason-time for pattern P, the agent retrieves `pattern_memory(P)` + recent `adjustment_history(P)`
+ semantic hits + trace-derived session history → grounds every recommendation in precedent, not just the current number.

### B. Monitor → Act (autonomy)
`job_vrr_anomaly` (scheduled, runs after the refresh) detects anomalies (out-of-band VRR, sustained
MoM drift, extrapolated-PVT/reconciliation flags), and for each **invokes the recommendation engine
in batch** (not chat) → writes a **draft** to `action_queue` → notifies the RM. The agent now *acts*
(proposes) on a trigger, not only when asked.

### C. Recommendation engine (draft the valve adjustment) — deterministic core
The magnitude is **computed, not guessed** (preserves the trust model):
1. **Physics target:** to steer VRR→target, required `INJ_RES_target = target_VRR × PROD_RES`;
   `ΔINJ_RES = INJ_RES_target − INJ_RES_current`.
2. **To surface rate:** `Δwater_inj_surface = ΔINJ_RES / (FACTOR × Bw_inj)`, allocated across the
   pattern's injector completions.
3. **Precedent calibration:** apply the learned per-pattern **response factor** `ρ` (§D) —
   `Δrecommended = ΔINJ_RES / ρ` — to correct for systematic over/under-response seen historically.
4. **Safety bound:** clamp to `safety_limits` (max injection-rate change, injection pressure,
   fracture gradient); flag if the needed change exceeds limits (→ escalate, don't auto-cap silently).
5. **Narrate (LLM):** the recommendation names the wells, the Δrate, the **expected post-VRR**, the
   **driver** (from `VRR_DECOMPOSE`), the **precedent** (from history), and **confidence** — cited,
   never invented. Draft-only.

New table: `vrr_agent.safety_limits(pattern_id, completion_id, max_inj_rate_change_pct, max_inj_pressure, ...)`.

### D. Learning loop (use outcomes to shape the next recommendation)
Concrete + deterministic (not opaque RL):
- On execution, record `predicted_post_vrr` vs `actual_post_vrr` in `adjustment_history`.
- Update the per-pattern **response factor** `ρ = EMA(actual ΔVRR / predicted ΔVRR)` in `pattern_memory`.
  If a pattern consistently over-responds (`ρ>1`), future recommendations are tempered; under-responds
  (`ρ<1`), strengthened. This is the "use outcomes to recommend the next" mechanism.
- **Case-based precedent:** retrieve the most similar past anomalies (same driver/season/pattern) and
  surface "last time X was done → VRR went to Y" in the draft.
- Human decisions (approved / edited / rejected) + the MLflow monitoring scorers add quality signals.

### Build order for this layer
1. `pattern_memory` + `adjustment_history` + `safety_limits` tables.
2. Recommendation engine (deterministic Δinjection + ρ calibration + safety bound + narrate).
3. `job_vrr_anomaly` (monitor→detect→recommend→queue) + the staged `action_queue` (Slice B).
4. Learning update (write outcomes, recompute ρ) + case-based retrieval into the draft.

## 6. Guardrails (non-negotiable — physical reservoir)
- **Advisory only** — the app recommends; **field ops execute**. Never autonomous well/valve control.
- **Multi-level human approval mandatory** (Analyst → RM → Site).
- **Safety-limit gate** at RM + Site stages (injection pressure, fracture gradient, valve rate).
- **Input-audit first** — never recommend on suspect inputs.
- **Every recommendation cites** its math (decompose/lineage), knowledge (PDF citations), and
  precedent (history) — no black-box advice. Full audit of every stage transition.

## 7. Build order
1. **Phase 1 (now):** Slice A (input-audit gate) + Slice B (multi-stage action_queue) + Slice C
   (knowledge index) — the load-bearing foundations.
2. **Phase 2:** the recommendation assembler (math+knowledge+precedent) + `adjustment_history`.
3. **Phase 3:** the Databricks App (staged approval UI, evidence bundle, citations) + notifications
   (App queue / SQL Alert / Teams webhook — no custom SMTP).
4. **Phase 4:** learning loop (outcomes → threshold/magnitude tuning) + agent-eval.

## 8. Open questions
- Safety-limit source: a policy table (`vrr_agent.safety_limits`) per pattern/well, or from the knowledge PDFs?
- Reconciliation baseline for "mismatch": vs legacy VRR, vs target, or vs a sim-model expectation?
- Notification channel for the RM: Databricks App only, SQL Alert email, or Teams/Slack webhook?
- Multi-asset rollout: one app across assets, or per-asset spaces?
