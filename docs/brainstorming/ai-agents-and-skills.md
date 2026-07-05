# Brainstorming — AI Agent Use Cases & Skill Map

> **Status:** Brainstorm / requirement-honing (not a committed spec). Ideas here
> graduate into `docs/specs/*.md` when picked up for build.
> **Captured:** 2026-07-04

Context: what can we build on the existing infra (unified CRM + ERP gold data
products, Unity Catalog governance, and the new `contract_vector_search` Vector
Search index)? Two threads: **business use cases for AI agents**, and the
**skills** this project develops.

---

## 1. AI agent use cases (by business question)

Data available: `customer_360`, `revenue_pipeline`, `bookings_vs_billings`,
`collections_risk`, `support_performance`, `account_health`, `renewal_risk`,
plus contract documents in Vector Search.

### Revenue & Finance
- **Bookings-vs-billings agent** — "Which deals booked last quarter haven't been
  invoiced?" Flags revenue leakage from `bookings_vs_billings`.
- **Collections agent** — "Which at-risk accounts to chase this week, ranked by $
  and days overdue?" from `collections_risk`; can draft the dunning email.
- **Forecast / pipeline agent** — "Commit vs best-case for Q3, and which deals
  slipped?" over `revenue_pipeline`.

### Customer Success / Account Management
- **Renewal-risk save agent** — "Which renewals in the next 90 days are at risk,
  and why?" joins `renewal_risk` + `support_performance` + usage; builds a save-play.
- **Account 360 briefing agent** — "One-page brief on Account X before my call" —
  `customer_360` + open cases + pipeline + payment history.
- **Churn early-warning agent** — declining `account_health` + support ticket
  spikes → proactive AM alerts.

### Contracts (Vector Search / RAG)
- **Contract Q&A agent** — "Price-adjustment and force-majeure terms in the FOB
  cargo contracts with Counterparty Y?" — direct use of the contract index.
- **Obligation & expiry agent** — "Contracts expiring in 60 days and their
  renewal/auto-renew clauses?" — contract chunks + `renewal_risk`.
- **Contract-vs-billing reconciliation** — "Are we billing per the contracted
  price/terms?" cross-checks contract clauses against ERP invoices.

### Operations / Governance (internal)
- **Data steward agent** — lineage, freshness, PII sensitivity over `system.access.*` + tags.
- **Platform-ops agent** — overnight job failures / SLA breaches over `system.lakeflow.*`.

### Highest-ROI picks
1. **Contract-vs-billing reconciliation** (contracts + ERP) — finds money;
   impossible off-the-shelf because it needs *our* unified data.
2. **Renewal-risk save agent** (CRM + support + contracts) — protects recurring revenue.

---

## 2. Skill map this project develops

### Already exercised
- **Unity Catalog governance** — RBAC, masking, row filters, tags, lineage.
- **Lakeflow / DLT + Auto Loader** — incremental, idempotent ingestion.
- **Medallion + Delta/Iceberg** — MERGE, CDF, identity resolution.
- **Databricks Asset Bundles** — one bundle, dev/qa/prod, `${var}` parameterization.
- **Mosaic AI Vector Search / RAG** — Delta Sync index, managed embeddings, hybrid retrieval.
- **Azure admin + FinOps** — workspaces, VNets, NAT gateways, Cost Management API, cleanup.
- **CI/CD** — GitHub Actions, OIDC / Workload Identity Federation (secret-less).
- **Software craft** — pure-logic-vs-Spark separation, pytest, spec-driven dev.

### To add (designed-but-not-built = build backlog)
- **Agent / LLM engineering** — the `agents/` fleet: tool-calling, LangGraph,
  Model Serving, AI Gateway, guardrails, UC-as-security-boundary.
- **Observability & DQ** — DLT expectations, Lakehouse Monitoring, freshness/SLA,
  `system.*` queries, alerting (`docs/observability.md`).
- **Data contracts** — enforcement, breaking-change policy, schema evolution,
  contract tests in CI (`docs/data-contracts.md`).
- **ABAC** — attribute-based access beyond RBAC (`governance/abac_policies.sql`).

### Natural extensions (net-new)
- **Databricks SQL / BI** — dashboards, marts, AI/BI Genie, metric/semantic layer.
- **Streaming / CDC** — real-time CDC from Postgres (DLT streaming / Debezium).
- **Performance & FinOps** — liquid clustering, Z-order, OPTIMIZE, cost attribution
  via `CostCenter` tags.
- **MLOps** — MLflow, model registry, feature store, serving beyond RAG.
- **Testing automation** — local Spark pytest, DLT expectations, CI-gated integration tests.

**Single highest-value next build:** the **agent fleet** — combines governance +
RAG + LLM engineering; security design already written in `agents/`.

---

## 3. MCP tools for agents (enterprise, sales-oriented) — ⏳ PENDING, revisit

Goal: go through the full learning curve of **building and maintaining agents
that access MCP tools**. MCP keeps the agent constant and makes each enterprise
system a pluggable tool server.

### Use cases by risk tier

**Read-heavy (start here — low risk)**
- **Account briefing / meeting-prep agent** — Calendar MCP (today's meetings) +
  CRM MCP + Drive MCP → auto one-pager before each call. (Drive + Calendar MCP
  already available in the session.)
- **Pipeline / forecast Q&A agent** — a **Databricks MCP server** over gold
  products (`revenue_pipeline`, `bookings_vs_billings`) → "what's my Q3 commit?"
- **Contract Q&A agent** — Vector Search index as an MCP tool + Drive MCP to fetch
  the source PDF.

**Write-capable (the real maintenance learning curve)**
- **Pipeline-hygiene agent** — CRM MCP with write scope: update stale opps, flag
  missing close dates → auth scopes, idempotency, audit, approval-before-write.
- **Renewal / collections outreach agent** — Databricks MCP (`collections_risk`,
  `renewal_risk`) + Slack MCP to notify AM + Calendar MCP to book the save-call.
- **Deal-desk / quote agent** — Databricks MCP (pricing) + contract index + Slack
  approval flow.

### Common enterprise MCP servers to wire in
Salesforce / HubSpot (CRM), **Postgres** (server code already exists at
`/Users/vamshi/AzureAI/mcp-servers/postgresql`), Databricks, Slack, Google
Drive / Calendar / Gmail, Jira / Confluence, GitHub, web-fetch/search.

### Recommended learning path (grounded in this stack)
1. **Build a Databricks MCP server** exposing 2–3 read-only tools over gold views;
   wrap in one agent. Teaches the MCP tool contract + read-only guardrails.
2. **Register the existing Postgres MCP server** → agent reads the CRM source.
   Teaches connecting an existing server + auth.
3. **Add one write-capable tool** (Slack notify, or a CRM field update behind an
   approval gate). Teaches the hard part: permissions, idempotency, audit logging,
   human-in-the-loop.

Arc = read-only → connect-existing → write-with-guardrails = full build-and-maintain curve.

**Next when resumed:** spec step 1 (Databricks MCP server over gold products) into
`docs/specs/databricks-mcp-server.md` and scaffold it.

---

## Next step

Graduate one use case into a spec. Candidates for `docs/specs/`:
`contract-billing-reconciliation-agent.md`, `renewal-risk-save-agent.md`,
`databricks-mcp-server.md` (MCP learning path, step 1).
