# Week 1 — Computer & Code Basics 🧱

**The vibe this week:** we're building the floor you'll stand on. No AI yet. Just
the everyday tools every engineer here uses without thinking. Go slow, type things
yourself (don't just copy-paste), and it'll click.

By Friday you'll be comfortable with the **terminal, Git, Python, and what "data"
and "the cloud" even mean.**

---

## Day 1 — The terminal (talking to your computer with words)

🎯 **Goal:** Run commands in a terminal without fear.

📖 **Learn:** The terminal is just a text way to tell your computer what to do —
like texting instead of clicking. `ls` = "list files here." `cd folder` = "go into
that folder." `pwd` = "where am I?" That's 80% of daily use.

🛠️ **Do:**
- Open the terminal in VS Code (`View → Terminal`).
- Try: `pwd`, then `ls`, then `cd onboarding`, then `ls` again, then `cd ..`.
- Make a folder and a file: `mkdir practice`, `cd practice`, then create a file and list it.

✅ **Check yourself:** What do `pwd`, `ls`, and `cd` do? How do you go "up" one folder?

---

## Day 2 — Git (a save-history for code)

🎯 **Goal:** Understand what Git is and see our project's history.

📖 **Learn:** Git is "track changes" for code, but powerful. A **commit** is a saved
snapshot with a message. A **repo** is the whole project + its history. We can go
back in time, and many people can work without overwriting each other.

🛠️ **Do (read-only — don't change anything yet):**
- Run `git status` — it shows what's changed.
- Run `git log --oneline -15` — the last 15 snapshots. Read the messages.
- Run `git show --stat HEAD` — what the most recent commit changed.

📂 **Read in our repo:** the recent commit messages you just saw. Notice they're
short and describe *what* changed (e.g. `feat(vrr): ...`, `docs(...): ...`). That
format is on purpose.

✅ **Check yourself:** What is a commit? Why is a clear commit message useful to the next person?

---

## Day 3 — Python basics, part 1

🎯 **Goal:** Write and run tiny Python programs.

📖 **Learn:** Python is the main language we use for AI work. Today: **variables**
(named boxes for values), **strings/numbers**, **print**, and **if/else** (making decisions).

🛠️ **Do:** Create `hello.py` and try:
```python
name = "Rheinhardt"
overdue_days = 45

print("Customer:", name)
if overdue_days > 30:
    print("This account is overdue — flag it.")
else:
    print("This account is fine.")
```
Run it: `python hello.py`. Change `overdue_days` to 10 and run again. See the difference.

✅ **Check yourself:** What does `if` do? What happens if you change the number?

---

## Day 4 — Python basics, part 2

🎯 **Goal:** Use lists, loops, dictionaries, and functions — the everyday building blocks.

📖 **Learn:**
- **List** = ordered collection: `["a", "b", "c"]`
- **Loop** = "do this for each item"
- **Dictionary** = labeled data: `{"name": "Acme", "ar_balance": 5000}`
- **Function** = a reusable named recipe

🛠️ **Do:** Try this — it's a baby version of what our real agents do:
```python
def is_actionable(account):
    return account["risk_tier"] == "High" and account["overdue_days"] >= 30

accounts = [
    {"name": "Acme", "risk_tier": "High", "overdue_days": 45},
    {"name": "Globex", "risk_tier": "Low", "overdue_days": 10},
]

for acct in accounts:
    if is_actionable(acct):
        print(acct["name"], "→ needs attention")
```

📂 **Read in our repo:** open [agents/collections/agent.py](../agents/collections/agent.py) and find the
real `is_actionable(...)` function near the top. It's the same idea as yours, just
with a couple more rules. **You can already read production code — notice that.**

✅ **Check yourself:** What's the difference between a list and a dictionary? What does a function give you?

---

## Day 5 — What is "data" and what is "the cloud"?

🎯 **Goal:** Explain, in plain words, the two ideas the whole platform rests on.

📖 **Learn:**
- **Data** here mostly means **tables**: rows and columns, like a spreadsheet
  (customers, invoices, orders). A **database** stores many tables and lets you
  ask questions with a language called **SQL** (next week).
- **The cloud** just means "someone else's very powerful computers you rent over
  the internet." We use **Azure** (Microsoft's cloud) and **Databricks** runs on top of it.
  We don't own the machines; we rent exactly what we need.

🛠️ **Do:**
- Skim the main [README.md](../README.md) at the project root. Look at the table
  "What this platform answers." You don't need to understand the how yet — just
  notice these are **business questions** turned into **data products**.
- In your learning log, write the one business question that sounds most interesting to you.

✅ **Check yourself:** What's a table? What does "the cloud" mean in one sentence? Which cloud do we use?

---

## 🏁 End of Week 1

You can now move around the terminal, read our Git history, write small Python, and
explain data + cloud. That's real progress.

**Deliverable:** In `my-learning-log.md`, write 5 sentences — one per day — on what
you learned. If you can explain the Day 4 `is_actionable` function to a friend, you're ready.

➡️ **[Week 2 — The Lakehouse](week-02-databricks-lakehouse.md)**
