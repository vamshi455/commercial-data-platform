# Platform Maturity Assessment — Advances, Gaps, What to Adopt

> Honest scorecard across five areas: what CDP genuinely advanced, where it lags
> current best practice, and the highest-leverage things to adopt. Some "advances"
> are partial/stubbed — flagged as such. Dated 2026-07-12.

## 1. Data platform architecture
- **✅ Advanced:** medallion; unstructured/RAG lane on the same medallion; two
  ingestion modes (Auto Loader files + Postgres JDBC); DABs multi-env; identity
  resolution design; amendment/`is_current` versioning.
- **⚠️ Gaps:** batch/triggered only (no streaming/real-time CDC); **Iceberg planned,
  not implemented**; JDBC *copies* (no zero-copy); gold isn't a true data-mesh
  product with SLAs.
- **🚀 Adopt:** **Lakehouse Federation** (zero-copy vs JDBC copy), **Iceberg via
  UniForm** (multi-engine, esp. Snowflake port), **streaming tables / real-time**.

## 2. Governance & reliability
- **✅ Advanced:** UC RBAC + masking + row filters + prod-strict env guard;
  dead-letter tables; DLT expectations; lineage via system tables; **AI hard-gate
  evals** (PII=0, injection=0).
- **⚠️ Gaps:** no DQ/drift monitoring; no enforced/versioned data contracts; ABAC
  not activated (D4); manual PII tagging; no SLOs/alerting.
- **🚀 Adopt:** **Databricks Lakehouse Monitoring** (drift/anomaly); **Open Data
  Contract Standard**; **UC Data Classification + ABAC** (both GA — replaces our
  manual/regex PII approach); **Metric Views** (certified semantic layer).

## 3. AI-enabled data engineering
- **✅ Advanced:** end-to-end RAG; **agent deployed** via Mosaic AI (UC model +
  serving); **eval framework** (LLM-judge + deterministic hard gates); **agentic
  actions** (collections monitor→diagnose→draft→HITL); managed embeddings.
- **⚠️ Gaps (biggest area):** 5 SQL agents are **stubs**; **retrieval metrics
  unscored** (no ground truth); no reranker / query-rewriting; no GraphRAG; **no
  memory (episodic/procedural)** — see [`specs/agent-memory.md`](./specs/agent-memory.md);
  no continuous/online eval or human-feedback loop wired; no guardrail model; MCP
  not built.
- **🚀 Adopt:** reranking + query rewriting + retrieval ground truth; **GraphRAG**;
  **agent memory + feedback loop**; AI Guardrails / Llama Guard; MCP + multi-agent;
  Databricks Assistant / AI-authored pipelines + auto DQ rules.

## 4. Cost / performance optimization
- **✅ Advanced:** genuinely disciplined — scale-to-zero serving, TRIGGERED index,
  repeated endpoint teardown, NAT-gateway avoidance, serverless/Photon, dev
  schedule pausing, recreate→run→delete pattern.
- **⚠️ Gaps:** no FinOps cost attribution/chargeback (cost app blocked); no budget
  policies / cost anomaly alerts; predictive optimization + liquid clustering
  documented but unconfirmed; no storage tuning (deletion vectors / VACUUM).
- **🚀 Adopt:** **system.billing cost dashboards + tag-based chargeback + budget
  policies + anomaly alerts**; predictive optimization + liquid clustering +
  deletion vectors on hot tables.

## 5. Cross-functional ownership of production systems
- **✅ Advanced:** DABs dev→qa→prod; **WIF/OIDC (no secrets)**; run-as SP for prod;
  RBAC personas; checkpoint + decision logs; layered tests (unit + DQ + AI evals);
  main-only git.
- **⚠️ Gaps:** **qa/prod not actually runnable** (workspaces deleted, no SP) —
  "production ownership" isn't real until prod runs; no SLOs/on-call/incident
  process; no freshness alerting; MDM backlog blocked on `gh auth login`; no
  self-service data-product catalog.
- **🚀 Adopt:** re-establish real qa/prod (SP + groups + workspaces); SLOs +
  alerting; data-mesh domain ownership; e2e integration tests in CI; self-service
  data-product marketplace (UC + Genie).

## Top 5 highest-leverage moves
1. **Lakehouse Monitoring + data contracts** — biggest reliability jump, least effort.
2. **Close the AI quality loop** — retrieval ground truth + reranking + **agent
   memory/feedback** + a guardrail model.
3. **FinOps cost dashboard** — unblock the cost app; you optimize cost but can't
   *measure* it.
4. **GraphRAG on contracts** — the genuine knowledge-base differentiator.
5. **Make prod real** — SP + qa/prod workspaces; nothing above is "production"
   until it runs there.

**Headline:** architecture, governance-first posture, cost discipline, and CI/CD
are strong-to-exemplary for a reference build. The real frontier gaps are
**(a) reliability *monitoring*, (b) AI *quality/safety/memory* beyond hard gates,
and (c) turning "deployed to dev" into "owned in prod."**
