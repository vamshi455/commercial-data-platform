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

## Authentication — Workload Identity Federation (WIF, secret-less)

Databricks **recommends Workload Identity Federation** for CI/CD authentication.
WIF eliminates the need for Databricks secrets, which makes it the most secure way
to authenticate automated flows to Databricks. See
[Enable workload identity federation in CI/CD](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-federation).

All workflows authenticate as a Databricks **service principal** by exchanging the
**GitHub-issued OIDC token** for a short-lived Databricks token — there is **no
`DATABRICKS_CLIENT_SECRET`** anywhere. Each job declares `permissions: id-token:
write` (to mint the OIDC token) and wires these **non-secret** env vars:

- `DATABRICKS_HOST` — `https://adb-7405618019865738.18.azuredatabricks.net` (GitHub **variable**)
- `DATABRICKS_CLIENT_ID` — the service principal's application id (GitHub **variable**)
- `DATABRICKS_AUTH_TYPE: github-oidc` — pins the CLI to the OIDC flow

No PATs, no secrets, nothing sensitive is committed to the repo.

### Create a service principal + federation policy (no secret)

1. Account console -> **User management -> Service principals -> Add**.
   Create one per environment, e.g. `sp-cdp-qa` and `sp-cdp-prod`.
2. Grant each SP the workspace + Unity Catalog privileges it needs
   (`CAN_MANAGE` on the bundle target's workspace path, catalog `USE`/`CREATE`,
   schema privileges). QA SP -> `cdp_qa`; PROD SP -> `cdp_prod`.
3. Add a **federation policy** that trusts this repo's GitHub OIDC tokens — instead
   of generating an OAuth secret:
   ```bash
   databricks account service-principal-federation-policies create \
     --service-principal-id <SP_NUMERIC_ID> --json '{
       "oidc_policy": {
         "issuer":   "https://token.actions.githubusercontent.com",
         "audiences": ["https://github.com/<ORG>"],
         "subject":  "repo:<ORG>/<REPO>:environment:prod"
       }
     }'
   ```
   Use `:environment:qa` for the QA SP and a PR-appropriate subject for CI.
4. (Optional) set the SP as the bundle `run_as` (see `databricks.yml`).

## Variables & GitHub Environments

WIF needs only **variables** (`Settings -> Secrets and variables -> Actions ->
Variables`), never secrets:

| Scope | Variables | Used by |
|-------|-----------|---------|
| Repo | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID` (CI/validate SP) | `ci.yml` |
| Environment **qa** | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DEPLOY_SERVICE_PRINCIPAL` (QA SP) | `deploy-qa.yml` |
| Environment **prod** | `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, `DEPLOY_SERVICE_PRINCIPAL` (PROD SP) | `deploy-prod.yml` |

Environment-scoped variables override repo variables when a job declares
`environment: <name>`, so the QA/PROD jobs automatically use the right SP.

### Create the GitHub Environments

`Settings -> Environments -> New environment`:

- **qa** — add the QA variables. (Optional: restrict to `develop`/`release/*`.)
- **prod** — add the PROD variables **and** the approval gate below.

## The PROD approval gate (manual approval)

`deploy-prod.yml` sets `environment: prod`. When a run reaches that job it
**pauses in a "Waiting" state** until a configured reviewer approves.

Configure under `Settings -> Environments -> prod`:

- **Required reviewers** — add the people/teams allowed to approve prod deploys.
- **Deployment branches and tags** — restrict to `main` and `v*` tags.
- (Optional) **Wait timer** — enforce a cool-down before deploy proceeds.

Until approval, the prod environment's variables are not exposed, the job can't
mint a prod-scoped OIDC token, and no `deploy -t prod` runs. This gives you a human
checkpoint and an audit trail for every production release.

## Local equivalents

Everything CI does, you can run locally:

```bash
databricks bundle validate -t dev
pytest -q tests/
databricks bundle deploy -t qa     # or use scripts/deploy.sh
```
