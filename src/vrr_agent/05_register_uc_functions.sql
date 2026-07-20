-- VRR — Unity Catalog functions over vrr_curated (design §4, handoff #3).
--
-- VRR_GET and the lineage read are simple, set-returning reads -> registered as UC
-- SQL table functions so they are governable (EXECUTE grant), lineage-tracked, and
-- callable from Genie / SQL / an agent tool. VRR_DECOMPOSE stays a Python agent tool
-- (tools.py): its exact log-mean attribution over a variable driver set is not a
-- scalar/SQL-shaped computation, and re-expressing it in SQL would duplicate the
-- verified physics. The agent calls the Python tool directly; the numbers still
-- trace to the same curated rows these functions expose.
--
-- :param catalog: cdp_dev

-- VRR_GET(pattern, date) — stored monthly VRR + cum + target (default 1.0) + refs.
CREATE OR REPLACE FUNCTION ${catalog}.vrr_agent.vrr_get(
  in_pattern STRING, in_date DATE)
RETURNS TABLE (
  pattern_id STRING, vrr_date DATE, vrr DOUBLE, cum_vrr DOUBLE,
  prod_res_bbl DOUBLE, inj_res_bbl DOUBLE, target_vrr DOUBLE,
  target_is_default BOOLEAN, any_extrapolated BOOLEAN, run_id STRING)
COMMENT 'Stored monthly VRR for a pattern/date + target (per-pattern or default 1.0).'
RETURN
  SELECT v.pattern_id, v.vrr_date, v.vrr, v.cum_vrr, v.prod_res_bbl, v.inj_res_bbl,
         COALESCE(t.target_vrr, 1.0) AS target_vrr,
         (t.target_vrr IS NULL)      AS target_is_default,
         v.any_extrapolated, v.run_id
  FROM ${catalog}.vrr_curated.pattern_vrr_monthly v
  LEFT JOIN ${catalog}.vrr_curated.pattern_target t USING (pattern_id)
  WHERE v.pattern_id = in_pattern AND v.vrr_date = in_date;

-- VRR_LINEAGE(pattern, month_start) — the per-completion lineage rows behind a VRR,
-- with PVT method as the confidence flag. Root sources are named in the columns'
-- provenance (see completion_contrib COMMENTs).
CREATE OR REPLACE FUNCTION ${catalog}.vrr_agent.vrr_lineage(
  in_pattern STRING, in_month DATE)
RETURNS TABLE (
  completion_id STRING, factor DOUBLE, pressure_psi DOUBLE,
  oil DOUBLE, water DOUBLE, gas DOUBLE, water_inj DOUBLE, gas_inj DOUBLE,
  bg DOUBLE, rs DOUBLE, pvt_method STRING, confidence STRING,
  free_gas_res DOUBLE, oil_res DOUBLE, water_res DOUBLE,
  water_inj_res DOUBLE, gas_inj_res DOUBLE, run_id STRING)
COMMENT 'Root-trace rows for a pattern month: every input + result per completion, with PVT confidence.'
RETURN
  SELECT completion_id, AVG(factor), AVG(pressure_psi),
         SUM(oil), SUM(water), SUM(gas), SUM(water_inj), SUM(gas_inj),
         AVG(bg), AVG(rs),
         MAX(pvt_method) AS pvt_method,
         CASE WHEN MAX(CASE WHEN pvt_method='extrapolated' THEN 1 ELSE 0 END)=1
              THEN 'low' ELSE 'ok' END AS confidence,
         SUM(free_gas_res), SUM(oil_res), SUM(water_res),
         SUM(water_inj_res), SUM(gas_inj_res), MIN(run_id)
  FROM ${catalog}.vrr_curated.completion_contrib
  WHERE pattern_id = in_pattern AND date_trunc('MM', vrr_date) = date_trunc('MM', in_month)
  GROUP BY completion_id;

-- Least-privilege: the agent/app service principal only needs to read curated + run
-- these. (Adjust the principal to your cdp_ai_app_users / a dedicated vrr SP.)
-- GRANT USAGE ON SCHEMA ${catalog}.vrr_curated TO `cdp_ai_app_users`;
-- GRANT SELECT ON SCHEMA ${catalog}.vrr_curated TO `cdp_ai_app_users`;
-- GRANT EXECUTE ON FUNCTION ${catalog}.vrr_agent.vrr_get TO `cdp_ai_app_users`;
-- GRANT EXECUTE ON FUNCTION ${catalog}.vrr_agent.vrr_lineage TO `cdp_ai_app_users`;
