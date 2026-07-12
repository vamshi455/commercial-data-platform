# Spec — Agent Memory Architecture

> How memory / context-assembly-over-time applies to CDP's agents (contract
> RAG + collections action agent). **Current state: mostly stateless** — strong
> semantic + ephemeral working memory, but **no episodic recall or procedural
> learning yet**. The `ops.action_feedback` table is the substrate for the
> missing layers. Related: [`agentic-actions.md`](./agentic-actions.md),
> [`agent-evals.md`](../agent-evals.md).

## The six memory layers, mapped to our system

| Layer | What it is | In our system | Status | When it's useful (case) |
|---|---|---|---|---|
| **Working** | active task state in the context window | prompt: facts / retrieved chunks | ✅ ephemeral | Follow-up in a thread; assembling one account's facts to draft |
| **Semantic** | general facts & knowledge | vector index (`contract_chunks_index`) + gold | ✅ | "What are Northwind's MSA termination terms?" |
| **Episodic** | specific past events | `ops.action_queue` + `ops.action_feedback` | 🟡 stored, **not recalled** | Recall "last quarter escalation REJECTED — known slow-payer" → don't re-escalate |
| **Procedural** | learned how-to / policy | `DEFAULT_RULES` + prompt (static) | 🔴 **not learned** | Stewards edit first-slip emails softer → agent learns that tone via few-shot |
| **Context builder** | assembles memories → working context | retriever / `propose_actions` (naive) | 🟡 basic | Fit facts + 2 episodes + 3 similar approved drafts + contract terms into budget |
| **Model** | parametric memory (weights) | `claude-sonnet-5`, frozen | ⚪ | After ~10k approved/rejected pairs, DPO to bake in steward-preferred behavior |

## Design: the memory-augmented collections agent
Before drafting for account X:
1. **Working** — pull X's current facts from gold (have).
2. **Episodic recall** — `SELECT` X's past proposals + decisions from
   `action_feedback` (by `account_id`) → inject prior outcomes + steward notes.
3. **Procedural (few-shot)** — vector-search past **approved/edited** drafts
   similar to X → top-3 as in-context "good draft" examples.
4. **Semantic** — relevant contract payment terms for X from the contract index.
5. **Context builder** — rank + compress + budget all of the above into one prompt.
6. **Reflection (batch)** — periodically summarize `action_feedback` into updated
   guidance / adjusted rules → procedural memory *evolves*.
7. **Model** — once enough labeled pairs exist, DPO/fine-tune (last, high data bar).

## Where it lives on Databricks
- **Episodic + procedural stores** = Delta (`action_feedback`, a `memory`/`playbook`
  table) **+ a Vector Search index over episode summaries and approved drafts**
  (same pattern as contract RAG) for similarity recall.
- **Working memory / multi-step orchestration** = **LangGraph** state (checkpointer)
  or the Mosaic AI Agent Framework.
- **Governance** = memory tables stay in UC — masked + audited. *Memory is governed
  too*: an episodic store can leak PII if unmasked.

## Why it matters
Memory turns the agent from a stateless drafter into one that **compounds**: never
repeats a rejected action, learns each account's payment personality, improves
drafts from human edits, internalizes stewards' unwritten policies. It **is** the
feedback loop, formalized — and closes the continuous-eval gap.

## Next build (recommended)
A thin **episodic + procedural layer** for the collections agent: read
`action_feedback` by account (episodic) + a Vector Search index over approved
drafts (procedural few-shot), fed into `propose_actions`. Reuses the feedback
table + the proven Vector Search pattern. This is what elevates it from demo to
"gets better every week."
