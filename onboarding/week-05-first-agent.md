# Week 5 — What an AI Agent Is 🤖

This is the big one. An **agent** is an LLM that can *use tools* to do real work —
not just chat. This week you'll fully understand **how our agents work**: the LLM
picks a tool, our code runs a safe query, and the model explains the result.

By Friday you'll be able to read any agent in this repo and explain it line by line.

---

## Day 1 — Agent = LLM + tools (function-calling)

🎯 **Goal:** Explain what "tools" and "function-calling" mean.

📖 **Learn:** On its own, an LLM can only produce text. A **tool** is a function *we*
write that the model is allowed to call — e.g. `get_open_invoices(customer)`. This is
**function-calling**: the model reads the question, decides "I need that tool," tells us
the tool + inputs, **our code runs it** and returns real data, then the model writes the
answer from that data.

The key insight: **the model never touches the database directly.** It only *asks* our
code, and our code only does safe, pre-approved things. That's how we stay in control.

🛠️ **Do:** In your log, draw: `question → model picks tool → our code runs SELECT → data → model answers`.

✅ **Check yourself:** Who actually runs the query — the model or our code? Why does that matter?

---

## Day 2 — Our agent pattern: function-calling over governed SQL

🎯 **Goal:** Understand the exact pattern every agent here follows.

📖 **Learn:** From [agents/README.md](../agents/README.md): every agent is a *thin
function-calling layer* — "the LLM picks a tool, the tool runs a **parameterized SELECT
against an approved Unity Catalog view**, and the result is summarized. Agents never
write data, never see raw bronze, and never see unmasked PII."

Three guardrails ride along:
- **Read-only** — tools do `SELECT` only. No changing data.
- **Parameterized** — inputs are bound as parameters, never glued into the SQL string (prevents injection).
- **Least privilege** — the agent's login can only read the exact approved views.

🛠️ **Do:** Re-read the "Shared guardrails" section of [agents/README.md](../agents/README.md).
Write each guardrail in your own words.

✅ **Check yourself:** Why parameterized SQL? What can an agent NOT do here?

---

## Day 3 — Read a real agent, top to bottom

🎯 **Goal:** Read one agent fully and understand each part.

📖 **Learn:** A typical `agent.py` has: a **system prompt** (rules), **pure helper
functions** (plain logic, easy to test), **tool definitions** (what the model may call),
and the **LLM call** that ties it together.

🛠️ **Do:** Open [agents/collections/agent.py](../agents/collections/agent.py). Read it
slowly, top to bottom. For each function, write one line: "this does ___." You already
met `is_actionable` in Week 1 — see how it fits the bigger picture now.

✅ **Check yourself:** Which parts are plain Python logic (no AI) and which part uses the LLM?
Why keep the logic separate from the LLM?

---

## Day 4 — Why we split "deterministic logic" from "the LLM"

🎯 **Goal:** Understand our signature pattern: *LLM drafts, deterministic code decides.*

📖 **Learn:** LLMs are creative but unreliable for exact facts. So we let the **LLM
handle language** (explaining, drafting) and let **plain code handle anything that must
be correct** (the numbers, the rules, the final gate). In collections: code decides *if*
an account is actionable and its priority; the LLM only *writes the explanation*. This is
why our answers are trustworthy.

🛠️ **Do:** In [agents/collections/agent.py](../agents/collections/agent.py), list which
decisions are made by code vs by the LLM. Notice the LLM never invents a number.

📂 **Read in our repo:** the module docstring at the top of that file — it literally
describes "LLM drafts, deterministic gate." That's the house style.

✅ **Check yourself:** What should the LLM do, and what should code always do? Why this split?

---

## Day 5 — Compare a second agent + see the deployable version

🎯 **Goal:** See the pattern repeat, and glimpse how an agent gets deployed.

📖 **Learn:** Same pattern, different domain = confidence it's a real pattern, not a
one-off. Some agents also have a `model.py` — the "productionized" version that runs as a
real serving endpoint with tracing.

🛠️ **Do:**
- Skim a second agent, e.g. [agents/customer_health/agent.py](../agents/customer_health/agent.py)
  or [agents/finance_reconciliation/agent.py](../agents/finance_reconciliation/agent.py).
- Open [agents/contract_intelligence/model.py](../agents/contract_intelligence/model.py)
  and just notice: it's a servable agent with a **tool-calling loop** and **tracing**
  (we log what the agent did). Don't master it — just see where agents "grow up" into services.

✅ **Check yourself:** What's common across all the agents? What does a `model.py` add over an `agent.py`?

---

## 🏁 End of Week 5

You can now read our agents and explain the whole pattern: **function-calling over
governed SQL, with LLM-for-language and code-for-correctness.** This is the core skill.

**Deliverable:** Pick one agent and write a one-page explainer: what it answers, which
tools it has, what's LLM vs code, and its guardrails. This is basically a mini design doc —
exactly what you'll write for real later.

➡️ **[Week 6 — RAG](week-06-rag.md)**
