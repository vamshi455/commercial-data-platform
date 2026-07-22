# CLAUDE.md

## Response style
- Be concise. Keep answers short — minimize lines.
- Lead with the answer; cut preamble, recaps, and restating the question.
- Avoid long tables/lists unless asked. Prefer a few tight sentences.
- Don't over-explain trade-offs; give the recommendation, not a survey.

## Execution
- Do NOT spin up compute / run warehouse or cluster queries unless absolutely needed. Prefer writing files and using metadata/CLI; only execute against compute when there's no other way to do the task.

## Azure workspace provisioning
- AVOID NAT gateways. When creating any qa/prod (or new) Databricks workspace, do NOT enable No-Public-IP / Secure Cluster Connectivity — an NPIP workspace with a Databricks-managed VNet auto-provisions a NAT gateway that bills ~$32/mo per workspace whether idle or not.
- Provision workspaces public-IP (NPIP disabled), matching dev (`enableNoPublicIp=false`, managed VNet) — no NAT gateway, no idle egress cost.
- If NPIP is ever required for security, get explicit sign-off first, since it forces the NAT-gateway cost.

## Session deliverables log
At the end of each substantial session, append a dated section below: a short table of
what was delivered (grouped by module, not every file), its purpose, and where it fits in
the existing landscape. Goal: keep the project auditable and avoid silent bloat. Keep it
brief — one row per module/area, not per file.

### 2026-07-19 — VRR Reasoning & Lineage agent (new module)
New self-contained module implementing the external VRR design (oil & gas Voidage
Replacement Ratio). Isolated in its own `cdp_dev` schemas (`vrr_raw`/`vrr_curated`/`vrr_agent`)
so it never mixes with the commercial bronze/silver/gold. Nothing existing was modified except
`databricks.yml` (added a `warehouse_http_path` var) and this file.

| Module / artifact | Purpose | Fits into landscape |
|---|---|---|
| `src/vrr_agent/config.py`, `physics.py` | Env config + deterministic reservoir math (PVT interp, reservoir volumes) | Same config/pure-helper pattern as `src/contract_vector_search/` |
| `src/vrr_agent/vrr_build.sql` | Faithful Databricks port of the production `vrr_sql_builder.sql` (11 checkpoints): raw→`completion_contrib`→VRR | The canonical transformation; parallels the ERP/contract pipelines |
| `src/vrr_agent/tools.py` | Deterministic tools `VRR_GET/DECOMPOSE/LINEAGE` + OpenAI tool schemas + data layers (Spark/SQL-warehouse/in-memory) | The agent's governed read surface over `vrr_curated` |
| `src/vrr_agent/agent.py` | Reasoning agent: LLM narrates tool output (never computes) + deterministic faithfulness gate | Same "LLM drafts, deterministic gate" pattern as `agents/collections/` |
| `src/vrr_agent/01_setup_schemas.sql`, `02_seed_raw.py`, `03/04_*`, `gen_load_sql.py` | Schema DDL + synthetic seed + build/aggregation (PySpark + a warehouse-only SQL loader) | Mirrors the bronze→silver→gold build style |
| `src/vrr_agent/05_register_uc_functions.sql` | `vrr_get`/`vrr_lineage` as governed UC table functions | Same UC-function-as-tool idea in `docs/agents.md` option (c) |
| `src/vrr_agent/app/` | §9.5 report app (Streamlit + Plotly + PDF, clickable lineage) | Peer of the reconciliation/report apps |
| `agents/vrr_reasoning/model.py` | Servable `ChatAgent` with a native **tool-calling loop** (5 tools incl. discovery: `VRR_LIST_PATTERNS`/`VRR_OVERVIEW` for open-ended questions) + MLflow trace spans | Same deploy contract as `agents/contract_intelligence/model.py` |
| `notebooks/agents/deploy_vrr_agent.py`, `resources/deploy_vrr_agent.job.yml` | Log→register→`agents.deploy` (UC model `cdp_dev.vrr_agent.vrr_reasoning` + serving endpoint) | Mirrors `deploy_contract_agent.*` |
| `src/vrr_agent/06_build_lineage_graph.sql`, `07_lineage_uc_functions.sql` + `vrr_agent.lineage_node`/`lineage_edge` | **Value-level lineage graph** (Delta node/edge tables, NOT a graph DB — per `docs/knowledge-graph.html`) + `vrr_impact`/`vrr_trace` UC functions; adds `VRR_IMPACT` (what-if) + `VRR_LINEAGE_GRAPH` tools | Persists what `VRR_LINEAGE` computed per-query; complements (doesn't duplicate) Unity Catalog table lineage |
| `src/vrr_agent/tests/` | Off-cluster unit tests (physics, tools, tool dispatch, faithfulness, graph impact/trace) | Same pytest-off-cluster convention as `src/evals/` |

Deployed live to dev: UC model + scale-to-zero serving endpoint `agents_cdp_dev-vrr_agent-vrr_reasoning`.
Email/SMTP report-delivery direction was explored then **dropped**; instead added discovery tools
so the agent answers open-ended questions. Not yet built: a feedback loop (Review App + agent eval).

### 2026-07-22 — MLflow 3 real-time tracing + GenAI monitoring for the contract agent
Brought `contract_intelligence` up to the VRR agent's MLflow-3 standard (the VRR path
already ran `mlflow>=3.1.3`/`databricks-agents>=1.2.0` + `setup_vrr_monitoring`).

| Module / artifact | Purpose | Fits into landscape |
|---|---|---|
| `notebooks/agents/deploy_contract_agent.py` | Pin `mlflow>=3.1.3`/`databricks-agents>=1.2.0` (was unpinned) + set a dedicated NON-Git trace experiment (`/Users/<me>/contract_agent_traces`) before `log_model` so `@mlflow.trace` spans stream live per request | Mirrors `deploy_vrr_agent.py` |
| `notebooks/agents/setup_contract_monitoring.py` + `resources/contract_monitoring.job.yml` | Enable Lakehouse Monitoring for GenAI (beta): register Safety (1.0) + grounded-citation Guidelines (0.5) scorers on the endpoint's trace experiment, resolved BY NAME (no hardcoded id) | Peer of `setup_vrr_monitoring.py`/`vrr_monitoring.job.yml` |

Not yet run against dev — re-run `job_deploy_contract_agent` then `job_setup_contract_monitoring`.

### 2026-07-22 — VRR module EXTRACTED to its own repo
The entire VRR module (all of the 2026-07-19 section above) moved to the private repo
**`vamshi455/vrr-agent`** (own DAB bundle `vrr-agent`, same dev workspace + `cdp_dev`
`vrr_raw`/`vrr_curated`/`vrr_agent` schemas, README carries the architecture flow).
Removed from this repo: `src/vrr_agent/`, `agents/vrr_reasoning/`, the VRR notebooks,
job YMLs, `docs/vrr_specs/` + coverage CSV, and the `warehouse_http_path` bundle var.
This repo is back to commercial-data-platform-only concerns. VRR history up to
`ecfebc9` remains in this repo's git log.
