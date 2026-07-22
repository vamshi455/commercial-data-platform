# Week 2 — The Lakehouse (Databricks) 🏞️

This week you learn **where our data lives and how it's organized.** Everything the
AI agents read comes from here, so this is important groundwork. Still mostly reading
and understanding — the AI fun starts next week.

By Friday you'll confidently explain **bronze → silver → gold**, what SQL is, and why
we're so careful about who can see what.

---

## Day 1 — SQL: asking questions of data

🎯 **Goal:** Read a simple SQL query and know what it returns.

📖 **Learn:** SQL is the language for asking tables questions. The core shape:
```sql
SELECT column1, column2      -- which columns I want
FROM   some_table            -- which table
WHERE  ar_balance > 5000     -- only rows matching this
```
That's "give me these columns, from this table, but only these rows." 90% of SQL is that pattern.

🛠️ **Do:** You don't need a live database. Just *read* and translate to English:
```sql
SELECT customer_name, ar_balance
FROM   gold.collections_risk
WHERE  risk_tier = 'High'
```
Write in your log: "This asks for ______."

📂 **Read in our repo:** search the project for `.sql` files and open one that looks
readable (try under [src/](../src/) or [ddl/](../ddl/)). Don't understand every line —
just spot the `SELECT ... FROM ... WHERE` shape.

✅ **Check yourself:** What do SELECT, FROM, and WHERE each control?

---

## Day 2 — The Lakehouse & the medallion (bronze → silver → gold)

🎯 **Goal:** Explain how raw data becomes trustworthy data products.

📖 **Learn:** Data arrives messy. We refine it in three stages (the "medallion"):
- 🥉 **Bronze** — raw, exactly as it arrived. Ugly but faithful. *(Nobody builds reports on bronze.)*
- 🥈 **Silver** — cleaned, standardized, deduplicated, joined. Trustworthy building blocks.
- 🥇 **Gold** — business-ready **data products** that answer a specific question
  (e.g. `gold.customer_360`, `gold.collections_risk`).

Think coffee: raw beans (bronze) → ground & filtered (silver) → the cup you actually drink (gold).

🛠️ **Do:** Re-open the root [README.md](../README.md). Find the architecture diagram
and the gold-products table. Match each **business question** to its **gold table**.

📂 **Read in our repo:** [docs/architecture.md](../docs/architecture.md) — read the
first couple of sections slowly.

✅ **Check yourself:** Why don't we let dashboards or AI read bronze directly? What lives in gold?

---

## Day 3 — Unity Catalog & governance (who's allowed to see what)

🎯 **Goal:** Explain why governance is a big deal, especially for AI.

📖 **Learn:** **Unity Catalog (UC)** is Databricks' security guard. It decides
**who can read which table/column**, hides sensitive fields (**PII** — personal info
like email, phone, tax IDs) with **masking**, and records **who read what** (audit).

Why you care: our AI agents are only as safe as their permissions. An agent that
could read raw customer emails would be a data leak. So agents get access to **only
the curated gold/silver views, with PII masked** — nothing more.

🛠️ **Do:** In your log, write one sentence: "If an AI agent should never see customer
emails, the safe way to enforce that is ______." (Hint: not the prompt — the permissions.)

📂 **Read in our repo:** [agents/README.md](../agents/README.md), the section
"**Shared guardrails**." Read it twice. This is the heart of how we do AI *safely*.

✅ **Check yourself:** What is PII? What is masking? Why are permissions (not prompts) the real boundary?

---

## Day 4 — How data flows in (pipelines, briefly)

🎯 **Goal:** Get the big picture of how data moves from source to gold — no deep detail.

📖 **Learn:** A **pipeline** is an automated job that takes data from one stage to the
next (bronze → silver → gold) on a schedule, applying cleaning and quality checks
(**expectations**) along the way. We use Databricks' **Lakeflow / DLT** for this. You
won't build pipelines soon — you just need to know they're what keeps gold fresh.

🛠️ **Do:** Skim [docs/pipelines.md](../docs/pipelines.md) or
[docs/jobs-and-pipelines.md](../docs/jobs-and-pipelines.md) — just the headings and diagrams.

✅ **Check yourself:** In one sentence, what does a pipeline do? What's a data-quality "expectation"?

---

## Day 5 — Put it together + explore the interactive map

🎯 **Goal:** See the whole platform as one connected picture.

📖 **Learn:** Everything connects: sources → pipelines → medallion → governance →
dashboards & AI agents. Today, zoom out.

🛠️ **Do:**
- Open [docs/knowledge-graph.html](../docs/knowledge-graph.html) in a browser
  (right-click → open). Click around. It maps every table, job, and agent.
- Pick ONE gold table and trace, roughly, where its data might come from.

✅ **Check yourself:** Draw (on paper!) the arrow: source → bronze → silver → gold → agent.
Show it to your buddy and talk through it.

---

## 🏁 End of Week 2

You now understand the "data platform" half of the job. Next week we make it concrete
with the actual business, and after that — finally — the AI.

**Deliverable:** A short paragraph in your log explaining bronze→silver→gold and why
agents only read gold/silver with PII masked. If that paragraph is clear, you're ready.

➡️ **[Week 3 — The Business](week-03-the-business.md)**
