# Week 4 — How LLMs Actually Work 🧠

Now the AI. This week demystifies the "magic." By Friday you'll have **talked to an
LLM from Python**, and you'll understand tokens, prompts, why LLMs sometimes make
things up, and how we keep them honest.

Don't worry about math. We care about **how to use it well and safely**, not how to build one from scratch.

---

## Day 1 — What is an LLM?

🎯 **Goal:** Explain an LLM in plain words.

📖 **Learn:** An **LLM (Large Language Model)** like Claude is a program that predicts
the next chunk of text, trained on enormous amounts of writing. That simple ability,
at scale, lets it answer questions, summarize, write code, and more.

Key truth: **it doesn't "know" facts like a database — it generates likely text.**
That's why it can sound confident and still be wrong. Our whole job is to *feed it the
real facts* and *check its output*.

🛠️ **Do:** In your log, complete: "An LLM is like a very well-read intern who ______,
but sometimes ______." (Use your own words.)

✅ **Check yourself:** Why is "predicts likely text" different from "looks up a fact"?

---

## Day 2 — Tokens, context, and cost

🎯 **Goal:** Understand tokens and why they matter (quality *and* money).

📖 **Learn:**
- **Token** = a chunk of text (~¾ of a word). LLMs read and write in tokens.
- **Context window** = how much text the model can consider at once (its short-term memory).
- **Cost** = you pay per token in and out. Sending a giant prompt every time gets expensive.
  That's why we're careful about how much data we hand the model.

🛠️ **Do:** Skim [docs/token-optimization-cost.md](../docs/token-optimization-cost.md).
Note one technique we use to save tokens/cost.

✅ **Check yourself:** What's a token? Why might a huge prompt be a bad idea (two reasons)?

---

## Day 3 — Prompts: how you steer the model

🎯 **Goal:** Write a clear prompt and understand the "system prompt."

📖 **Learn:** A **prompt** is your instruction to the model. A **system prompt** is a
special instruction that sets the model's role and rules for the whole conversation
(e.g. "You only answer questions about collections; refuse anything about PII").

Good prompts are **specific**: role, task, rules, and format. Vague in → vague out.

🛠️ **Do:** Find the `SYSTEM_PROMPT` in one of our agents — e.g. search for `SYSTEM_PROMPT`
in [agents/collections/agent.py](../agents/collections/agent.py). Read what rules we give it.

📂 **Read in our repo:** notice how the system prompt states **scope and refusal behavior.**
That's a guardrail written in plain English — one layer of several.

✅ **Check yourself:** What's the difference between a prompt and a system prompt? Why set rules there?

---

## Day 4 — Talk to an LLM from Python (your first real AI code)

🎯 **Goal:** Send a message to a model and get a reply, in code.

📖 **Learn:** We call the model through an API (a function call over the internet).
We mainly use **Claude** models (via Databricks / Anthropic). The shape is always:
*you send messages → you get a text reply back.*

🛠️ **Do (with your buddy for API keys/access):**
- Follow the [claude-api](../onboarding/glossary.md#claude-api) note in the glossary, or ask your buddy for the
  quickest sanctioned way to run a "hello LLM" script in our environment.
- Send: *"In one sentence, what is a voidage replacement ratio?"* and read the reply.
- Then ask something about Rheinhardt it **can't** know (e.g. "What was Acme's AR balance?").
  Watch it either refuse or **make something up** — that's the hallucination problem, live.

✅ **Check yourself:** Did the model invent an answer to the Rheinhardt question? Why did that happen?

> ⚠️ If you can't get access today, don't stall — do the reading and pair with your buddy tomorrow. Access hiccups are normal.

---

## Day 5 — Hallucination & grounding (the core AI-safety idea)

🎯 **Goal:** Explain why LLMs make things up and how we prevent it.

📖 **Learn:**
- **Hallucination** = a confident, wrong, made-up answer.
- **Grounding** = forcing the model to answer **only from real data we give it**
  (a database row, a document). No data → it should say "I don't know," not guess.
- Two big grounding techniques you'll learn next:
  - **Tools / function-calling** (Week 5) — the model asks *our code* to fetch real data.
  - **RAG** (Week 6) — we retrieve relevant documents and make the model answer from them.

🛠️ **Do:** In your log, write: "The model hallucinated the Rheinhardt answer because
______. To fix it, we would ______."

✅ **Check yourself:** What is grounding? Name the two ways we ground answers here.

---

## 🏁 End of Week 4

You've talked to an LLM, seen it hallucinate, and you know the fix is *grounding*.
That's exactly the door into how our agents work. Next week: your first real agent.

**Deliverable:** A short note explaining tokens, prompts, hallucination, and grounding —
in words a non-technical friend would get.

➡️ **[Week 5 — Your First Agent](week-05-first-agent.md)**
