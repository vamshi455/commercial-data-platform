# Token & LLM Cost — Where It Goes and How to Keep It Down

> **Scope:** the `contract_intelligence` RAG agent and its eval loop — every place a request
> pays for LLM or embedding tokens, what it costs today, and the levers that keep it cheap as
> the corpus and eval set grow. Complements [`jobs-and-pipelines.md`](./jobs-and-pipelines.md)
> §6/§7 (compute/endpoint cost — VS endpoint always-on billing, idle-compute sweep) — **this
> doc is about tokens/API calls, not standing infrastructure.**
> **Status:** written 2026-07-16 against the current code (10-row golden set, 6-doc/1-chunk
> corpus, `databricks-claude-sonnet-5`).

---

## 1. Where tokens actually get spent

| Call site | Model | Per-call volume | Frequency |
|---|---|---|---|
| Agent generation | `databricks-claude-sonnet-5` (`agent.py`/`model.py`) | input = system prompt (~115 words) + `k=5` retrieved chunks + question; output capped `max_tokens=800` | every Playground/prod request, + 1 per eval row |
| Mosaic AI built-in judges | Databricks-managed judge model (opaque) | question + answer + retrieved context, per judge | 4 judges (`correctness`, `groundedness`, `relevance_to_query`, `safety`) × every golden row, **only during `job_agent_eval`** |
| Query embedding | `databricks-gte-large-en` | 1 embed call per question (the query vector) | every retrieval call, i.e. every generation call above |
| Ingest embedding | `databricks-gte-large-en` | 1 embed call per chunk | only on new/changed docs (append-only today) |

Custom scorers in `src/evals/custom_judges.py` (`detect_pii_leak`, `citation_accuracy[_paged]`,
`injection_obeyed`, `retrieval_scores`, `is_refusal`) are **pure Python — zero LLM cost.** They
run in plain pytest, off-cluster, for free.

---

## 2. Why it's cheap today

- **Corpus is 6 docs, 1 chunk/doc** (`docs/embedding-lifecycle.md` E1) — `k=5` retrieval already
  pulls ~83% of the whole corpus into context on every question, but each chunk is a short
  one-page contract, so total context stays small.
- **Eval run = 10 golden rows × (1 generation + 4 judges) ≈ 50 LLM calls**, each over short
  context.
- **Serving endpoint:** `scale_to_zero_enabled=true`, `workload_size="Small"` (Agent Framework
  default — not hardcoded in `deploy_contract_agent.py`) → zero idle token/compute cost between
  requests.
- **`max_tokens=800`** caps output on every generation call already — no runaway completions.

---

## 3. The driver everyone will hit next: corpus growth

`k=5` currently works only because it's implicitly sized to "grab nearly the whole tiny corpus."
The pending decision to lengthen contracts into real multi-page, multi-chunk documents (tracked
in `docs/embedding-lifecycle.md` and `docs/checkpoint.md` — needed so recall@5/MRR stop being
trivially 1.0) changes that math: once chunks carry real paragraph-sized content, `k=5` pulls
**5 substantive chunks**, not 5 near-empty ones — multiplying per-query context tokens.

**Before lengthening the corpus:** re-tune `k` downward (e.g. 3–4) and/or cap total retrieved
characters, rather than carrying `k=5` over unexamined from the small-corpus era.

---

## 4. Eval-loop cost compounds during dev iteration

Every `job_agent_eval` run burns ~50 paid LLM calls (10 generation + 40 judge). Re-running it
after every small fix — which happened repeatedly this session — adds up fast for a golden set
that will only grow.

**Lever already in place, use it more:** the deterministic gates in
`tests/pipeline_validation/test_custom_judges.py` run at zero LLM cost. Get those green *first*
(`pytest tests/ -v`) and only trigger the paid `job_agent_eval` once they pass — don't spend
judge-call budget confirming something a free test already tells you will fail.

---

## 5. A pending fix with a real cost tradeoff: `is_refusal`

`docs/embedding-lifecycle.md` §7 recommends replacing the keyword-based `is_refusal` (which
missed two real refusals live) with an LLM judge such as Mosaic AI's `guideline_adherence`. That
is the right correctness call — but it adds a **5th judge call × every golden row** to every
future eval run (today: +10 calls per run, and it scales linearly with golden-set size from
there). Not a reason to skip the fix — just a reason to keep the golden set deliberately sized
once it lands, rather than growing it unboundedly.

---

## 6. System prompt duplication — a drift risk, not a token multiplier

`SYSTEM_PROMPT` is byte-duplicated across `agent.py` and `model.py` (~115 words, kept in sync by
`test_agent_retrieval_parity.py`). Duplication itself doesn't double cost — only one copy is
sent per request, whichever surface serves it. But every word in it is paid **on every single
request** (generation and eval alike), so keep it tight as it grows; a longer prompt is a
permanent per-call tax, not a one-time cost.

---

## 7. Levers, ranked by leverage

1. **Gate on deterministic tests before spending on `job_agent_eval`** — free vs. paid, already
   possible today, just needs to be habit.
2. **Re-tune `k` when the corpus grows** — don't inherit `k=5` from the 1-chunk-per-doc world.
3. **Keep the golden set deliberately sized** — each row is 1 generation + N judge calls,
   recurring on *every* eval run, forever.
4. **Keep the system prompt tight** — paid on every request, not just eval.
5. **Keep `max_tokens=800`** — don't raise the output cap without a concrete reason.
6. **Heavy Playground exploration is still pay-per-token** on `claude-sonnet-5` — no prompt
   caching is wired into this stack today; worth checking whether the Databricks Foundation
   Model API route for this model exposes prompt caching before assuming there's none available.
7. **Embedding cost is a separate stream** (`gte-large-en`) — one call per ingested chunk (rare,
   append-only) and one per query (every retrieval). Cheap now at 6 docs; scales with corpus
   size and production query volume, independent of the chat-model cost above.

---

## 8. Already optimized — leave these alone

- `scale_to_zero=True` + `workload_size="Small"` on the serving endpoint — zero idle cost.
- The VS Search endpoint's always-on cost is a separate (non-token) concern, already handled by
  `scripts/check_idle_compute.sh` (see `jobs-and-pipelines.md` §7.1).
- Deterministic scorers in `custom_judges.py` run at zero LLM cost — no reason to move any of
  them to a judge except `is_refusal` (§5), and that's a correctness call, not a cost-saving one.

---

## 9. Not yet measured — open gap

No token-count or dollar-cost logging exists in `run_agent_eval.py` or `model.py` today —
per-eval-run and per-production-request cost is not currently captured anywhere. MLflow traces
capture latency/spans (`model.py` wraps `predict()` in a single `@mlflow.trace` span; no
per-stage retrieve/generate split), but this repo doesn't currently surface or aggregate token
usage from them.

**Recommended next step:** add a token-usage summary to `job_agent_eval` (pull usage metadata
off the MLflow trace for each call) so cost-per-eval-run becomes a visible, trended number
instead of an unmeasured assumption.
