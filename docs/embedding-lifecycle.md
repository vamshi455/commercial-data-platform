# Embedding Lifecycle — Add, Update, Amend, Delete (and the test scenarios)

> **Scope:** what happens to the vector index when a contract PDF is added, changed,
> superseded, or removed — and the scenarios that prove it. Complements
> [`agent-evals.md`](./agent-evals.md) (which grades *answers*); this document is about
> whether the **index reflects reality**.
> **Status:** written 2026-07-16 from an evidence-based audit of a live run.
> **Verdict: the corpus is effectively APPEND-ONLY.** New documents work; in-place
> updates and deletions do not.

---

## 1. Why this matters

Answer quality is meaningless if the index is stale. Three failure modes are invisible to
the eval harness because every one of them produces a *fluent, well-cited, confidently
wrong* answer:

- The agent cites a contract that **was deleted** from the source volume.
- The agent quotes the **old terms** of a contract that was revised in place.
- The agent retrieves **orphaned chunks** left behind by a re-chunk.

`agent-evals.md` grades the answer given the index. **Nothing currently grades the index
against the source volume.** That is the gap this document names.

---

## 2. How the pipeline decides what to process (the mechanics)

```
Volume (*.pdf) ──► bronze ──► silver ──► gold ──► Delta Sync index
                     │          │         │
             Auto Loader   anti-join   MERGE on
             checkpoint    on          chunk_id
             (by PATH)     source_file (no DELETE)
```

Three independent gates decide whether a document is (re)processed:

| Gate | Where | Keyed on | Consequence |
|---|---|---|---|
| Auto Loader checkpoint | `01_bronze_ingest.py` | **file path** | A path already seen is never re-read — *even if its bytes changed* |
| Anti-join | `02_silver_parse_chunk.py` | `source_file` | A file already in silver/failures is never re-parsed |
| `MERGE ... ON chunk_id` | `03_gold_merge.py` | `chunk_id` | Only `WHEN MATCHED`/`WHEN NOT MATCHED` — **no `NOT MATCHED BY SOURCE ... DELETE`** |

`chunk_id = sha2(source_file || ':' || chunk_seq)` — deterministic, which is what makes
re-runs idempotent. It is also why nothing is ever removed: a chunk that no longer has a
source simply stops being visited by the MERGE, and lingers with `is_current = true`.

**Evidence (2026-07-16):** purging the oil corpus required manually deleting the PDFs,
deleting the Auto Loader checkpoint, and `TRUNCATE`-ing four tables. The pipeline offered
no supported path to remove a document. That is the bug, observed.

---

## 3. Scenario matrix

Legend: ✅ works (verified) · ⚠️ designed but unproven · ❌ broken

| # | Scenario | Expected behavior | Today | Notes |
|---|---|---|---|---|
| **E1** | **New PDF lands** | Ingested, chunked, masked, indexed, retrievable | ✅ | Verified: 6 docs → 6 chunks → agent answered correctly |
| **E2** | **Re-run with no changes** | Idempotent — no dupes, no version bump, no re-embed | ✅ | Deterministic `chunk_id` + MERGE; `detect_amendments` no-ops on same file (unit-tested) |
| **E3** | **PDF modified in place** (same filename) | New terms indexed; old terms unretrievable | ❌ | **Silently ignored.** Checkpoint says "path seen"; anti-join says "file parsed". The agent keeps serving the OLD text forever with no error |
| **E4** | **Amendment** (new filename, same `contract_id`) | Prior version `is_current=false`; new version current; agent cites only the new | ⚠️ | Logic exists + unit-tested; **never exercised live** |
| **E5** | **PDF deleted from the volume** | Chunks removed from gold + index; agent can no longer cite it | ❌ | **Chunks persist with `is_current=true`.** Agent will cite a document that no longer exists |
| **E6** | **Re-chunk yields FEWER chunks** (5 → 3) | Chunks 3–4 removed | ❌ | **Orphans.** MERGE never deletes; stale chunks stay retrievable |
| **E7** | **Corrupt / unparseable PDF** | Dead-lettered; index unaffected | ✅ | Verified: `ParseShapeError` sent 6 docs to `silver_parse_failures`, index untouched |
| **E8** | **Superseded contract never returned** | `is_current=false` chunks excluded from retrieval | ✅ | `retriever.py` filters `is_current=true` by default — but depends on E4/E5 marking it |
| **E9** | **Embeddings refresh on content change** | Changed `chunk_text` → re-embedded via CDF | ⚠️ | CDF→Delta Sync is wired, but unreachable while E3 is broken |
| **E10** | **Index freshness** | New contract retrievable within the sync window | ⚠️ | `TRIGGERED` sync + file-arrival trigger; lag never measured |

**The three that matter: E3, E5, E6 — all silent.** None raises, none dead-letters, none
shows up in a gate. They degrade answer *truth* while every quality metric stays green.

---

## 4. What the fixes look like

**E5 + E6 — deletions and orphans. They are DIFFERENT fixes, and neither needs a full load.**

> ⚠️ **The trap:** adding `WHEN NOT MATCHED BY SOURCE ... THEN DELETE` to the existing
> MERGE is *wrong*. On an incremental run the staged source holds only the files just
> processed, so every other document's chunks are "not matched by source" and get wiped.
> That design silently forces a full reload of the whole corpus on every run. The fix is
> not "delete inside the MERGE" — it is **picking the right source for each reconcile**.

**E5 — a file was removed from the volume.** Reconcile against the **volume listing**, which
is a directory listing (cheap metadata — no PDF is read, parsed, or re-embedded). Incremental
ingest stays incremental; this is a separate, cheap statement:

```sql
-- SOURCE = every file currently in the volume (a listing, not the batch).
-- "Not matched by source" therefore means: this file no longer exists.
MERGE INTO gold_contract_chunks AS t
USING (SELECT path AS source_file FROM volume_listing) AS v
  ON t.source_file = v.source_file
WHEN NOT MATCHED BY SOURCE THEN
  UPDATE SET t.is_current = false, t._merged_at = current_timestamp();   -- soft delete
```

**E6 — a still-present file re-chunked into fewer chunks.** Scope the delete to *only the
files this run touched*, so untouched documents are never candidates:

```sql
MERGE INTO gold_contract_chunks AS t
USING staged_chunks AS s ON t.chunk_id = s.chunk_id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...
WHEN NOT MATCHED BY SOURCE
  AND t.source_file IN (SELECT DISTINCT source_file FROM staged_chunks)  -- ← the guard
  THEN DELETE;
```
That predicate is what keeps it incremental: a chunk is only deletable if its own file was
reprocessed in this run and no longer produces that `chunk_seq`.

**Soft vs hard delete.** Soft (`is_current=false`) is preferred: the retriever already
filters `is_current=true`, so retirement takes effect immediately, it keeps an audit trail
of what was withdrawn and when, and it is reversible. Hard delete actually shrinks the index
(and its cost) but destroys lineage. Recommend **soft for E5** (a withdrawn contract is a
governance event worth recording) and **hard for E6** (an orphaned chunk is an artifact, not
a fact — nobody will ever ask "what did chunk 4 used to say?").

**Cost note:** the volume listing is O(files) metadata, run once per pipeline execution.
For a corpus of hundreds or thousands of PDFs this is negligible next to `ai_parse_document`
on a single new file.

**E3 — in-place updates.** Auto Loader keys on path, so content changes are invisible.
Options:
1. **Content-hash the bytes** in bronze and re-parse when the hash changes for a known path
   (bronze already captures `content` + `modificationTime`).
2. **Anti-join on (source_file, content_hash)** instead of `source_file` alone, so silver
   re-parses a changed file.
3. Convention: **never modify in place — always land a new filename** (turns E3 into E4,
   which the amendment logic already handles). Cheapest, but a convention is not a control.

Recommended: (1)+(2) — make the pipeline correct, rather than depend on discipline.

---

## 5. Test scenarios to build

Each is an **integration** test (needs the pipeline + index), distinct from the pure unit
tests and from the answer-grading eval. Cheapest home: a `job_embedding_lifecycle` that
runs the scenarios against a scratch schema and asserts on gold/index state.

| Test | Steps | Assertion |
|---|---|---|
| `test_new_pdf_is_indexed` | land → run → query | chunk present, retrievable, PII masked |
| `test_rerun_is_idempotent` | run twice | same `chunk_id`s, same row count, `version` unchanged |
| `test_modified_pdf_reindexes` (E3) | land → run → **edit content, same name** → run | new term retrievable, old term NOT |
| `test_amendment_retires_prior` (E4) | land v1 → run → land v2 (new name, same `contract_id`) → run | v1 `is_current=false`; agent cites v2 only |
| `test_deleted_pdf_leaves_index` (E5) | land → run → delete file → run | chunks gone/retired; agent cannot cite it |
| `test_rechunk_removes_orphans` (E6) | index doc → shrink it → run | no chunk with `chunk_seq` ≥ new count |
| `test_unparseable_pdf_dead_letters` (E7) | land corrupt file → run | row in `silver_parse_failures`; index unaffected |
| `test_superseded_never_retrieved` (E8) | after E4 | retrieval returns no `is_current=false` chunk |
| `test_index_freshness_within_sla` (E10) | land → measure to retrievable | lag < agreed window |

**Start with E5 and E3** — they are the ones that make the agent lie, and they're what the
"modified PDF should show in agent chat" scenario (backlog A6) actually depends on.

---

## 6. Relationship to the eval harness

| | `agent-evals.md` | this document |
|---|---|---|
| Question | "Given the index, is the answer good?" | "Does the index match the source volume?" |
| Grades | answers | pipeline state |
| Catches | hallucination, PII, injection | staleness, orphans, ghost documents |
| Runs | `job_agent_eval` | `job_embedding_lifecycle` (to build) |

A perfect eval score over a stale index is precisely the failure this platform is supposed
to prevent — governed, current, cited answers. **E5 is a governance bug, not a bug fix
backlog item:** an agent that cites a deleted contract is worse than one that says "I don't
know."

---

## 7. Postscript — pick the right tool per gate

Observed 2026-07-16 while making the eval honest. `is_refusal` is a keyword list. It was
patched once (to catch *"I don't see a X in the provided context"*), and the very next live
answer broke it again:

> *"I don't have access to revenue or booking metrics — my scope is limited to contract
> terms... please consult the revenue_insights agent."*

A textbook decline-and-route. Scored `False`, because the list has `"please contact"` not
`"please consult"`, and no entry for `"don't have access"` or `"my scope is limited"`.

Two misses in two attempts is not a missing keyword — it is the wrong mechanism. **"Did the
agent decline?" is a semantic judgement with unbounded phrasings; string matching cannot
close it.** Adding a third batch of keywords buys the next single answer and fails on the
one after.

| Gate | Right tool | Why |
|---|---|---|
| PII leak | **regex** (deterministic) | PII has an exact shape; a match is a match |
| Injection obeyed | **exact canary match** | The canary is a literal we chose; no ambiguity |
| Citation accuracy | **parse + set compare** | Mechanical, once the regex accepts real formats |
| **Refusal / scope-routing** | **LLM judge** ← change this | Unbounded phrasings; semantic by nature |

The deterministic-vs-judge split in `agent-evals.md` §2C is right in principle — the mistake
was putting refusal on the deterministic side. Keep it as a *hint*, but gate on a judge
(Mosaic AI's `guideline_adherence` fits: "the agent must decline and route metric questions").
Until that lands, `refused` is **advisory, not a gate** — and the `edge-empty` /
`safety-scope` rows will keep under-reporting correct behavior.
