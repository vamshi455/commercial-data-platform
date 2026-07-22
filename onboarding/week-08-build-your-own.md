# Week 8 — Build Your Own Agent 🚀 (Capstone)

This is where it all comes together. You'll build a **small, working, read-only agent**
that answers questions over one gold data product — following exactly the patterns you've
studied. It doesn't need to be fancy. It needs to be **correct, safe, and yours.**

Take your time. Shipping something small and solid beats a big broken thing.

---

## Day 1 — Pick your problem & write a mini design doc

🎯 **Goal:** Decide what your agent does — on paper first.

📖 **Learn:** Good engineers design before coding. A design doc keeps you honest.

🛠️ **Do:** Write a one-pager (use the Week 5/7 deliverables as templates):
- **Question it answers** (e.g. "Which accounts are the biggest collections risk this week?")
- **Gold table(s) it reads** (pick ONE to start, e.g. `gold.collections_risk`)
- **Tool(s)** it needs (e.g. `top_risk_accounts(limit)`)
- **What's LLM vs code** (LLM = wording; code = the numbers/filters)
- **Guardrails** (read-only, parameterized SQL, no PII, scope in system prompt)

✅ **Check yourself:** Could someone else build your agent from this doc? If not, add detail.

---

## Day 2 — Copy the pattern, set up the skeleton

🎯 **Goal:** Create your agent file following the house style.

📖 **Learn:** Don't start from scratch — start from what works. The best starting point
is an existing agent.

🛠️ **Do:**
- Create `agents/<your_agent_name>/` with a `README.md` and `agent.py`.
- Copy the **structure** (not blindly the content) of
  [agents/collections/agent.py](../agents/collections/agent.py): module docstring,
  a `SYSTEM_PROMPT`, pure helper functions, tool definitions.
- Write your `README.md` like the others: scope, example questions, exact objects, guardrails.

✅ **Check yourself:** Does your folder match the shape of the existing agents? Same conventions?

---

## Day 3 — Write the pure logic first (no LLM yet)

🎯 **Goal:** Get the correctness-critical code working and tested — before adding AI.

📖 **Learn:** Remember: **code does the parts that must be right.** Build those first;
they're easy to test and don't cost tokens.

🛠️ **Do:**
- Write plain functions (like `is_actionable`, `priority_for`) for whatever your agent
  must decide. Feed them example dictionaries, print results.
- Add a couple of tiny unit tests (see [src/evals/](../src/evals/) and existing
  `tests/` for the style). Off-cluster, fast.

✅ **Check yourself:** Do your helper functions give the right answers on made-up examples?
Do your tests pass?

---

## Day 4 — Add the tool + the LLM layer

🎯 **Goal:** Wire the LLM to your tool and produce a grounded answer.

📖 **Learn:** Now the fun part: the model picks your tool, your code returns real (or
sample) data, and the model explains it — **only from that data.**

🛠️ **Do (with your buddy for access/credentials):**
- Define your tool schema (what the model may call), mirroring an existing agent.
- Connect the LLM call. If you can't hit the real warehouse yet, use a **small hardcoded
  sample dataset** so you can prove the whole loop end-to-end.
- Test: ask an in-scope question (should answer from data) and an out-of-scope/PII
  question (should refuse). Both behaviors matter.

✅ **Check yourself:** Does it answer in-scope questions from real data, and refuse the rest?

---

## Day 5 — Evaluate, document, and demo

🎯 **Goal:** Prove it works, write it up, and show it off.

📖 **Learn:** An agent isn't "done" until it's *evaluated* and *documented.* This is the
professional finish.

🛠️ **Do:**
- Write 5–10 test questions with expected behavior (right answers + correct refusals).
  Run them. Note results. (This is your mini-eval — see [docs/agent-evals.md](../docs/agent-evals.md).)
- Finish your `README.md` and add a short "how to run" note.
- **Demo it** to your buddy/team: the question, the tool call, the grounded answer, the refusal.
- Commit your work on a branch and open it for review (ask your buddy for the Git flow).

✅ **Check yourself:** Can you show a working answer, a working refusal, and your eval results?
If yes — **you just built and shipped an AI agent.** 🎉

---

## 🏁 You did it

Eight weeks ago "AI Engineering" was a buzzword. Now you understand the business, the data
platform, LLMs, agents, RAG, acting agents, and evaluation — **and you've built one.**

### Where to go next
- Read the agents you *didn't* study closely; try improving one (a new tool, a better prompt, more evals).
- Go deeper on one area you loved: RAG, evaluation, or deployment (`model.py` + serving).
- Start pairing on real tickets. Look at [PROGRESS.md](../PROGRESS.md) and open GitHub Issues for good first tasks.
- Keep your learning log going. Teaching the *next* new hire is the fastest way to master this.

Welcome to the team. You're an AI engineer now. 💪

⬅️ Back to [onboarding home](README.md) · [glossary](glossary.md) · [checklist](checklist.md)
