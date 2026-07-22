# 🚀 Start Here (read this first — ~20 min)

Welcome again. Before any tasks, let's get you comfortable with a few things. No code yet.

---

## 1. What is "AI Engineering," really?

Forget the hype for a second. An **AI Engineer** does one core thing:

> **Take a smart-but-forgetful assistant (an LLM), and wire it safely into a real
> business so it gives useful, trustworthy answers or takes safe actions.**

An LLM (like Claude) on its own is like a brilliant new intern who:
- read most of the internet, but
- doesn't know **your** company's data,
- sometimes makes things up confidently, and
- can't be allowed to touch sensitive data or do risky things.

Our job is to give that intern:
1. **The right data** (but only what they're allowed to see),
2. **The right tools** (specific safe actions, not "do anything"),
3. **Guardrails** (so it can't leak private info or make a mess), and
4. **A way to check its work** (so we know it's actually right).

That's it. Everything in the next 8 weeks is a piece of that picture.

---

## 2. What is *this* project?

This project is called the **Commercial Data Platform (CDP)**. Think of a made-up
company called **Rheinhardt Industrial** — they build and sell industrial machines
(pumps, valves, motors, compressors) to other businesses.

Like any real company, their information is scattered across systems:
- a **CRM** (sales: customers, deals, support tickets),
- an **ERP** (back office: orders, invoices, payments),
- contracts, and more.

We built a platform that **collects all that data, cleans it, organizes it, and
then puts AI agents on top** so people can just *ask questions* like
"Which customers are at risk of not paying us?" instead of writing complex reports.

You'll learn the data part first (weeks 1–3), then the AI part (weeks 4–8).

---

## 3. The mental model to hold the whole time

```
   Messy raw data  →  Cleaned & organized data  →  AI agents answer questions / act
     (bronze)              (silver → gold)               (what YOU will build)
```

Everything we do is somewhere on that arrow. Whenever you feel lost, come back to
this picture and ask: *"Which part am I looking at right now?"*

---

## 4. A few habits that will make you good, fast

- **Read the README first.** Almost every folder here has one. It's the map.
- **Explain it back in your own words.** If you can't, you don't understand it yet — and that's fine, re-read.
- **Small steps, run often.** Change one thing, run it, see what happens. Repeat.
- **Keep a "learning log."** A simple notes file: what you learned, what confused you. Future-you will thank you.
- **Copy the patterns already here.** This codebase has strong patterns. Match them; don't invent new ones yet.

---

## 5. Set up your laptop (do this once)

You don't need everything today, but let's install the basics. Ask for help if any step is confusing — that's expected.

1. **A code editor** — install **VS Code** (free). This is where you'll read and write code.
2. **Python** — install **Python 3.11+**. (We'll check it works in Week 1.)
3. **Git** — the tool that tracks code changes. (Mac usually has it; we'll verify in Week 1.)
4. **This project** — you already have it, since you're reading this file inside it. 🎉

Don't worry about Databricks accounts, cloud logins, or credentials yet. You'll get
those when you actually need them (around Week 2–3), with a buddy to help.

---

## 6. Your first tiny task ✅

1. Open [glossary.md](glossary.md) and skim it. You won't understand most terms — that's expected. Just know it exists.
2. Open [checklist.md](checklist.md). This is your progress tracker.
3. Create a file called `my-learning-log.md` somewhere on your laptop. Write today's date and one line: *"Day 0 — read the intro. I think AI engineering is about ______."* Fill the blank in your own words.

Done? Awesome. Head to **[Week 1 →](week-01-foundations.md)**. See you there. 💪
