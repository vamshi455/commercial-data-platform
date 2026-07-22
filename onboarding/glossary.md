# 📖 Plain-English Glossary

Every scary word, in one friendly sentence. Keep this open while you learn — nobody
memorizes these; you look them up until they stick.

## The basics
- **Terminal / command line** — a text way to tell your computer what to do (`ls`, `cd`, `python ...`).
- **Git** — a "save history" for code; a **commit** is one saved snapshot with a message; a **repo** is the whole project + its history.
- **Python** — the main programming language we use for AI work.
- **Function** — a named, reusable recipe of code. Give it inputs, get an output.
- **API** — a way for one program to call another (often over the internet), like ordering from a menu.

## Data & the platform
- **Table** — data as rows and columns, like a spreadsheet.
- **Database** — a place that stores many tables and lets you query them.
- **SQL** — the language for asking tables questions: `SELECT columns FROM table WHERE condition`.
- **The cloud** — renting powerful computers over the internet instead of owning them.
- **Azure** — Microsoft's cloud; the cloud this project runs on.
- **Databricks** — the platform (on Azure) where our data and AI live; a "lakehouse."
- **Lakehouse** — a system that stores lots of data cheaply *and* lets you query it like a database.
- **Medallion (bronze → silver → gold)** — refining data in stages: raw (bronze) → cleaned (silver) → business-ready products (gold).
- **Gold data product** — a business-ready table that answers a specific question (e.g. `gold.collections_risk`).
- **Pipeline** — an automated job that moves and cleans data from one stage to the next.
- **Expectation** — a data-quality rule a pipeline checks (e.g. "amount must be positive").
- **Delta / Iceberg** — modern table formats that make lakehouse tables reliable and fast.

## Governance & safety
- **Unity Catalog (UC)** — Databricks' security guard: who can read what, masking, and audit logs.
- **PII** — Personally Identifiable Information (email, phone, tax ID) — must be protected.
- **Masking** — hiding or scrambling sensitive fields so they can't be read.
- **Least privilege** — give each user/agent access to *only* what they need, nothing more.
- **Audit** — a record of who did/read what, for accountability.
- **Guardrail** — a safety limit that keeps an agent from doing something unsafe.

## AI & LLMs
- **LLM (Large Language Model)** — an AI (like Claude) that predicts and generates text; great with language, not a fact database.
- **Claude** — the family of LLMs we mainly use (by Anthropic; also available via Databricks).
- <a id="claude-api"></a>**Claude API** — the way we call Claude from code (send messages → get a reply). Ask your buddy for the sanctioned setup in our environment; see the `claude-api` skill/docs.
- **Token** — a chunk of text (~¾ of a word); models read/write in tokens and we pay per token.
- **Context window** — how much text a model can consider at once (its short-term memory).
- **Prompt** — the instruction you give the model.
- **System prompt** — a special instruction that sets the model's role and rules for the whole chat.
- **Hallucination** — a confident but made-up, wrong answer.
- **Grounding** — forcing the model to answer only from real data we provide.

## Agents & RAG
- **Agent** — an LLM that can use **tools** to do real work, not just chat.
- **Tool / function-calling** — functions we let the model call; the model asks, *our code* runs it and returns real data.
- **Parameterized SQL** — passing inputs as safe parameters (not glued into the query text) to prevent injection.
- **RAG (Retrieval-Augmented Generation)** — find the few relevant document chunks, then have the LLM answer from them.
- **Embedding** — turning text into numbers that capture its meaning, so a computer can find similar meanings.
- **Chunk** — a small piece of a document (so we can retrieve just the relevant parts).
- **Vector search / vector index** — a "search engine for meaning" over embedded chunks.
- **Citation** — pointing to the exact source a grounded answer came from.

## Acting & quality
- **Monitor → act → learn** — an agent watches for problems, drafts an action, a human approves, and it learns from the outcome.
- **Human-in-the-loop** — a person reviews/approves before anything real happens.
- **Draft-only** — the agent proposes but never acts on its own.
- **Agent memory** — stored records of past decisions and outcomes the agent can learn from.
- **Evaluation (eval)** — measuring an agent's correctness, groundedness, and safety against test cases.
- **Faithfulness gate** — code that checks the LLM's answer matches the real data before it's allowed out.
- **Deterministic** — always gives the same result for the same input (plain code); the opposite of the LLM's variability.
- **Serving endpoint / deployment** — an agent running as a live service others can call.
- **Trace / tracing** — a recorded log of what the agent did step by step (for debugging and audit).

---
*Missing a word? Add it here as you learn it — that's the best way to lock it in.*
