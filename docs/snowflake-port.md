# Snowflake Port — Plan for a Parallel Commercial Data Platform on Snowflake

> **Goal:** stand up the *same* Commercial Data Platform on **Snowflake** — same medallion,
> same CRM/ERP + contract domains, same unstructured/RAG lane, same MCP + agents + evals — using
> Snowflake-native services instead of Databricks. Parity of *capability*, not code.
> **Status:** plan. **Biggest prereq:** a Snowflake account (ideally on **Azure** to match the
> existing landing storage). This is a multi-phase build, not a one-shot.
> **Related:** [`architecture.md`](./architecture.md), [`rag-unstructured.md`](./rag-unstructured.md),
> [`agent-evals.md`](./agent-evals.md), [`jobs-and-pipelines.md`](./jobs-and-pipelines.md).

---

## 1. Component mapping (Databricks → Snowflake)

| Concern | Databricks (today) | Snowflake (target) |
|---|---|---|
| Catalog / governance | Unity Catalog | **Horizon** (RBAC roles, tags, masking & row-access policies) |
| Namespace | catalog → schema | **database → schema** |
| Table format | Delta (+ managed Iceberg) | Snowflake native tables (+ **managed Iceberg** for open/external) |
| Landing storage | ADLS Gen2 UC **Volume** | **External Stage** on Azure blob + **Directory Table** |
| File ingestion | Auto Loader (`cloudFiles`) | **Snowpipe** / **Snowpipe Streaming** (auto-ingest on file arrival) |
| Declarative pipelines | Lakeflow/DLT | **Dynamic Tables** (declarative, incremental refresh) |
| Imperative pipelines | Jobs of Python tasks | **Streams + Tasks** (CDC + DAG orchestration) |
| Transform language | PySpark | **Snowpark** (Python/DataFrame) + SQL; **dbt** optional |
| Doc parsing | `ai_parse_document` | **`SNOWFLAKE.CORTEX.PARSE_DOCUMENT`** (Document AI) |
| Embeddings | FM API `gte-large-en` | **`SNOWFLAKE.CORTEX.EMBED_TEXT_1024`** (e5 / arctic-embed) |
| Vector search | Vector Search Delta Sync Index | **Cortex Search** (managed hybrid) *or* `VECTOR` column + `VECTOR_COSINE_SIMILARITY` |
| LLM calls | Foundation Model / external | **`SNOWFLAKE.CORTEX.COMPLETE`** (llama, mistral, Claude via Cortex) |
| SQL agents (text-to-SQL) | governed function-calling / Genie | **Cortex Analyst** (semantic model over gold) |
| RAG agents | Mosaic AI Agent + retriever | **Cortex Agents** + Cortex Search |
| MCP | (planned Databricks MCP) | **Snowflake MCP Server** (exposes Cortex Analyst + Search as MCP tools) |
| Evals | Mosaic AI Agent Evaluation + MLflow | LLM-as-judge via `CORTEX.COMPLETE` + `AI_CLASSIFY`; results in a table (MLflow optional/external) |
| Orchestration | Databricks Workflows (`job_*`) | **Task graphs** (serverless tasks) |
| Compute | serverless / Photon | **Virtual Warehouses** (auto-suspend/resume) |
| CI/CD | Asset Bundles + GitHub Actions | **Snowflake CLI (`snow`)** + Git integration / **schemachange** / Terraform; dbt for models |
| Secrets | Databricks secret scopes / Key Vault | **SECRET** objects + **External Access Integration** |
| Non-human identity | deploy service principal | **service user** (key-pair / OAuth) + role |
| Masking / row filters | UC column masks, row filters | **Masking Policies**, **Row Access Policies** |
| Tags / classification | UC tags | **Object Tagging** (+ tag-based masking) |
| Lineage / audit / cost | `system.access.*`, `system.billing.*` | **ACCOUNT_USAGE** (ACCESS_HISTORY lineage, WAREHOUSE_METERING, CORTEX usage) |

---

## 2. Target architecture (medallion on Snowflake)

```
 Azure blob (same landing files)
    │  External Stage + Directory Table
    ▼
 Snowpipe (auto-ingest) ─────────────► BRONZE tables (raw, VARIANT/typed + audit)
    │  Streams + Dynamic Tables / Snowpark
    ▼
 SILVER (Dynamic Tables): cleansed, conformed, identity resolution (CRM↔ERP)
    │
    ▼
 GOLD: customer_360, revenue_pipeline, bookings_vs_billings, … (marts)
    │                                   │
    ▼                                   ▼
 Cortex Analyst (semantic model)   Cortex Search (contract chunks) ── RAG
    │                                   │
    └────────── Cortex Agents / MCP tools ──────────┘  ← governed, role-scoped
```

Databases per env: **`CDP_DEV` / `CDP_QA` / `CDP_PROD`**; schemas `LANDING, BRONZE, SILVER, GOLD, OPS, CONTRACTS`.

---

## 3. Unstructured / contract RAG lane on Snowflake

Mirrors `contract_vector_search`, but fully Cortex-native — **no external embedding job, no
separate index endpoint to babysit** (Cortex Search is a managed service):

```
Stage (contract PDFs) ─► PARSE_DOCUMENT ─► parsed text
   ─► chunk (Snowpark UDF / SPLIT_TEXT_RECURSIVE_CHARACTER) ─► CONTRACTS.doc_chunks
   ─► CREATE CORTEX SEARCH SERVICE over doc_chunks (auto-embeds + indexes, TARGET_LAG controls freshness)
   ─► retrieval: SNOWFLAKE.CORTEX.SEARCH_PREVIEW(...) filtered on is_current = true
```

Two build options for the vector layer:
- **Cortex Search** (recommended) — managed hybrid (vector + keyword), handles embedding +
  indexing + freshness (`TARGET_LAG`); closest analog to the Delta Sync index.
- **DIY** — add a `VECTOR(FLOAT, 1024)` column, populate with `EMBED_TEXT_1024`, query with
  `VECTOR_COSINE_SIMILARITY`. More control, more plumbing (you own refresh).

Amendment/`is_current` logic ports directly (Streams+Task doing the MERGE, same as the Databricks Job).

---

## 4. Agents & MCP on Snowflake

- **SQL agents** (`revenue_insights`, `customer_health`, …) → **Cortex Analyst**: define a
  **semantic model** (YAML) over the gold marts; Analyst does governed text-to-SQL. Roles enforce access.
- **Contract RAG agent** → **Cortex Agents** orchestrating **Cortex Search** retrieval +
  `CORTEX.COMPLETE` generation, with citations.
- **MCP** → the **Snowflake MCP Server** exposes Cortex Analyst (structured) and Cortex Search
  (unstructured) as MCP tools to any MCP client — the Snowflake-native equivalent of the planned
  Databricks MCP server. Add custom tools via the SQL API behind a role + approval gate.

Governance parity: every agent runs under a **role** granted only on the approved gold/search
objects; masking policies keep PII masked in results.

---

## 5. Evals on Snowflake
Same taxonomy as [`agent-evals.md`](./agent-evals.md) (retrieval, generation, LLM-as-judge, safety,
performance, regression). Implementation differences:
- **Judge** = `SNOWFLAKE.CORTEX.COMPLETE(<strong model>, <rubric prompt>)`; classification via `AI_CLASSIFY`.
- **Golden set** = a Snowflake table (portable from the Databricks `eval_dataset`).
- **Retrieval metrics** = score `SEARCH_PREVIEW` output vs expected chunk ids in SQL/Snowpark.
- **Tracking** = an `OPS.EVAL_RESULTS` table + a dashboard; MLflow optional (external).
- **Cortex Analyst** has built-in accuracy tooling for the semantic model — use it for the SQL agents.

---

## 6. Cost model differences (watch these)
- **Virtual warehouses auto-suspend** — set `AUTO_SUSPEND=60s`; you pay per-second while active
  only. This is friendlier than an always-on endpoint, *but*…
- **Cortex Search service** has an ongoing **serving cost** (like the VS endpoint) — one per env
  that needs search; suspend/drop when idle.
- **Cortex functions** (COMPLETE/EMBED/PARSE) bill **per token / per page** — evals and embedding
  large corpora are the cost drivers; keep the golden set tight.
- **No NAT-gateway trap** (that was an Azure-Databricks-VNet issue) — but mind warehouse sizing
  and Cortex token spend instead.

---

## 7. Phased plan (mirrors the CDP roadmap)

| Phase | Deliverable |
|---|---|
| **0 Foundation** | Snowflake account (Azure region), `CDP_DEV` db + schemas, roles, warehouses, `snow` CLI + Git integration, external stage on the existing Azure blob |
| **1 Ingestion** | Snowpipe from stage → bronze; reuse the **existing synthetic generators** (they just write files) |
| **2 Silver** | Dynamic Tables / Snowpark: conform, CRM↔ERP identity resolution, DQ |
| **3 Gold** | The 7 marts; semantic model YAML for Cortex Analyst |
| **4 Contract RAG** | Stage → PARSE_DOCUMENT → chunk → Cortex Search; amendment/is_current |
| **5 Agents + MCP** | Cortex Analyst (SQL), Cortex Agents (RAG), Snowflake MCP Server |
| **6 Evals** | Port the golden set + judges; `OPS.EVAL_RESULTS` scorecard |
| **7 Governance + CI/CD** | Masking/row-access policies, tags, ACCESS_HISTORY lineage; `snow`/dbt deploy dev→qa→prod |

---

## 8. What's reusable vs. rewrite
- ♻️ **Reusable as-is:** the synthetic **data generators** (`data_gen/*` — they emit files), the
  **domain model** + business questions, the **eval golden set**, the **contract sample docs**,
  most **docs**.
- ✍️ **Rewrite:** all pipeline code (PySpark→Snowpark/SQL), DLT→Dynamic Tables, Auto Loader→Snowpipe,
  Vector Search→Cortex Search, agents→Cortex Analyst/Agents, bundle→`snow`/dbt, UC policies→Snowflake policies.
- 🟰 **Roughly 1:1 concepts** (fast to port): medallion layering, masking/row-access, roles↔personas,
  tags, the identity-resolution logic, the amendment/is_current pattern.

---

## 9. Open questions / decisions before building
1. **Snowflake account** — do we have one? Which **cloud + region** (Azure, to reuse the landing blob)?
2. **Transform tooling** — **dbt** (portable, popular) vs **pure Snowpark/SQL** for silver/gold?
3. **Vector layer** — **Cortex Search** (managed, recommended) vs DIY `VECTOR` columns?
4. **Repo strategy** — same repo (`/snowflake` subtree) vs a separate repo? Shared generators either way.
5. **Scope of first slice** — full parity, or a thin vertical (ingest → one gold mart → Cortex
   Analyst → one agent) to prove the stack first? (recommended: thin vertical first.)
