-- VRR agent — schemas, volumes, and table DDL (Unity Catalog, cdp_dev).
--
-- Design §10 (data model). VRR is a distinct oil & gas domain, isolated in its
-- own schemas inside the shared cdp_dev catalog so it never mixes with the
-- commercial bronze/silver/gold and is trivially droppable.
--
--   raw     -> source-shaped, ACTUAL pipeline names (drop-in for real data)
--   curated -> completion_contrib (lineage layer) + pattern_vrr_daily/_monthly
--   agent   -> audit_log (tools read curated; the agent only writes audit)
--
-- Run with: databricks --profile cdp-dev sql ... OR as a notebook/SQL task.
-- Parameterized on ${catalog} (default cdp_dev) so qa/prod reuse the same file.

-- :param catalog: cdp_dev

CREATE SCHEMA IF NOT EXISTS ${catalog}.vrr_raw
  COMMENT 'VRR raw source-shaped tables (oil & gas volumes, factors, pressure, PVT).';
CREATE SCHEMA IF NOT EXISTS ${catalog}.vrr_curated
  COMMENT 'VRR lineage layer (completion_contrib) + VRR aggregates.';
CREATE SCHEMA IF NOT EXISTS ${catalog}.vrr_agent
  COMMENT 'VRR reasoning agent — audit log; tools are UC functions over vrr_curated.';

-- ---------------------------------------------------------------------------
-- raw — exact names/columns of the upstream pipeline (so real data is drop-in).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_raw.pattern (
  ID_PATTERN   STRING,
  PATTERN_NAME STRING
) USING DELTA
  COMMENT 'Injection/production patterns (a pattern = a group of completions).';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_raw.production_volumes_daily_oilfield (
  EMSDB_PROD_COMPLETION_ID STRING,
  PROD_DATE                DATE,
  ALLOC_OIL_VOL_STB        DOUBLE,
  ALLOC_WATER_VOL_STB      DOUBLE,
  ALLOC_WATER_INJ_VOL_STB  DOUBLE,
  ALLOC_GAS_VOL_KSCF       DOUBLE,
  ALLOC_GAS_INJ_VOL_KSCF   DOUBLE
) USING DELTA
  COMMENT 'Daily allocated surface volumes per completion (oilfield units).';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_raw.pattern_contribution_factor (
  ID_COMPLETION STRING,
  ID_PATTERN    STRING,
  FACTOR        DOUBLE,
  EFFECT_DATE   DATE
) USING DELTA
  COMMENT 'Allocation factor of a completion to a pattern, effective-dated (as-of window).';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_raw.pattern_pressure (
  ID_PATTERN STRING,
  DATE       DATE,
  PRESSURE   DOUBLE
) USING DELTA
  COMMENT 'Pattern average reservoir pressure (psi), effective-dated (as-of window).';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_raw.completion_pvt_characteristics (
  ID_COMPLETION                       STRING,
  TEST_DATE                           DATE,
  PRESSURE                            DOUBLE,
  OIL_FORMATION_VOLUME_FACTOR         DOUBLE,  -- Bo
  WATER_FORMATION_VOLUME_FACTOR       DOUBLE,  -- Bw
  GAS_FORMATION_VOLUME_FACTOR         DOUBLE,  -- Bg
  INJECTED_WATER_FORMATION_VOLUME_FACTOR DOUBLE, -- Bw_inj
  INJECTED_GAS_FORMATION_VOLUME_FACTOR   DOUBLE, -- Bg_inj
  SOLUTION_GAS_OIL_RATIO              DOUBLE,  -- Rs
  VOLATIZED_OIL_GAS_RATIO             DOUBLE   -- Rv
) USING DELTA
  COMMENT 'PVT lab points per completion; interpolated at pattern pressure (method = confidence).';

-- ---------------------------------------------------------------------------
-- curated — the lineage layer + the VRR aggregates (derived from raw).
-- ---------------------------------------------------------------------------
-- One row per (pattern, completion, date) with EVERY input + result. This is
-- what makes lineage real — every VRR traces straight back to these rows.
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_curated.completion_contrib (
  pattern_id    STRING,
  completion_id STRING,
  vrr_date      DATE,
  factor        DOUBLE,                                   -- <- pattern_contribution_factor
  oil DOUBLE, water DOUBLE, gas DOUBLE,                   -- <- raw producer volumes
  water_inj DOUBLE, gas_inj DOUBLE,                       -- <- raw injection volumes
  pressure_psi  DOUBLE,                                   -- <- pattern_pressure
  bo DOUBLE, bw DOUBLE, bg DOUBLE, bw_inj DOUBLE, bg_inj DOUBLE,
  rs DOUBLE, rv DOUBLE,
  pvt_method    STRING,                                   -- exact|interpolated|extrapolated (confidence)
  pvt_bracket_lo DOUBLE, pvt_bracket_hi DOUBLE,           -- pressures bracketing the interp
  missing_input STRING,                                   -- null=ok, else which root input was absent
  oil_res DOUBLE, water_res DOUBLE, free_gas_res DOUBLE,  -- per-term reservoir contributions
  water_inj_res DOUBLE, gas_inj_res DOUBLE,
  run_id        STRING,                                   -- provenance: which build produced this row
  built_at      TIMESTAMP
) USING DELTA
  COMMENT 'Lineage layer: per (pattern, completion, date) every input + result, with PVT confidence + run_id.';

-- VRR = aggregate of the lineage layer (so every VRR traces back to completion_contrib).
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_curated.pattern_vrr_daily (
  pattern_id STRING, pattern_name STRING, vrr_date DATE,
  prod_res_bbl DOUBLE, inj_res_bbl DOUBLE, vrr DOUBLE,
  cum_prod_res_bbl DOUBLE, cum_inj_res_bbl DOUBLE, cum_vrr DOUBLE,
  n_completions INT, any_extrapolated BOOLEAN,            -- roll-up confidence flag
  run_id STRING, built_at TIMESTAMP
) USING DELTA
  COMMENT 'Instantaneous + cumulative VRR per (pattern, date), aggregated from completion_contrib.';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_curated.pattern_vrr_monthly (
  pattern_id STRING, pattern_name STRING, vrr_date DATE,   -- month-start date
  prod_res_bbl DOUBLE, inj_res_bbl DOUBLE, vrr DOUBLE,
  cum_prod_res_bbl DOUBLE, cum_inj_res_bbl DOUBLE, cum_vrr DOUBLE,
  n_completions INT, any_extrapolated BOOLEAN,
  run_id STRING, built_at TIMESTAMP
) USING DELTA
  COMMENT 'Monthly VRR per pattern (month-start dates), aggregated from completion_contrib.';

-- "High vs what?" — per-pattern target VRR (default 1.0 applied in the tool if absent).
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_curated.pattern_target (
  pattern_id STRING, target_vrr DOUBLE, source STRING
) USING DELTA
  COMMENT 'Optional per-pattern target VRR from Reservoir Management; tool defaults to 1.0.';

-- ---------------------------------------------------------------------------
-- agent — audit + the persisted VALUE-LEVEL lineage graph.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.audit_log (
  ts TIMESTAMP, run_id STRING, tool STRING, args STRING,
  pattern_id STRING, vrr_date DATE, ok BOOLEAN, note STRING
) USING DELTA
  COMMENT 'Provenance/audit of every deterministic tool call made by the VRR agent.';

-- Value-level lineage graph (design "lineage IS trust"): the persisted form of what
-- VRR_LINEAGE computes on the fly. Delta node/edge tables in UC — NOT a graph DB
-- (see docs/knowledge-graph.html: "two tables, not a graph database; a recursive CTE
-- handles reachability fine"). Enables impact/what-if traversal + cross-run history.
-- Node keys are STABLE (many VRRs share the same raw-input nodes) so forward
-- reachability from a raw input finds every VRR it feeds.
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.lineage_node (
  node_id     STRING,     -- stable key, e.g. 'pressure:PUNITY:2026-04-01'
  node_type   STRING,     -- vrr | contrib | factor | volume | pressure | pvt
  label       STRING,     -- human-readable
  attrs       STRING,     -- JSON of node attributes (vrr/target/verdict, *_res, method, value)
  pattern_id  STRING, completion_id STRING, vrr_date DATE,
  run_id      STRING, built_at TIMESTAMP
) USING DELTA
  COMMENT 'Nodes of the VRR value-lineage graph: VRR outputs, per-completion contributions, and raw-input roots.';

-- Transformation log — Databricks port of the Snowflake PATTERN_VRR_LOG (vrr_logger.sql).
-- Stores the ACTUAL build SQL used for an asset+grain per run, so the agent can retrieve
-- the real transformation and explain "how is VRR calculated" from source (not memory).
-- run_id + log_ts make it point-in-time; the agent reads the LATEST row per (asset, grain).
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.pattern_vrr_log (
  log_ts           TIMESTAMP,
  log_date         DATE,
  run_id           STRING,
  step             STRING,             -- e.g. SQL_GENERATED | BUILD_OK | ERROR
  row_count        BIGINT,
  error_text       STRING,
  load_type        STRING,             -- full | incremental
  history_months   INT,
  aggregation_type STRING,             -- Daily | Monthly (mirrors Snowflake)
  uom              STRING,             -- OilField | Metric
  asset_name       STRING,             -- the reservoir/asset (a pattern belongs to one)
  params_json      STRING,
  sql_text         STRING              -- the FULL transformation SQL that ran
) USING DELTA
  COMMENT 'Per-run log of the actual VRR build SQL per asset+grain (port of Snowflake PATTERN_VRR_LOG); the agent retrieves the latest to explain how VRR is calculated.';

CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.lineage_edge (
  src_id      STRING,     -- derives-from direction: vrr -> contrib -> root
  dst_id      STRING,
  rel         STRING,     -- aggregates_from | input:factor|volume|pressure|pvt
  weight      DOUBLE,     -- e.g. a completion's contribution share to the VRR
  confidence  STRING,     -- pvt_method on the contrib->pvt edge (exact|interpolated|extrapolated)
  run_id      STRING, built_at TIMESTAMP
) USING DELTA
  COMMENT 'Edges of the VRR value-lineage graph; traverse with recursive CTE (vrr_impact / vrr_trace).';

-- ---------------------------------------------------------------------------
-- Agent MEMORY (design §5.4) — episodic + entity tiers, and safety limits.
-- The recommendation engine reads these to calibrate + bound proposed valve
-- changes, and the learning loop writes outcomes back. NOT written by the
-- serving endpoint (read-mostly); the anomaly/approval jobs do the writes.
-- ---------------------------------------------------------------------------
-- EPISODIC memory: one row per proposed/executed adjustment + its outcome.
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.adjustment_history (
  action_id        STRING,
  pattern_id       STRING, pattern_name STRING, vrr_date DATE,
  driver           STRING,                 -- dominant VRR_DECOMPOSE driver at the time
  anomaly          STRING,                 -- e.g. 'over-replicating VRR 1.31 vs 1.0'
  change_type      STRING,                 -- reduce_injection | increase_injection
  d_inj_res_bbl    DOUBLE,                 -- recommended reservoir-bbl injection change
  d_surface_pct    DOUBLE,                 -- surface injection %% change applied
  pre_vrr          DOUBLE,
  predicted_post_vrr DOUBLE,               -- what the engine predicted
  actual_post_vrr  DOUBLE,                 -- what happened (fills the learning signal)
  decision         STRING,                 -- approved | edited | rejected
  approved_by      STRING, outcome STRING, -- executed | skipped | failed
  ts               TIMESTAMP
) USING DELTA
  COMMENT 'Episodic memory: past VRR anomalies -> recommended change -> decision -> outcome. Feeds precedent retrieval and the per-pattern response-factor learning.';

-- ENTITY memory: one rolling row per pattern (state + LEARNED response factor).
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.pattern_memory (
  pattern_id       STRING,
  pattern_name     STRING,
  latest_vrr       DOUBLE, latest_date DATE,
  typical_low      DOUBLE, typical_high DOUBLE,   -- observed normal band
  response_factor  DOUBLE,                        -- rho = EMA(actual dVRR / predicted dVRR); default 1.0
  n_adjustments    INT,
  tendencies       STRING,                        -- free-text/JSON notes (e.g. 'over-responds to injection cuts')
  updated_at       TIMESTAMP
) USING DELTA
  COMMENT 'Entity memory: per-pattern rolling state + LEARNED response factor rho used to calibrate recommendation magnitude.';

-- Safety limits that BOUND any recommended change (RM/Site approval gates).
CREATE TABLE IF NOT EXISTS ${catalog}.vrr_agent.safety_limits (
  pattern_id       STRING, completion_id STRING,
  max_inj_rate_change_pct DOUBLE,   -- e.g. 0.15 = at most 15%% change per action
  max_inj_pressure DOUBLE,          -- psi
  fracture_gradient DOUBLE,         -- psi (hard ceiling)
  note             STRING
) USING DELTA
  COMMENT 'Per-pattern/completion safety limits; the recommendation engine clamps proposals to these and escalates if exceeded.';
