# Commercial Data Platform

A production-style Databricks lakehouse that unifies a **Salesforce-like CRM** domain and an
**SAP-like ERP** domain into governed, analytics-ready, and AI-ready data products.

It is built to look and operate like a real enterprise commercial data platform — not a learning
lab — using the current Databricks stack: **Unity Catalog** governance, **Lakeflow / DLT
declarative pipelines**, **Auto Loader** ingestion, a **medallion (bronze→silver→gold)**
architecture, a **Delta + selective Managed Iceberg** table strategy, and automatic **lineage**.

**Delivery model** (`dev → qa → prod`):

- **Databricks Asset Bundles (DABs)** — infrastructure-as-code: jobs, pipelines, and
  permissions are declared in `databricks.yml` + `resources/*.yml`, deployed per target.
- **GitHub Actions** — delivery: PR validation and gated promotion to qa/prod
  (`.github/workflows/`).
- **OIDC federation (Workload Identity Federation)** — authentication: CI assumes a
  service principal via GitHub OIDC, **no stored Databricks secrets**.

> **Workspace:** `https://adb-7405618019865738.18.azuredatabricks.net` (Azure Databricks)
> **Catalogs:** `cdp_dev`, `cdp_qa`, `cdp_prod`

---

## What this platform answers

| Business question | Gold data product |
|---|---|
| Who are our customers, end-to-end? | `gold.customer_360` |
| What's in the sales pipeline? | `gold.revenue_pipeline` |
| Are we billing what we book? | `gold.bookings_vs_billings` |
| Which accounts are a collections risk? | `gold.collections_risk` |
| How is support performing? | `gold.support_performance` |
| Which accounts are healthy / at-risk? | `gold.account_health` |
| Which renewals are at risk? | `gold.renewal_risk` |

---

## Architecture at a glance

```
 Synthetic generators                 Unity Catalog (governance, lineage, RBAC, masking)
 (CRM + ERP + reference)         ┌───────────────────────────────────────────────────────┐
        │                        │                                                         │
        ▼                        │   LANDING        BRONZE          SILVER         GOLD     │
 ┌──────────────┐  Auto Loader   │  (volumes)   (Delta, raw    (Delta, conformed (Delta +  │
 │ UC Volume    │ ─────────────► │   files  ─►   + audit)  ─►   + DQ + identity ─► Iceberg) │
 │ landing/files│  (incremental) │                              resolution)                 │
 └──────────────┘                │      Lakeflow / DLT declarative pipelines + expectations │
                                 └───────────────────────────────────────────────────────┘
                                                         │
                            ┌────────────────────────────┼───────────────────────────┐
                            ▼                            ▼                            ▼
                     Databricks SQL              AI / Agents                  Observability
                  (dashboards, marts)     (governed curated views only)   (lineage, DQ, SLAs)
```

Full detail: **[docs/architecture.md](docs/architecture.md)**.

---

## Repository layout

```text
commercial-data-platform/
├── README.md                  ← you are here
├── databricks.yml             ← Asset Bundle root: dev/qa/prod targets
├── docs/                      ← architecture, governance, pipelines, cicd, env, agents...
├── data_gen/                  ← synthetic CRM + ERP + reference data generators
├── src/pipelines/             ← Lakeflow/DLT pipeline code
│   ├── ingestion/             ← Auto Loader landing → bronze
│   ├── bronze/                ← raw, source-faithful + audit columns
│   ├── silver/                ← cleansed, conformed, identity-resolved, DQ-checked
│   └── gold/                  ← business marts (Delta) + Iceberg products
├── resources/                 ← bundle resources: pipeline + job YAML definitions
├── governance/                ← catalogs/schemas, grants, masking, row filters, tags (SQL)
├── notebooks/                 ← setup, observability, lineage, analytics
├── tests/                     ← data-quality + pipeline-validation tests
├── agents/                    ← business + platform agent stubs (curated data only)
├── scripts/                   ← deploy helpers
└── .github/workflows/         ← CI/CD: validate, deploy-qa, deploy-prod
```

---

## Quick start

### 1. Prerequisites
- Databricks workspace with Unity Catalog enabled (you have one).
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) ≥ 0.220 (`databricks --version`).
- Workspace admin (or metastore admin) to create catalogs/schemas/grants once.
- Python 3.10+ for the local generators.

### 2. Authenticate the CLI
```bash
databricks configure        # or: databricks auth login --host https://adb-7405618019865738.18.azuredatabricks.net
```

### 3. One-time platform setup (catalogs, schemas, volumes, grants)
Run the SQL in [governance/](governance/) (or notebook `notebooks/setup/`) per environment:
```bash
# creates cdp_dev / cdp_qa / cdp_prod, their schemas, the landing volume, and persona grants
databricks bundle deploy -t dev
databricks bundle run job_platform_setup -t dev
```

### 4. Generate + land synthetic source data
```bash
python data_gen/crm_generator.py        --out data_gen/output/crm   --days 90
python data_gen/erp_generator.py        --out data_gen/output/erp   --days 90
python data_gen/reference_data_generator.py --out data_gen/output/reference
# upload to the landing volume (or point Auto Loader at it)
databricks fs cp -r data_gen/output dbfs:/Volumes/cdp_dev/landing/files
```

### 5. Deploy & run the pipelines
```bash
databricks bundle validate -t dev
databricks bundle deploy   -t dev
databricks bundle run job_orchestration_daily -t dev
```

Promotion to `qa` / `prod` is the **same commands with `-t qa` / `-t prod`** — see
**[docs/cicd.md](docs/cicd.md)** and **[docs/environments.md](docs/environments.md)**.

---

## Documentation map

| Doc | What it covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | End-to-end design, medallion layers, data flow, table-format strategy |
| [docs/source-systems.md](docs/source-systems.md) | CRM + ERP entities, behaviors, PII model, data contracts |
| [docs/data-contracts.md](docs/data-contracts.md) | Per-entity schemas, keys, SLAs, refresh cadence |
| [docs/pipelines.md](docs/pipelines.md) | Ingestion / silver / gold pipelines, DQ rules, expectations |
| [docs/jobs-and-pipelines.md](docs/jobs-and-pipelines.md) | Deployed jobs & pipelines: tasks, DAGs, triggers, compute, cost |
| [docs/agent-evals.md](docs/agent-evals.md) | Agent & RAG evaluation: scenarios, LLM-as-judge, metrics, deploy steps |
| [docs/snowflake-port.md](docs/snowflake-port.md) | Plan to build the same platform on Snowflake (Cortex/Search/Analyst/MCP) |
| [docs/specs/agentic-actions.md](docs/specs/agentic-actions.md) | Agents beyond BI: monitor→diagnose→draft→HITL→learn; portfolio + shared infra |
| [docs/specs/agent-memory.md](docs/specs/agent-memory.md) | Agent memory: working/semantic/episodic/procedural/context-builder/model |
| [docs/maturity-assessment.md](docs/maturity-assessment.md) | 5-area maturity scorecard: advances, gaps, what to adopt |
| [docs/databricks-gotchas.md](docs/databricks-gotchas.md) | Serverless/agent/Vector Search gotchas learned the hard way |
| [docs/governance.md](docs/governance.md) | Unity Catalog RBAC, personas, masking, tags, lineage |
| [docs/environments.md](docs/environments.md) | dev/qa/prod model, catalogs, schemas, promotion |
| [docs/cicd.md](docs/cicd.md) | Asset Bundles + GitHub Actions, branch strategy, promotion gates |
| [docs/observability.md](docs/observability.md) | Lineage, freshness, DQ, SLA dashboards, system tables |
| [docs/agents.md](docs/agents.md) | AI agents, what data they may touch, guardrails |
| [docs/naming-conventions.md](docs/naming-conventions.md) | Catalog/schema/table/column/job naming standards |
| [docs/project-plan.md](docs/project-plan.md) | 7 phases, deliverables, milestones |

---

## Design principles

1. **Governance-first** — sensitivity is modeled from day one; PII is restricted in bronze, masked in gold.
2. **Declarative over imperative** — transformations are DLT/Lakeflow with expectations, not ad-hoc notebooks.
3. **Same code, many environments** — one bundle, config-only differences across dev/qa/prod.
4. **Agents consume curated views only** — never raw bronze, never unmasked PII.
5. **Everything is lineage-traceable** — Unity Catalog captures it automatically; we report on it.

---

*Built as an enterprise reference implementation. See [docs/project-plan.md](docs/project-plan.md) for the phased roadmap.*
