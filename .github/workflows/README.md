# CI/CD — GitHub Actions for the Commercial Data Platform

This folder holds the automation that validates and promotes the Databricks
Asset Bundle (DAB) defined in the repo-root `databricks.yml` across the
`dev -> qa -> prod` targets.

## Workflows

| File | Trigger | What it does | Deploys? |
|------|---------|--------------|----------|
| `ci.yml` | `pull_request` (to develop / release/** / main) | Python syntax check, `pytest tests/`, `databricks bundle validate -t dev` | No |
| `deploy-qa.yml` | push to `develop` or `release/**` | `validate` + `deploy -t qa` | Yes (QA) |
| `deploy-prod.yml` | push of tag `v*` or push to `main` | `validate` + `deploy -t prod` behind an approval gate | Yes (PROD) |

## Branch strategy

```
feature/*  ──PR──►  develop  ──►  release/x.y  ──►  main  ──tag v*──►  prod
   (CI)            (deploy QA)   (deploy QA)     (deploy PROD, gated)
```

- **feature/**: short-lived branches. Open a PR into `develop`; `ci.yml` runs.
- **develop**: integration branch. Every merge deploys to **QA** automatically.
- **release/x.y**: stabilization branches; also deploy to **QA** for UAT.
- **main**: production-ready. Merging to `main` (or pushing a `v*` tag) triggers
  the gated **PROD** deploy.

## Authentication — OAuth M2M service principal

All workflows authenticate with a Databricks **service principal** using OAuth
machine-to-machine (M2M). The Databricks CLI auto-detects these env vars, which
the workflows wire from secrets:

- `DATABRICKS_HOST` — `https://dbc-0d3c2f0f-de7b.cloud.databricks.com`
- `DATABRICKS_CLIENT_ID` — the service principal's OAuth client (application) id
- `DATABRICKS_CLIENT_SECRET` — an OAuth secret for that service principal

No PATs and no secrets are committed to the repo.

### Create a service principal + OAuth secret

1. Account console -> **User management -> Service principals -> Add**.
   Create one per environment, e.g. `sp-cdp-qa` and `sp-cdp-prod`.
2. Grant each SP the workspace + Unity Catalog privileges it needs
   (`CAN_MANAGE` on the bundle target's workspace path, catalog `USE`/`CREATE`,
   schema privileges). QA SP -> `cdp_qa`; PROD SP -> `cdp_prod`.
3. Generate an **OAuth secret** for the SP:
   ```bash
   databricks account service-principal-secrets create <SP_APPLICATION_ID>
   ```
   Record the returned `secret` (shown once) and the SP's client/application id.
4. (Optional) set the SP as the bundle `run_as` (see `databricks.yml`).

## Secrets & GitHub Environments

| Scope | Secrets | Used by |
|-------|---------|---------|
| Repo (Settings -> Secrets -> Actions) | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` (dev/validate SP) | `ci.yml` |
| Environment **qa** | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` (QA SP) | `deploy-qa.yml` |
| Environment **prod** | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` (PROD SP) | `deploy-prod.yml` |

Environment-scoped secrets override repo secrets when a job declares
`environment: <name>`, so the QA/PROD jobs automatically use the right SP.

### Create the GitHub Environments

`Settings -> Environments -> New environment`:

- **qa** — add the three QA secrets. (Optional: restrict to `develop`/`release/*`.)
- **prod** — add the three PROD secrets **and** the approval gate below.

## The PROD approval gate (manual approval)

`deploy-prod.yml` sets `environment: prod`. When a run reaches that job it
**pauses in a "Waiting" state** until a configured reviewer approves.

Configure under `Settings -> Environments -> prod`:

- **Required reviewers** — add the people/teams allowed to approve prod deploys.
- **Deployment branches and tags** — restrict to `main` and `v*` tags.
- (Optional) **Wait timer** — enforce a cool-down before deploy proceeds.

Until approval, PROD secrets are not exposed and no `deploy -t prod` runs. This
gives you a human checkpoint and an audit trail for every production release.

## Local equivalents

Everything CI does, you can run locally:

```bash
databricks bundle validate -t dev
pytest -q tests/
databricks bundle deploy -t qa     # or use scripts/deploy.sh
```
