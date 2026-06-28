# CI/CD — Commercial Data Platform

This document explains how the Commercial Data Platform is built, validated, and promoted
through **dev → qa → prod** using **Databricks Asset Bundles (DABs)** and **GitHub Actions**,
with **Workload Identity Federation (WIF / GitHub OIDC, secret-less)** auth and approval gates.

> **One bundle, three targets.** The *same* code deploys to every environment; only config
> (catalog, schedules, permissions, compute, channel) changes per target. Root config:
> `databricks.yml`; resources: `resources/*.yml`; pipeline code: `src/pipelines/`.

---

## 1. Databricks Asset Bundles (DABs)

A **bundle** is the unit of deployment: it packages resources (jobs, pipelines, etc.) +
source code + per-environment config, described as YAML and managed by the `databricks
bundle` CLI.

| Concept | What it is | In this repo |
|---|---|---|
| **bundle** | Top-level package (`bundle.name`) | `commercial-data-platform` |
| **targets** | Named environments with overrides | `dev`, `qa`, `prod` |
| **resources** | Deployable objects (jobs, pipelines) | `resources/*.yml` (included via `include:`) |
| **variables** | Parameterize config per target | `catalog`, `landing_volume`, `notifications_email`, `pipeline_channel`, `deploy_service_principal` |
| **mode** | `development` or `production` deploy semantics | dev=`development`, qa/prod=`production` |

### 1.1 `mode: development` vs `mode: production`

| | `development` (dev) | `production` (qa, prod) |
|---|---|---|
| Resource naming | Prefixed `[dev <user>] ...` (isolated per user) | Exact, shared names |
| Schedules / triggers | **Paused** | Active (real schedules) |
| `run_as` | Deploying user | **Service principal** |
| Concurrent edits / overwrite | Permissive | Locked, validated, single source of truth |
| Intended use | Fast iteration | Reproducible, governed releases |

### 1.2 Target → catalog mapping (from `databricks.yml`)

| Target | Catalog | landing_volume | channel | run_as |
|---|---|---|---|---|
| `dev` | `cdp_dev` | `/Volumes/cdp_dev/landing/files` | `PREVIEW` | current user |
| `qa` | `cdp_qa` | `/Volumes/cdp_qa/landing/files` | `CURRENT` | `${var.deploy_service_principal}` |
| `prod` | `cdp_prod` | `/Volumes/cdp_prod/landing/files` | `CURRENT` | `${var.deploy_service_principal}` |

---

## 2. Branch strategy

```
 feature/*  ──PR──►  develop  ──PR──►  release/qa  ──PR/tag──►  main
   (local)          (auto→DEV)        (auto→QA)               (approval→PROD)
      │                 │                  │                       │
   ci.yml           ci.yml +          deploy-qa.yml          deploy-prod.yml
 (validate+test)   deploy-qa.yml     (UAT/integration)      (gated, tagged release)
```

| Branch | Maps to | Deploy trigger | Gate |
|---|---|---|---|
| `feature/*` | nothing (validate only) | PR opened/updated → `ci.yml` | PR review + CI green |
| `develop` | **dev** | merge to `develop` → `deploy-qa.yml` (dev job) | CI green |
| `release/qa` | **qa** | merge to `release/qa` → `deploy-qa.yml` | CI green + UAT |
| `main` (+ `vX.Y.Z` tag) | **prod** | tag push / merge to `main` → `deploy-prod.yml` | **Manual approval** (GitHub Environment) |

All merges require a **pull request with ≥1 review** and passing required checks.

---

## 3. Promotion commands

The CLI verbs used everywhere (CI and locally):

```bash
# Validate config + resolve variables for a target (no side effects)
databricks bundle validate -t dev
databricks bundle validate -t qa
databricks bundle validate -t prod

# Deploy resources + sync source for a target
databricks bundle deploy -t dev
databricks bundle deploy -t qa
databricks bundle deploy -t prod

# Trigger a run (job or pipeline) after deploy
databricks bundle run job_orchestration_daily -t dev
databricks bundle run job_orchestration_daily -t qa
databricks bundle run job_orchestration_daily -t prod

# Tear down (mostly dev)
databricks bundle destroy -t dev
```

---

## 4. Workload Identity Federation (WIF) auth for CI

CI never uses a human user — and, as of this platform, **never stores a Databricks
secret**. Databricks recommends **Workload Identity Federation (WIF)** for CI/CD
authentication. WIF eliminates the need for Databricks secrets, which makes it the
most secure way to authenticate automated flows to Databricks. See
[Enable workload identity federation in CI/CD](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-federation).

CI authenticates as a **Unity Catalog service principal** by exchanging the
**GitHub-issued OIDC token** for a short-lived Databricks token — no client secret
ever exists.

```
GitHub Actions job  (permissions: id-token: write)
   │  mints a GitHub OIDC token (issuer https://token.actions.githubusercontent.com)
   │  env: DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DATABRICKS_AUTH_TYPE=github-oidc
   ▼
databricks CLI  ──OIDC token──►  Databricks OIDC token endpoint
   │                               (federation policy validates issuer + subject,
   │                                issues a short-lived Databricks token)
   ▼
Workspace + Unity Catalog (deploy/run as the service principal)
```

- **No secret to leak or rotate.** `DATABRICKS_HOST` (workspace URL) and
  `DATABRICKS_CLIENT_ID` (the SP application id) are **non-secret identifiers**,
  stored as GitHub **variables** (`vars.*`), not secrets. There is no
  `DATABRICKS_CLIENT_SECRET` anywhere.
- `permissions: id-token: write` on the job is what lets it request the GitHub OIDC
  token; `DATABRICKS_AUTH_TYPE: github-oidc` pins the CLI to this flow so a
  misconfiguration fails loudly instead of silently falling back.
- The service principal must have: workspace access, `CAN_MANAGE` on the bundle root
  path, and UC privileges (`USE CATALOG`, `CREATE SCHEMA/TABLE`, pipeline create) on
  the target catalog. In `databricks.yml`, qa/prod set `run_as.service_principal_name:
  ${var.deploy_service_principal}`.

### 4.1 One-time setup — federation policy + GitHub variables

**On Databricks (per service principal, account-level):** create a federation policy
that trusts this repo's GitHub OIDC tokens. The `subject` claim scopes trust to a
specific repo + environment so only the right workflow can assume the SP:

```bash
# Trust the prod SP only from this repo's `prod` environment.
databricks account service-principal-federation-policies create \
  --service-principal-id <PROD_SP_NUMERIC_ID> --json '{
    "oidc_policy": {
      "issuer":   "https://token.actions.githubusercontent.com",
      "audiences": ["https://github.com/<ORG>"],
      "subject":  "repo:<ORG>/<REPO>:environment:prod"
    }
  }'
```

Repeat for the QA SP with `subject: "repo:<ORG>/<REPO>:environment:qa"`, and for the
CI/dev SP with a PR-appropriate subject (e.g. `repo:<ORG>/<REPO>:pull_request`).

**On GitHub:** store the non-secret identifiers as **variables** (not secrets).

| GitHub **variable** | Scope | Purpose |
|---|---|---|
| `DATABRICKS_HOST` | repo or environment | Workspace URL `https://adb-7405618019865738.18.azuredatabricks.net` |
| `DATABRICKS_CLIENT_ID` | **environment** (`qa`, `prod`) | SP application (client) id |
| `DEPLOY_SERVICE_PRINCIPAL` | environment | SP application id for the `run_as` bundle var |

Scope `DATABRICKS_CLIENT_ID` / `DEPLOY_SERVICE_PRINCIPAL` to **GitHub Environments**
(`qa`, `prod`) so the **prod** environment can require **manual approval** and restrict
which branches/tags deploy. No `Settings → Secrets` entries are needed at all.

---

## 5. GitHub Actions workflows

Files: `.github/workflows/ci.yml`, `.github/workflows/deploy-qa.yml`,
`.github/workflows/deploy-prod.yml`.

### 5.1 `ci.yml` — validate + test on PR

```yaml
name: ci
on:
  pull_request:
    branches: [develop, release/qa, main]
jobs:
  validate-and-test:
    runs-on: ubuntu-latest
    permissions:
      id-token: write           # mint GitHub OIDC token for WIF
      contents: read
    env:
      DATABRICKS_HOST: ${{ vars.DATABRICKS_HOST }}
      DATABRICKS_CLIENT_ID: ${{ vars.DATABRICKS_CLIENT_ID }}
      DATABRICKS_AUTH_TYPE: github-oidc
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - name: Bundle validate (all targets)
        run: |
          databricks bundle validate -t dev
          databricks bundle validate -t qa
          databricks bundle validate -t prod
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Unit tests
        run: |
          pip install -r requirements-dev.txt
          pytest tests/unit -q
      - name: Data-quality tests
        run: pytest tests/dq -q
```

### 5.2 `deploy-qa.yml` — on merge to develop/release

```yaml
name: deploy-qa
on:
  push:
    branches: [develop, release/qa]
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ github.ref_name == 'develop' && 'dev' || 'qa' }}
    permissions:
      id-token: write           # mint GitHub OIDC token for WIF
      contents: read
    env:
      DATABRICKS_HOST: ${{ vars.DATABRICKS_HOST }}
      DATABRICKS_CLIENT_ID: ${{ vars.DATABRICKS_CLIENT_ID }}
      DATABRICKS_AUTH_TYPE: github-oidc
      BUNDLE_VAR_deploy_service_principal: ${{ vars.DEPLOY_SERVICE_PRINCIPAL }}
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - run: databricks bundle validate -t ${{ github.ref_name == 'develop' && 'dev' || 'qa' }}
      - run: databricks bundle deploy   -t ${{ github.ref_name == 'develop' && 'dev' || 'qa' }}
      - name: Smoke run
        run: databricks bundle run job_orchestration_daily -t ${{ github.ref_name == 'develop' && 'dev' || 'qa' }} --no-wait
```

### 5.3 `deploy-prod.yml` — on tag/main with approval gate

```yaml
name: deploy-prod
on:
  push:
    tags: ["v*.*.*"]            # release tags only
jobs:
  deploy-prod:
    runs-on: ubuntu-latest
    environment: prod           # <-- required reviewers (approval gate) configured here
    permissions:
      id-token: write           # mint GitHub OIDC token for WIF
      contents: read
    env:
      DATABRICKS_HOST: ${{ vars.DATABRICKS_HOST }}
      DATABRICKS_CLIENT_ID: ${{ vars.DATABRICKS_CLIENT_ID }}
      DATABRICKS_AUTH_TYPE: github-oidc
      BUNDLE_VAR_deploy_service_principal: ${{ vars.DEPLOY_SERVICE_PRINCIPAL }}
    steps:
      - uses: actions/checkout@v4
      - uses: databricks/setup-cli@main
      - run: databricks bundle validate -t prod
      - run: databricks bundle deploy   -t prod
      # Schedules in prod are active; do NOT force a run unless intended.
```

### 5.4 Jobs / triggers summary

| Workflow | Trigger | Target(s) | Key jobs | Gate |
|---|---|---|---|---|
| `ci.yml` | PR to develop/release/main | validate only | validate ×3, unit tests, DQ tests | required checks |
| `deploy-qa.yml` | push to develop / release/qa | dev / qa | validate, deploy, smoke run | CI green |
| `deploy-prod.yml` | push tag `v*.*.*` | prod | validate, deploy | **Environment approval** |

---

## 6. Quality gates

A change cannot reach the next environment until **all** pass:

| Gate | Command | Blocks |
|---|---|---|
| Bundle validate | `databricks bundle validate -t <env>` | malformed resources / bad var refs |
| Unit tests | `pytest tests/unit` | transform logic regressions |
| Data-quality tests | `pytest tests/dq` | DQ rule / expectation regressions |
| PR review | GitHub branch protection | unreviewed code |
| Prod approval | GitHub Environment reviewers | un-approved prod deploy |

---

## 7. Versioning, tagging & rollback

- **Versioning:** semantic tags `vMAJOR.MINOR.PATCH`. Tag on `main` triggers prod deploy.
  Tag message records the change set; release notes link the PRs.
- **Immutable artifact:** the deployed bundle for a tag is reproducible — re-running
  `databricks bundle deploy -t prod` from the same tag yields the same state.

### Rollback

| Scenario | Action |
|---|---|
| Bad prod deploy | `git checkout v<previous>` → `databricks bundle deploy -t prod` (redeploy last good tag) |
| Bad data in a table | Delta **time travel** / `RESTORE TABLE ... TO VERSION AS OF n` |
| Bad pipeline logic | redeploy prior tag, then targeted `--full-refresh-select <table>` to rebuild |
| Emergency | pause schedules (`mode: production` jobs) via Workflows UI/CLI, then roll back |

---

## 8. Runbook A — first deployment

```
1.  Install CLI:            (Databricks CLI v0.2xx+; `databricks -v`)
2.  Create the SP in the account console; grant UC + workspace privileges.
       Then add a WIF *federation policy* on the SP trusting this repo's GitHub
       OIDC subject (issuer token.actions.githubusercontent.com) — see §4.1.
       NO OAuth secret is created.
3.  Add GitHub repo/env *variables* (not secrets):
       DATABRICKS_HOST, DATABRICKS_CLIENT_ID, DEPLOY_SERVICE_PRINCIPAL
       (qa & prod in GitHub Environments; configure required reviewers on `prod`).
4.  Local auth (one-time):  databricks auth login --host https://adb-7405618019865738.18.azuredatabricks.net
5.  Validate:               databricks bundle validate -t dev
6.  Deploy dev:             databricks bundle deploy   -t dev
7.  Seed landing data:      run data_gen / scripts to land files in /Volumes/cdp_dev/landing/files
8.  Run pipeline:           databricks bundle run job_orchestration_daily -t dev
9.  Verify:                 check bronze→silver→gold tables + ops.dq_results in cdp_dev
10. Open PR feature → develop; let ci.yml + deploy-qa.yml promote to dev/qa.
```

## 9. Runbook B — promote a change to prod

```
1.  Branch:        git checkout -b feature/<change> ; commit ; push
2.  PR → develop:  ci.yml runs (validate + unit + DQ). Get review. Merge.
                   → deploy-qa.yml deploys to DEV automatically.
3.  PR develop → release/qa ; merge → deploys to QA. Run UAT / integration.
4.  PR release/qa → main ; merge.
5.  Tag release:   git tag v1.4.0 && git push origin v1.4.0
6.  Approve:       deploy-prod.yml pauses on the `prod` Environment → required reviewer approves.
7.  Deploy runs:   bundle validate -t prod ; bundle deploy -t prod.
8.  Verify:        prod pipeline run, DQ results, lineage, dashboards.
9.  Rollback if needed:  redeploy previous tag (Runbook §7).
```

---

## 10. File map

| Concern | Location |
|---|---|
| Bundle root | `databricks.yml` |
| Resources (jobs/pipelines) | `resources/*.yml` |
| CI workflow | `.github/workflows/ci.yml` |
| QA deploy workflow | `.github/workflows/deploy-qa.yml` |
| Prod deploy workflow | `.github/workflows/deploy-prod.yml` |
| Tests | `tests/unit`, `tests/dq` |
| Helper scripts | `scripts/` |
