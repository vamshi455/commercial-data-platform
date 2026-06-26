# Environments — dev / qa / prod

> **Program:** Commercial Data Platform (CDP)
> **Workspace:** `https://dbc-0d3c2f0f-de7b.cloud.databricks.com` (AWS Databricks)
> **Deployment:** Databricks Asset Bundles (DAB), one bundle, three targets.
>
> This document explains the three-environment model, how a single codebase is
> promoted across `cdp_dev → cdp_qa → cdp_prod`, and how the bundle in
> `databricks.yml` wires each environment to its own catalog, workspace path,
> schedule, compute, and identity.

---

## 1. The core idea: same code, three catalogs

CDP follows the **catalog-per-environment** + **schema-per-layer** pattern. The
*same* parameterized code is deployed to all three environments; only the
**catalog** (and the schedule / compute / identity / permissions) change. Because
the medallion layer lives in the **schema** name, the only thing that differs
between environments is the **catalog** prefix.

```
        ┌────────────────────────────────────────────────────────────┐
        │                    ONE bundle, ONE codebase                  │
        │  notebooks/  resources/*.yml  governance/*.sql  src/  tests/ │
        └───────────────┬───────────────┬───────────────┬─────────────┘
                        │               │               │
          databricks bundle deploy -t {dev|qa|prod}     │
                        │               │               │
          ┌─────────────▼──┐   ┌────────▼───────┐   ┌───▼─────────────┐
          │   target: dev   │   │   target: qa   │   │   target: prod  │
          │ mode:development │   │ mode:production│   │ mode:production │
          ├─────────────────┤   ├────────────────┤   ├─────────────────┤
          │ catalog cdp_dev  │   │ catalog cdp_qa │   │ catalog cdp_prod│
          │ schedules PAUSED │   │ schedules PAUSE│   │ schedules LIVE  │
          │ run_as: each user│   │ run_as: SP     │   │ run_as: SP      │
          └─────────────────┘   └────────────────┘   └─────────────────┘
```

---

## 2. Purpose, access, and operating mode of each environment

| Aspect | **dev** (`cdp_dev`) | **qa** (`cdp_qa`) | **prod** (`cdp_prod`) |
|--------|---------------------|-------------------|------------------------|
| **Purpose** | Developer iteration; build pipelines, notebooks, governance; experiment | Integration tests, UAT, validation against representative data | Live, governed, scheduled production data products |
| **Bundle mode** | `development` | `production` | `production` |
| **Schedules** | Paused (manual trigger) | Paused / on-demand for test runs | Live cron schedules |
| **Run-as identity** | Each developer (their own user) | Deploy **service principal** | Deploy **service principal** |
| **Resource naming** | Prefixed `[dev <user>]`, per-user isolation | Canonical names | Canonical names |
| **Who deploys** | Any engineer (from laptop / IDE) | CI on merge to `main` / release branch | CI on tagged release / approval gate |
| **Who can read data** | Engineers (broad) | Engineers + QA + steward reviewers | Personas per [governance.md](./governance.md) RBAC |
| **Compute** | Small / serverless, autoscale-min | Right-sized for representative volumes | Production-sized, SLA-backed |
| **Data** | Synthetic, frequently regenerated | Synthetic at representative scale | Loaded via Lakeflow Connect / production feeds |
| **`sandbox` schema** | **Present** | Absent | Absent |
| **Cost posture** | Minimize; ephemeral clusters, auto-terminate | Moderate | Optimized for reliability + SLA |

---

## 3. Catalog-per-env and schema-per-layer

```
 cdp_dev ─┐                cdp_qa ─┐                cdp_prod ─┐
          ├─ landing                ├─ landing                ├─ landing
          ├─ bronze                 ├─ bronze                 ├─ bronze
          ├─ silver                 ├─ silver                 ├─ silver
          ├─ gold                   ├─ gold                   ├─ gold
          ├─ ops                    ├─ ops                    ├─ ops
          └─ sandbox  ◄── dev only  └─ (no sandbox)           └─ (no sandbox)
```

| Catalog | Environment | Schemas |
|---------|-------------|---------|
| `cdp_dev` | Development | `landing`, `bronze`, `silver`, `gold`, `ops`, **`sandbox`** |
| `cdp_qa` | QA / UAT | `landing`, `bronze`, `silver`, `gold`, `ops` |
| `cdp_prod` | Production | `landing`, `bronze`, `silver`, `gold`, `ops` |

- **Catalog = environment boundary.** UC permissions, masks, and row filters are
  applied per catalog, so dev access never bleeds into prod.
- **Schema = medallion layer.** Same layer names everywhere → identical code
  paths; only `${var.catalog}` differs.
- **`sandbox` is dev-only** for free-form experimentation; it is never created in
  qa/prod (see `governance/catalogs_schemas.sql`, which gates the sandbox `CREATE`
  on the target).

---

## 4. How the Asset Bundle maps env → catalog → workspace path

The root `databricks.yml` defines one bundle with three targets. Each target sets
its own `workspace.host`/`root_path` and overrides the shared variables
`catalog` and `landing_volume`.

```
target → mode → workspace.root_path → var.catalog → var.landing_volume
─────────────────────────────────────────────────────────────────────────
 dev   → development → /Workspace/Users/<you>/.bundle/cdp/dev → cdp_dev
                                                   → /Volumes/cdp_dev/landing/files
 qa    → production  → /Workspace/.bundle/cdp/qa            → cdp_qa
                                                   → /Volumes/cdp_qa/landing/files
 prod  → production  → /Workspace/.bundle/cdp/prod          → cdp_prod
                                                   → /Volumes/cdp_prod/landing/files
```

Relevant excerpts from the existing `databricks.yml`:

```yaml
variables:
  catalog:        { default: cdp_dev }
  landing_volume: { default: /Volumes/cdp_dev/landing/files }

targets:
  dev:
    mode: development            # [dev <user>] prefixes, paused schedules, per-user isolation
    default: true
    workspace:
      host: https://dbc-0d3c2f0f-de7b.cloud.databricks.com
      root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/dev
    variables:
      catalog: cdp_dev
      landing_volume: /Volumes/cdp_dev/landing/files
      pipeline_channel: PREVIEW   # try newer DLT runtime in dev first

  qa:
    mode: production
    workspace:
      host: https://dbc-0d3c2f0f-de7b.cloud.databricks.com
      root_path: /Workspace/.bundle/${bundle.name}/qa
    variables:
      catalog: cdp_qa
      landing_volume: /Volumes/cdp_qa/landing/files
    run_as:
      service_principal_name: ${var.deploy_service_principal}

  prod:
    mode: production
    workspace:
      host: https://dbc-0d3c2f0f-de7b.cloud.databricks.com
      root_path: /Workspace/.bundle/${bundle.name}/prod
    variables:
      catalog: cdp_prod
      landing_volume: /Volumes/cdp_prod/landing/files
    run_as:
      service_principal_name: ${var.deploy_service_principal}
    permissions:
      - level: CAN_MANAGE
        group_name: cdp_platform_engineers
      - level: CAN_VIEW
        group_name: cdp_data_stewards
```

How resources consume the variables — every job/pipeline in `resources/*.yml`
references `${var.catalog}` and `${var.landing_volume}` so it auto-targets the
right environment:

```yaml
# resources/pipeline_medallion.yml (illustrative)
resources:
  pipelines:
    medallion:
      name: cdp_medallion_${bundle.target}
      catalog: ${var.catalog}          # cdp_dev | cdp_qa | cdp_prod
      target: silver
      channel: ${var.pipeline_channel}
      configuration:
        landing_volume: ${var.landing_volume}
```

Deploy / run:

```bash
databricks bundle validate -t qa
databricks bundle deploy   -t dev          # default target is dev
databricks bundle deploy   -t prod         # CI, as service principal
databricks bundle run job_orchestration_daily -t dev
```

---

## 5. `mode: development` vs `mode: production`

This is the single most important behavioral switch in the bundle.

| Behavior | `mode: development` (dev) | `mode: production` (qa, prod) |
|----------|---------------------------|--------------------------------|
| Resource names | Prefixed `[dev <user>]` → **per-user isolation** (no collisions) | Canonical, shared names |
| Schedules / triggers | **Paused** automatically | As declared (prod = live cron) |
| Concurrent runs | Limited to 1 (fast feedback) | As configured |
| `run_as` | The deploying **user** | The declared **service principal** |
| Deployment root | Under `/Workspace/Users/<you>/…` | Under shared `/Workspace/.bundle/…` |
| Validation strictness | Relaxed | Strict (e.g. warns if `run_as`/SP missing) |
| Intent | Safe, isolated iteration | Reproducible, identity-stable execution |

**Per-user isolation in dev:** because dev resources are prefixed with the
developer's name and deployed under their own workspace folder, two engineers can
each `databricks bundle deploy -t dev` without overwriting each other's jobs or
pipelines. Each gets their own `[dev jane] cdp_medallion` pipeline writing to the
shared `cdp_dev` catalog (typically into per-user or sandbox schemas).

**Service-principal execution in qa/prod:** production runs execute as a
**deploy service principal**, not a human. This means:

- Jobs keep running when an employee leaves (no orphaned ownership).
- Audit logs (`system.access.audit`) attribute production writes to a stable
  identity.
- The SP — not individuals — is what holds write grants on `cdp_qa`/`cdp_prod`
  bronze/silver/gold, so no human can write prod data interactively.

---

## 6. Promotion flow: dev → qa → prod (promote code, not data)

The golden rule: **we promote *code*, never *data*.** Data is regenerated or
loaded **independently per environment**. Promoting data would copy dev's
synthetic noise (or worse, leak prod data downward).

```
   ┌──────────┐   git PR + review   ┌──────────┐   tagged release   ┌──────────┐
   │   dev    │ ──────────────────► │    qa    │ ─────────────────► │   prod   │
   └────┬─────┘   (merge to main)   └────┬─────┘   (approval gate)  └────┬─────┘
        │                                │                               │
        │ CODE promoted ───────────────────────────────────────────────►│
        │  • notebooks/  • resources/*.yml  • governance/*.sql  • src/   │
        │                                                                │
        │ DATA regenerated/loaded PER ENV (never copied between envs):   │
        │  cdp_dev: synthetic via data_gen/  ──┐                         │
        │  cdp_qa : synthetic @ representative │  independent runs       │
        │  cdp_prod: Lakeflow Connect feeds  ──┘                         │
```

| What | Promoted across envs? | How it lands in each env |
|------|-----------------------|--------------------------|
| Notebooks, pipeline/job definitions, SQL, Python `src/` | **Yes** (via git + `bundle deploy`) | Same artifacts, parameterized by `${var.catalog}` |
| Governance SQL (grants, masks, filters, tags) | **Yes** | Re-run against the target catalog |
| **Data** | **No** | dev/qa: synthetic generation; prod: Lakeflow Connect / source feeds |
| Schedules / compute / identity / permissions | Config differs per target | From the target block in `databricks.yml` |

**Typical lifecycle:**

1. Engineer develops on a feature branch, `bundle deploy -t dev`, iterates against
   `cdp_dev` with synthetic data and the `sandbox` schema.
2. PR → review (CI runs `tests/`, `bundle validate -t qa`). Merge to `main`.
3. CI deploys to `cdp_qa` as the service principal; integration/UAT runs against
   representative synthetic data; stewards verify governance.
4. On a tagged release (with approval), CI `bundle deploy -t prod`. Prod schedules
   go live; data loads from real source feeds.

---

## 7. Isolation, secrets, service principals, permissions per env

### Isolation

- **Catalog isolation:** `cdp_dev`/`cdp_qa`/`cdp_prod` are separate UC catalogs
  with independent grants; a dev grant cannot expose prod data.
- **Workspace-path isolation:** dev artifacts live under the user's folder; qa/prod
  under shared bundle roots.
- **Identity isolation:** dev = user; qa/prod = service principal.

### Secrets

- Stored in **Databricks secret scopes** (or backed by AWS Secrets Manager), one
  scope per environment (e.g. `cdp_dev`, `cdp_qa`, `cdp_prod`).
- Referenced as `${secrets/<scope>/<key>}` or `dbutils.secrets.get(...)`; never
  hard-coded. The deploy service-principal name and source credentials are
  resolved from CI secrets, **not** committed in `databricks.yml`.

### Service principals

- A **deploy service principal** runs qa and prod (`run_as` in those targets).
- The SP is the holder of write grants on qa/prod bronze/silver/gold, so no human
  writes production data interactively.

### Group-based permissions per env

Set on the bundle target (`permissions:` block) and on UC securables via
`governance/grants.sql`:

| Env | `CAN_MANAGE` | `CAN_VIEW` / data read |
|-----|--------------|------------------------|
| dev | deploying user | engineers (broad) |
| qa  | platform engineers (CI/SP) | `cdp_analysts`, steward reviewers |
| prod | `cdp_platform_engineers` | `cdp_data_stewards` + personas per RBAC matrix |

---

## 8. Sandbox schema (dev only)

`cdp_dev.sandbox` is a free-for-all scratch space for engineers:

- Prototype transformations, ad-hoc joins, throwaway tables.
- **Never referenced by promoted pipeline code** — promoted resources write to
  `bronze/silver/gold` only, so nothing depends on sandbox.
- Created **only** when the bundle target is `dev` (gated in
  `governance/catalogs_schemas.sql`); qa and prod have no sandbox.
- Periodically purged; not backed up; no SLA.

> If a sandbox prototype proves valuable, it is rewritten as a proper DLT/Lakeflow
> resource targeting `silver`/`gold`, reviewed, and promoted through the normal
> dev → qa → prod flow.

---

## 9. Cost & compute guidance per environment

| Env | Compute pattern | Guidance |
|-----|-----------------|----------|
| **dev** | Serverless / small autoscaling clusters; aggressive auto-terminate | Minimize spend: smallest workable node, low autoscale max, short idle timeout. Use serverless SQL warehouse (small) for queries. Synthetic data kept small. Schedules paused so no idle scheduled burn. |
| **qa** | Right-sized to representative volumes; on-demand | Match prod shape at reduced scale so tests are realistic but cheap. Spin up for test runs, tear down after. |
| **prod** | Production-sized, SLA-backed; reserved/optimized | Right-size for actual volume + freshness SLAs. Prefer serverless DLT/jobs where it lowers idle cost; enable photon; set autoscaling to meet SLA without over-provisioning. Tag compute for chargeback. |

**Cost visibility** comes from `system.billing.usage` joined to bundle/job tags;
the freshness/cost dashboards live in `ops` (see [observability.md](./observability.md)).
Tag all compute with `env`, `bundle`, and `data_product` so spend can be split by
environment and by gold product.

```sql
-- Spend by environment over the last 30 days (chargeback).
SELECT usage_metadata.cluster_id,
       custom_tags['env']          AS env,
       SUM(usage_quantity)         AS dbus
FROM   system.billing.usage
WHERE  usage_date >= current_date() - INTERVAL 30 DAYS
  AND  custom_tags['bundle'] = 'commercial-data-platform'
GROUP  BY 1, 2
ORDER  BY dbus DESC;
```

---

## 10. Quick reference

```bash
# Validate before deploy
databricks bundle validate -t qa

# Deploy (dev is default target)
databricks bundle deploy -t dev
databricks bundle deploy -t qa     # CI, service principal
databricks bundle deploy -t prod   # CI, approval-gated, service principal

# Run a job in a given env
databricks bundle run job_orchestration_daily -t prod

# Tear down a dev deployment (cleans the per-user prefixed resources)
databricks bundle destroy -t dev
```

| Question | Answer |
|----------|--------|
| Where does env live? | In the **catalog** (`cdp_*`), set by `var.catalog` per target |
| Where does the layer live? | In the **schema** (`landing/bronze/silver/gold/ops/sandbox`) |
| What's promoted? | **Code + governance**, never data |
| Who runs prod? | The deploy **service principal** |
| Are dev schedules live? | No — `mode: development` pauses them |
| Where's sandbox? | `cdp_dev` only |
