# Week 3 — The Business 🏭

You can't build good AI for a business you don't understand. This week is about
**Rheinhardt Industrial** — what they sell, how they make money, and what questions
keep their teams up at night. This is the "domain knowledge" that separates an
engineer who builds the right thing from one who just writes code.

By Friday you'll be able to explain the business to a stranger and map each **gold
data product** to a real decision someone makes.

---

## Day 1 — Meet Rheinhardt Industrial

🎯 **Goal:** Explain what the company does and who its customers are.

📖 **Learn:** Rheinhardt is a made-up **B2B industrial-equipment manufacturer** —
they build **pumps, valves, motors, compressors, and spare parts**, and sell to
**distributors and business customers** (not to you and me). They also do after-sales:
spare parts, warranty, field service. European roots (Germany/UK).

🛠️ **Do:** Read [docs/business-domain-and-systems.md](../docs/business-domain-and-systems.md) —
at least the top half (the product divisions and "systems a manufacturer operates").

✅ **Check yourself:** What does Rheinhardt sell? Who buys it? Name two after-sales services.

---

## Day 2 — The two big systems: CRM and ERP

🎯 **Goal:** Explain what a CRM and an ERP are, and what each holds.

📖 **Learn:** Real companies run on software systems. Two matter most here:
- **CRM** ("Salesforce-like") = the **sell side**: accounts, contacts, leads,
  opportunities (deals), quotes, contracts, support cases.
- **ERP** ("SAP-like") = the **back office**: orders, invoices, payments, collections.

The magic of our platform is **joining these two worlds** — e.g. matching "we won this
deal" (CRM) with "did we actually bill and get paid?" (ERP).

🛠️ **Do:** Skim [docs/source-systems.md](../docs/source-systems.md). List 3 things the CRM
holds and 3 things the ERP holds in your log.

✅ **Check yourself:** CRM vs ERP — which one has invoices? Which has sales deals? Why join them?

---

## Day 3 — The gold data products (what we actually deliver)

🎯 **Goal:** Explain what each gold table answers and who uses it.

📖 **Learn:** Each gold product answers one business question. From the README:

| Gold product | Answers | Who cares |
|---|---|---|
| `customer_360` | Who is this customer, end-to-end? | Sales, Support |
| `revenue_pipeline` | What deals are in flight? | RevOps, Finance |
| `bookings_vs_billings` | Did we bill what we sold? | Finance |
| `collections_risk` | Who might not pay us? | Finance/Collections |
| `account_health` | Which accounts are healthy vs at-risk? | Customer Success |
| `renewal_risk` | Which renewals might we lose? | Account Managers |

🛠️ **Do:** For each product above, write in your log **one decision a person makes** using it
(e.g. "collections_risk → decide which customer to call about an overdue bill today").

✅ **Check yourself:** Pick any two gold products and explain who uses them and why.

---

## Day 4 — Map the agents to the business

🎯 **Goal:** Connect each AI agent to the business need it serves.

📖 **Learn:** We built one agent per major need. Each is a "thin, safe layer" that lets
someone *ask questions in plain English* over a gold product instead of writing SQL.

🛠️ **Do:** Open [agents/README.md](../agents/README.md) — the "**The fleet**" table.
For each agent, jot down: which business team it helps, and which gold tables it reads.

📂 **Read in our repo:** peek into two agent folders' READMEs, e.g.
[agents/customer_health/README.md](../agents/customer_health/README.md) and
[agents/finance_reconciliation/README.md](../agents/finance_reconciliation/README.md).
Notice each README lists **scope, example questions, exact objects, and guardrails.**

✅ **Check yourself:** Which agent would a Collections analyst use? Which would an Account Manager use?

---

## Day 5 — Data storytelling: from question to answer

🎯 **Goal:** Trace one real business question all the way through the platform.

📖 **Learn:** Let's follow: *"Which high-value customers are overdue and likely to churn?"*
- The **data** for it lives in gold (`collections_risk`, `account_health`).
- An **agent** (customer_health / finance_reconciliation) can answer it in English.
- The answer must be **grounded** (from real data) and **safe** (no raw PII).

🛠️ **Do:** Write a half-page "story" in your log: pick one business question, and
narrate how it flows source → gold → agent → answer. Use the picture from Week 1/2.

✅ **Check yourself:** Can you explain, end to end, how one question gets answered here?
That's the whole platform in a nutshell.

---

## 🏁 End of Week 3

You now understand **the business and what we deliver.** Everything from here is about
building the AI that sits on top. This is where it gets exciting.

**Deliverable:** A one-page "About Rheinhardt & our platform" note in your own words.
Share it with your buddy — teaching it back is the best test.

➡️ **[Week 4 — How LLMs Work](week-04-llm-fundamentals.md)**
