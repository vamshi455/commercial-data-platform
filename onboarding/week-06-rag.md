# Week 6 — RAG: Answering From Documents 📚

Week 5's agents answer from **tables**. But a lot of business knowledge lives in
**documents** — contracts, policies, PDFs. **RAG (Retrieval-Augmented Generation)** is
how we let an LLM answer questions from those documents, accurately and with citations.

By Friday you'll explain embeddings, vector search, and how our `contract_intelligence`
agent gives **grounded, cited** answers over Rheinhardt's contracts.

---

## Day 1 — The problem RAG solves

🎯 **Goal:** Explain why we can't just paste all documents into the prompt.

📖 **Learn:** We have many contracts — far too much text to feed the model every time
(remember tokens = cost + limited context from Week 4). So instead of "read everything,"
we do "**find the few relevant paragraphs, then answer from those.**" That "find relevant
bits, then generate an answer" is **RAG**.

🛠️ **Do:** In your log: "We can't paste all contracts into the prompt because ______.
So RAG first ______, then ______."

✅ **Check yourself:** Why not just send all documents to the model every time?

---

## Day 2 — Embeddings: turning meaning into numbers

🎯 **Goal:** Explain embeddings in plain words.

📖 **Learn:** An **embedding** turns a piece of text into a list of numbers (a
"vector") that captures its *meaning*. Texts with similar meaning get similar numbers —
even if they use different words ("payment terms" ≈ "when we get paid"). This lets a
computer find related text by *meaning*, not just exact keywords.

🛠️ **Do:** Analogy check — in your log, explain: "Embeddings are like giving every
sentence a location on a map, so similar sentences sit ______."

✅ **Check yourself:** What does an embedding capture that a keyword search misses?

---

## Day 3 — Vector search: finding the relevant bits

🎯 **Goal:** Explain how we retrieve the right chunks.

📖 **Learn:** We chop documents into **chunks**, embed each chunk, and store them in a
**vector index** (a search engine for meaning). At question time we embed the question,
then ask the index "which chunks are closest in meaning?" — those come back as context.

Our project uses **Databricks Vector Search** for this.

🛠️ **Do:** Skim [docs/embedding-lifecycle.md](../docs/embedding-lifecycle.md) — how
embeddings get created and kept fresh. Look at [src/contract_vector_search/](../src/contract_vector_search/)
and find the `retriever.py` (the "fetch relevant chunks" part).

✅ **Check yourself:** What's a chunk? What does the vector index return for a question?

---

## Day 4 — Grounded + cited generation (the payoff)

🎯 **Goal:** Explain how RAG produces trustworthy, cited answers.

📖 **Learn:** Full flow:
```
question → embed → vector search → top relevant chunks
        → give chunks + question to the LLM
        → LLM answers ONLY from those chunks, and cites which chunk it used
```
Because the answer must come from retrieved text, hallucination drops sharply, and
**citations** let a human verify. This is our `contract_intelligence` agent.

🛠️ **Do:** Read [agents/contract_intelligence/README.md](../agents/contract_intelligence/README.md),
then skim [agents/contract_intelligence/agent.py](../agents/contract_intelligence/agent.py).
Trace the flow: retrieve → build prompt with chunks → generate cited answer.

📂 **Read in our repo:** note it reads a **PII-masked** index and only **current** contract
versions — governance shows up here too.

✅ **Check yourself:** Why does grounding-in-retrieved-chunks reduce hallucination? Why do citations matter?

---

## Day 5 — How we know it's actually good (a peek at evals)

🎯 **Goal:** Understand that we *measure* agent quality, not just hope.

📖 **Learn:** A RAG agent can still be wrong. So we **evaluate** it: run a set of test
questions with known-good answers and score things like "was it grounded? did it cite
correctly? was it right?" This is **agent evaluation**, and it's what makes AI work
*engineering* rather than *guessing*. (You'll go deeper in Week 7.)

🛠️ **Do:** Skim [docs/agent-evals.md](../docs/agent-evals.md) — just the idea and the
kinds of things we score.

✅ **Check yourself:** Why isn't "it looked good in one demo" enough? What does an eval measure?

---

## 🏁 End of Week 6

You now know both ways we ground agents: **tools over SQL** (structured data) and
**RAG over documents** (unstructured text). Together, that's most of applied AI engineering.

**Deliverable:** A diagram + paragraph explaining RAG end-to-end, using our
`contract_intelligence` agent as the example.

➡️ **[Week 7 — Agents That Act & Learn](week-07-agentic-actions.md)**
