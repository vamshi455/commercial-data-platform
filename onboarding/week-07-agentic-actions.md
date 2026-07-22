# Week 7 — Agents That Act & Learn 🔁

So far agents *answer questions*. The frontier — and an active direction in this
project — is agents that **notice a problem, propose an action, wait for a human to
approve, and learn from the outcome.** This week you'll understand that pattern and how
we keep it safe.

By Friday you'll explain **monitor → act → learn**, human-in-the-loop, agent memory, and
evaluation.

---

## Day 1 — From "answer" to "act": the monitor → act → learn loop

🎯 **Goal:** Explain the loop and why it's powerful.

📖 **Learn:** The pattern (from our collections agent):
```
MONITOR   watch a gold table for problems (e.g. overdue high-risk accounts)
DIAGNOSE  LLM explains the likely root cause
DRAFT     LLM drafts a tailored action (a dunning email / a CSM escalation)
APPROVE   a HUMAN reviews and approves — the agent never sends anything itself
LEARN     the decision + outcome are saved, so the agent improves over time
```
This turns "a person stares at a dashboard" into "the system surfaces the few things
that matter and prepares the response."

🛠️ **Do:** Re-read the docstring at the top of [agents/collections/agent.py](../agents/collections/agent.py) —
it describes exactly this loop. Write the 5 steps in your own words.

✅ **Check yourself:** What are the 5 steps? At which step does a human step in?

---

## Day 2 — Human-in-the-loop & "draft-only" safety

🎯 **Goal:** Explain why the agent proposes but never acts alone.

📖 **Learn:** Letting an AI send emails or change data on its own is risky. So our
acting agents are **draft-only**: they write a *proposal* into a queue
(`ops.action_queue`), and **a human approves** before anything happens. Every proposal is
audited. This is **human-in-the-loop** — the AI does the heavy lifting, the human keeps
the judgment and accountability.

🛠️ **Do:** In [agents/collections/agent.py](../agents/collections/agent.py), find where it
writes a **PROPOSAL** (not an action). Note: it "never sends anything."

✅ **Check yourself:** What does "draft-only" mean? Why is human approval non-negotiable here?

---

## Day 3 — Agent memory (how an agent "learns")

🎯 **Goal:** Explain how agents remember and improve.

📖 **Learn:** "Learning" here doesn't mean retraining the model. It means **keeping a
record**: what was proposed, what the human decided, what happened (did the customer pay?).
That feedback (`ops.action_feedback`) can shape future proposals — e.g. stop suggesting
things humans keep rejecting. Memory = tables of past decisions + outcomes.

🛠️ **Do:** Skim the specs under [docs/specs/](../docs/specs/) related to agentic actions /
memory (look for the collections or "monitor→act→learn" spec). Note what gets stored.

✅ **Check yourself:** What does "learning" mean for our agents? Where does the feedback live?

---

## Day 4 — Evaluation, done properly

🎯 **Goal:** Explain how we measure whether an agent is good and safe.

📖 **Learn:** Before an agent is trusted, we **evaluate** it against test cases:
- **Correctness** — right answer / right diagnosis?
- **Groundedness** — did it stick to real data?
- **Safety** — did it refuse out-of-scope or PII requests?
- **Faithfulness** — did the LLM's words match the actual tool output (no invented numbers)?

Some agents even have a **deterministic faithfulness gate** — code that checks the LLM
didn't stray from the data before the answer is allowed out.

🛠️ **Do:** Read [docs/agent-evals.md](../docs/agent-evals.md) more carefully now. Look at
[src/evals/](../src/evals/) to see how tests are structured (off-cluster unit tests).

✅ **Check yourself:** Name three things an eval checks. What's a "faithfulness gate"?

---

## Day 5 — See it all in one advanced agent (VRR)

🎯 **Goal:** See a full, deployed, tool-using, traced agent as your "north star."

📖 **Learn:** The `vrr_reasoning` agent is our most complete example: multiple tools, a
tool-calling loop, discovery tools for open-ended questions, tracing, and a deployed
serving endpoint. It's a great model for your capstone next week.

🛠️ **Do:** Skim [agents/vrr_reasoning/model.py](../agents/vrr_reasoning/model.py). Don't
master it — identify: the tools, the loop, and where it records traces. Notice how
familiar it now feels vs. Week 5.

✅ **Check yourself:** Can you point to the tools, the loop, and the tracing? How is it
just a bigger version of the collections pattern?

---

## 🏁 End of Week 7

You now understand the full spectrum: agents that **answer**, agents that **act with human
approval**, and how we **evaluate** them. You're ready to build.

**Deliverable:** A one-page design note for an imaginary new "acting" agent (any Rheinhardt
problem you like): what it monitors, what it drafts, where the human approves, what it
learns, and how you'd evaluate it. Next week you'll build a small real one.

➡️ **[Week 8 — Build Your Own Agent](week-08-build-your-own.md)**
