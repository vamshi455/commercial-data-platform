# Observability — Lineage, Freshness, Data Quality, SLA & Run-Health

> **Program:** Commercial Data Platform (CDP)
> **Workspace:** `https://adb-1234567890123456.7.azuredatabricks.net` (Azure Databricks)
> **Goal:** a single **control plane** that answers, at any moment: *Is the data
> fresh? Is it correct? Did the pipelines run? What breaks if I change X?*
>
> Observability is built almost entirely on **Unity Catalog system tables** and
> the **DLT/Lakeflow event log**, surfaced through **Databricks SQL** dashboards.
> Reusable queries live in `notebooks/observability/` and `notebooks/lineage/`.

---

## 1. The control plane — five pillars

```
                         ┌─────────────────────────────────────────────┐
                         │            CDP OBSERVABILITY PLANE           │
                         └─────────────────────────────────────────────┘
   ┌───────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  ┌───────────────┐
   │ LINEAGE   │  │ FRESHNESS  │  │ DATA QUAL. │  │   SLA    │  │  RUN-HEALTH   │
   │ what feeds│  │ last load  │  │ expectation│  │ on-time? │  │ jobs/pipelines│
   │ /consumes │  │  vs SLA    │  │ pass/fail  │  │  alerts  │  │ success/fail  │
   └─────┬─────┘  └─────┬──────┘  └─────┬──────┘  └────┬─────┘  └──────┬────────┘
         │              │               │              │               │
   system.access  information_schema  system.event_log  job-run    system.lakeflow.*
   .table/column   + history()        / DLT event log   sys tables  system.workflow.*
   _lineage                                                          .job_run_timeline
         └──────────────┴───────────────┴──────────────┴───────────────┘
                                   │
                        Databricks SQL dashboards + Alerts (Section 9-10)
```

| Pillar | Question answered | Primary source |
|--------|-------------------|----------------|
| Lineage | What feeds/consumes this object? What breaks if I change it? | `system.access.table_lineage`, `column_lineage` |
| Freshness | When did each table last load? Is it within SLA? | `<catalog>.information_schema.tables`, `DESCRIBE HISTORY` |
| Data Quality | Which expectations passed/failed, by pipeline & rule? | DLT/`system.event_log` (event type `flow_progress`) |
| SLA | Did the right data land on time? | freshness × declared SLA in `ops.sla_config` |
| Run-health | Did jobs/pipelines run, fail, or run long? | `system.lakeflow.*` / `system.workflow.job_run_timeline` |

All derived metrics are persisted into the **`ops`** schema (e.g.
`ops.freshness_snapshot`, `ops.dq_results`, `ops.run_health`) so dashboards read
cheap pre-aggregated tables rather than re-scanning system tables every refresh.

---

## 2. Lineage — table & column

Unity Catalog captures lineage **automatically** for every governed read/write.
Two ways to consume it:

1. **Catalog Explorer** → a table's **Lineage** tab → interactive upstream/
   downstream graph (tables *and* columns), plus the notebooks/jobs/pipelines
   that produced each edge. Best for ad-hoc exploration.
2. **System tables** → programmatic queries for dashboards and impact analysis.

| Table | Grain |
|-------|-------|
| `system.access.table_lineage` | one row per source-table → target-table lineage event |
| `system.access.column_lineage` | one row per source-column → target-column edge |

**Full downstream footprint of `silver.customer`:**

```sql
SELECT DISTINCT
       target_table_catalog AS catalog,
       target_table_schema  AS schema,
       target_table_name    AS table_name,
       entity_type          AS produced_by   -- NOTEBOOK / PIPELINE / JOB
FROM   system.access.table_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer'
  AND  target_table_name IS NOT NULL
ORDER  BY 1, 2, 3;
```

> `notebooks/lineage/` contains reusable notebooks that wrap these queries:
> `impact_analysis.py` (given a table/column, list everything downstream),
> `lineage_graph_export.py` (materialize the edge list into `ops.lineage_edges`
> for dashboarding), and `agent_provenance_check.sql` (prove agent views have no
> raw-PII upstream — see [governance.md](./governance.md) §10).

---

## 3. Impact analysis — "what breaks if I change `silver.customer`?"

Run **before** any breaking change (rename/drop column, retype, deprecate table).

**Step 1 — downstream tables (blast radius):**

```sql
SELECT DISTINCT target_table_schema AS schema, target_table_name AS table_name
FROM   system.access.table_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer';
```

**Step 2 — column-level: who consumes `silver.customer.email`?** (the column you
intend to rename):

```sql
SELECT DISTINCT
       target_table_schema || '.' || target_table_name AS downstream_table,
       target_column_name
FROM   system.access.column_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer'
  AND  source_column_name   = 'email'
ORDER  BY 1, 2;
```

**Step 3 — which jobs/notebooks must be re-tested** (the producers of those
downstream tables):

```sql
SELECT DISTINCT target_table_name, entity_type, entity_run_id
FROM   system.access.table_lineage
WHERE  source_table_catalog = 'cdp_prod'
  AND  source_table_schema  = 'silver'
  AND  source_table_name    = 'customer'
  AND  target_table_name IS NOT NULL;
```

Output of Step 1 for `silver.customer` typically includes: `gold.customer_360`,
`gold.account_health`, `gold.renewal_risk`, and their `v_*_agent` views — those
are exactly the products a stewards review must sign off before the change ships.

---

## 4. Freshness — design & SQL

**Definition:** freshness = `now() − last successful write` for a table, compared
to its declared **SLA** (`ops.sla_config`).

```
 domain    table                   last_load           sla_minutes  status
 ───────── ─────────────────────── ─────────────────── ──────────── ───────
 sales     gold.revenue_pipeline   2026-06-26 05:58    120          ✅ OK
 finance   gold.bookings_vs_bill.  2026-06-26 04:10    120          ⚠ WARN
 finance   gold.collections_risk   2026-06-25 23:40    240          ❌ BREACH
 cs        gold.support_perform.   2026-06-26 06:01     60          ✅ OK
```

### 4a. SLA config table (`ops`)

```sql
CREATE TABLE IF NOT EXISTS cdp_prod.ops.sla_config (
  domain        STRING,
  table_name    STRING,   -- fully qualified
  sla_minutes   INT,      -- max acceptable staleness
  owner_group   STRING
);
```

### 4b. Last-load via `information_schema` + history

The cheapest broad signal is the table commit time; the precise signal is
`DESCRIBE HISTORY`. A scalable approach reads from `information_schema.tables`
(`last_altered`) for all tables, then refines hot tables with history:

```sql
-- Broad pass: last_altered for every gold table (from information_schema).
SELECT table_schema, table_name, last_altered AS last_load_ts
FROM   cdp_prod.information_schema.tables
WHERE  table_schema = 'gold'
ORDER  BY last_load_ts;
```

```sql
-- Precise pass for one table: timestamp of the last WRITE/MERGE commit.
SELECT max(timestamp) AS last_load_ts
FROM   (DESCRIBE HISTORY cdp_prod.gold.collections_risk)
WHERE  operation IN ('WRITE','MERGE','STREAMING UPDATE','CREATE TABLE AS SELECT');
```

### 4c. Freshness vs SLA (dashboard query)

```sql
WITH last_load AS (
  SELECT 'gold.' || table_name AS table_name,
         table_schema, table_name AS tbl, last_altered AS last_load_ts
  FROM   cdp_prod.information_schema.tables
  WHERE  table_schema = 'gold'
)
SELECT s.domain,
       s.table_name,
       l.last_load_ts,
       s.sla_minutes,
       round(timestampdiff(SECOND, l.last_load_ts, current_timestamp())/60.0, 1)
         AS staleness_min,
       CASE
         WHEN timestampdiff(MINUTE, l.last_load_ts, current_timestamp()) > s.sla_minutes
              THEN 'BREACH'
         WHEN timestampdiff(MINUTE, l.last_load_ts, current_timestamp()) > s.sla_minutes*0.8
              THEN 'WARN'
         ELSE 'OK'
       END AS status
FROM   cdp_prod.ops.sla_config s
JOIN   last_load l ON l.table_name = s.table_name
ORDER  BY staleness_min DESC;
```

> Persist this into `cdp_prod.ops.freshness_snapshot` on a schedule (a notebook in
> `notebooks/observability/freshness_snapshot.py`) so the dashboard and the SLA
> alert (Section 10) read a small table.

---

## 5. Data Quality — design & SQL

DQ in CDP is enforced with **DLT/Lakeflow expectations** (`EXPECT`,
`EXPECT ... ON VIOLATION DROP/FAIL`). Every expectation evaluation is emitted to
the **pipeline event log**, also exposed as `system.event_log`. We read the
`flow_progress` events, which carry per-expectation pass/fail counts in
`details:flow_progress.data_quality.expectations`.

```
 pipeline           dataset        rule                 passed  failed  pass_rate
 ────────────────── ────────────── ──────────────────── ─────── ─────── ─────────
 cdp_medallion_prod silver.customer valid_email          120341    12    99.99%
 cdp_medallion_prod silver.customer non_null_account_id  120353     0   100.00%
 cdp_medallion_prod silver.invoice  amount_non_negative   88210   140    99.84% ⚠
```

### 5a. Expectation definition (in the DLT pipeline)

```python
@dlt.table(name="customer")
@dlt.expect("valid_email", "email RLIKE '^[^@]+@[^@]+\\.[^@]+$'")
@dlt.expect_or_drop("non_null_account_id", "account_id IS NOT NULL")
def customer():
    return dlt.read_stream("bronze.customer_raw").transform(conform_customer)
```

### 5b. DQ pass/fail from the event log

If the pipeline publishes its event log to a UC table (recommended) or via
`system.event_log`:

```sql
-- Per-rule pass/fail for the latest update of a pipeline.
SELECT
  e.origin.pipeline_name                                    AS pipeline,
  e.origin.flow_name                                        AS dataset,
  exp.name                                                  AS rule,
  exp.passed_records                                        AS passed,
  exp.failed_records                                        AS failed,
  round(100.0 * exp.passed_records
        / nullif(exp.passed_records + exp.failed_records,0), 2) AS pass_rate_pct
FROM cdp_prod.ops.pipeline_event_log e
LATERAL VIEW explode(
  from_json(e.details:flow_progress.data_quality.expectations,
            'array<struct<name:string,passed_records:bigint,failed_records:bigint>>')
) AS exp
WHERE e.event_type = 'flow_progress'
  AND e.details:flow_progress.data_quality IS NOT NULL
  AND e.timestamp >= current_timestamp() - INTERVAL 1 DAY
ORDER BY failed DESC;
```

> Materialize into `cdp_prod.ops.dq_results` (notebook
> `notebooks/observability/dq_results.py`) so the DQ dashboard trends pass-rate by
> rule over time and alerts when any rule drops below threshold.

---

## 6. Pipeline event-log review process

Every DLT/Lakeflow pipeline writes a structured **event log**. Querying it is the
canonical way to diagnose a run.

```sql
-- The event log for a pipeline (point the table at the pipeline's event log).
-- event_type values of interest:
--   update_progress  → overall update lifecycle (RUNNING/COMPLETED/FAILED)
--   flow_progress    → per-dataset progress + data_quality
--   flow_definition  → schema/expectations definition
-- Latest update outcome:
SELECT timestamp,
       event_type,
       details:update_progress.state    AS update_state,
       message
FROM   cdp_prod.ops.pipeline_event_log
WHERE  event_type = 'update_progress'
ORDER  BY timestamp DESC
LIMIT  20;
```

```sql
-- Errors / warnings only, most recent first.
SELECT timestamp, level, error.message AS error_message, details
FROM   cdp_prod.ops.pipeline_event_log
WHERE  level IN ('ERROR','WARN')
  AND  timestamp >= current_timestamp() - INTERVAL 1 DAY
ORDER  BY timestamp DESC;
```

**Review process (runbook):**

1. Alert fires (run failure or DQ breach).
2. Open the event log; filter `event_type='update_progress'` for the failing
   update → get `update_id` and failure `message`.
3. Filter `flow_progress` for that update → find which dataset/expectation failed.
4. Inspect `level='ERROR'` rows for the stack/cause.
5. Cross-check **lineage** (Section 3) for downstream blast radius.
6. Remediate; re-run via `databricks bundle run <pipeline> -t prod`.
7. Log the incident in `ops.incident_log`.

---

## 7. Run-status monitoring & SLA alerts

Job and pipeline run history is in UC system tables — no custom logging needed.

| System table | Contents |
|--------------|----------|
| `system.workflow.job_run_timeline` | one row per job run: start/end, result_state, run duration |
| `system.workflow.job_task_run_timeline` | per-task within each run |
| `system.lakeflow.*` | Lakeflow pipeline run metadata |

**Recent failed / long-running job runs:**

```sql
SELECT job_id,
       run_id,
       period_start_time                                  AS started,
       period_end_time                                    AS ended,
       result_state,                                       -- SUCCESS / FAILED / TIMEDOUT
       round(timestampdiff(SECOND, period_start_time,
                           period_end_time)/60.0, 1)       AS duration_min
FROM   system.workflow.job_run_timeline
WHERE  period_start_time >= current_timestamp() - INTERVAL 1 DAY
  AND  result_state IN ('FAILED','TIMEDOUT','CANCELED')
ORDER  BY started DESC;
```

**Runs that exceeded their runtime SLA (e.g. > 45 min):**

```sql
SELECT job_id, run_id, result_state,
       timestampdiff(MINUTE, period_start_time, period_end_time) AS duration_min
FROM   system.workflow.job_run_timeline
WHERE  period_start_time >= current_date() - INTERVAL 7 DAYS
  AND  timestampdiff(MINUTE, period_start_time, period_end_time) > 45
ORDER  BY duration_min DESC;
```

### Alerts

- **Job-level:** bundle jobs declare failure notifications to
  `var.notifications_email` (and/or Slack/PagerDuty webhook). Configured in
  `resources/*.yml` `email_notifications.on_failure`.
- **SLA / freshness / DQ:** Databricks SQL **Alerts** run a saved query on a
  schedule and notify when a threshold trips — e.g. *"any row in
  `ops.freshness_snapshot` with `status='BREACH'`"* or *"any rule in
  `ops.dq_results` with `pass_rate_pct < 99`"*.

```sql
-- Alert query: fire if anything is breaching freshness right now.
SELECT count(*) AS breaches
FROM   cdp_prod.ops.freshness_snapshot
WHERE  status = 'BREACH';
-- Alert condition: breaches > 0  → notify cdp_platform_engineers + owner_group.
```

---

## 8. Audit & cost context (supporting signals)

Observability also pulls from:

- `system.access.audit` — who read/changed governed data (security observability;
  see [governance.md](./governance.md) §11).
- `system.billing.usage` — DBU spend by job/pipeline/env tag (cost observability;
  see [environments.md](./environments.md) §9).

These round out the "is the platform healthy" picture beyond pure data freshness.

---

## 9. Ops dashboards to build in Databricks SQL

Build these as Databricks SQL dashboards reading from the pre-aggregated `ops`
tables (refreshed by `notebooks/observability/*`):

| # | Dashboard | What it shows | Primary source |
|---|-----------|---------------|----------------|
| 1 | **Freshness & SLA** | Per domain/table: last load, staleness, SLA status (OK/WARN/BREACH); count of breaches | `ops.freshness_snapshot` ← `information_schema` + `DESCRIBE HISTORY` |
| 2 | **Data Quality** | Expectation pass/fail by pipeline & rule; pass-rate trend; top failing rules | `ops.dq_results` ← `system.event_log` `flow_progress` |
| 3 | **Run-Health** | Job/pipeline run outcomes (success/fail/timeout), durations vs runtime SLA, failure timeline | `system.workflow.job_run_timeline`, `system.lakeflow.*` |
| 4 | **Lineage / Impact** | Blast radius per critical table; agent-view provenance; orphan/unconsumed tables | `system.access.table_lineage` / `column_lineage` → `ops.lineage_edges` |
| 5 | **Pipeline Event Review** | Latest update states, errors/warnings, per-dataset progress | `ops.pipeline_event_log` |
| 6 | **Cost & Compute** | DBU spend by env / job / data_product; idle clusters; serverless usage | `system.billing.usage`, `system.compute.*` |
| 7 | **Security / Audit** | Access to `pii`/`financial_sensitive`; grant changes; unusual access | `system.access.audit` |
| 8 | **Platform Health Summary** | One-screen executive roll-up: % tables fresh, overall DQ pass-rate, run success-rate, open incidents | all `ops.*` snapshots |

Each operational dashboard should default to `cdp_prod` but accept a **catalog
parameter** so the same dashboard inspects `cdp_qa` during UAT.

---

## 10. Notebook folders

| Folder | Contents |
|--------|----------|
| `notebooks/observability/` | `freshness_snapshot.py`, `dq_results.py`, `run_health.py`, `event_log_review.sql`, `cost_rollup.sql`, `build_ops_snapshots.py` (orchestrates the daily snapshot refresh into `ops.*`) |
| `notebooks/lineage/` | `impact_analysis.py` (Section 3), `lineage_graph_export.py` (→ `ops.lineage_edges`), `agent_provenance_check.sql` (governance §10), `orphan_tables.sql` (tables with no downstream consumers) |

These notebooks are deployed and scheduled per environment by the bundle (a daily
`job_observability_snapshot` in `resources/*.yml`, paused in dev/qa, live in
prod), so every environment refreshes its own `ops.*` snapshot tables that the
Databricks SQL dashboards then read.

---

## 11. Daily observability loop

```
   00:30  ingest + medallion pipelines run (prod schedules)
     │
   05:00  job_observability_snapshot runs notebooks/observability/*
     │       ├─ freshness_snapshot   → ops.freshness_snapshot
     │       ├─ dq_results           → ops.dq_results
     │       ├─ run_health           → ops.run_health
     │       └─ lineage_graph_export → ops.lineage_edges
     │
   05:15  SQL Alerts evaluate ops.* snapshots
     │       ├─ freshness BREACH  → notify platform eng + owner_group
     │       └─ DQ pass_rate < 99 → notify data eng + stewards
     │
   morning  teams open Databricks SQL dashboards (Section 9)
```

This closes the loop: pipelines produce data → system tables + event log capture
truth → snapshot notebooks summarize into `ops` → dashboards + alerts make it
visible and actionable.
