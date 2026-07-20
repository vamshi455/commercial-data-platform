-- ============================================================================
-- VRR value-level lineage graph — project completion_contrib (+ pattern_vrr_*)
-- into vrr_agent.lineage_node / lineage_edge. Pure SQL, warehouse-executable,
-- INSERT OVERWRITE keyed by run_id (same pattern as vrr_build.sql). No graph DB.
--
-- Structure (2-hop DAG, edges point derives-from downstream -> upstream root):
--   vrr:{pattern}:{grain}:{date}  --aggregates_from-->  contrib:{pattern}:{comp}:{date}
--   contrib:...  --input:factor|volume|pressure|pvt-->  {root node}
-- Root node keys are STABLE and shared, so forward reachability from a root finds
-- every VRR it feeds (impact / what-if).
-- ${catalog}, ${run_id} substituted by the runner.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- STATEMENT 1 — nodes (distinct; roots are shared across contribs/VRRs).
-- ---------------------------------------------------------------------------
INSERT OVERWRITE ${catalog}.vrr_agent.lineage_node
WITH c AS (SELECT * FROM ${catalog}.vrr_curated.completion_contrib)
-- VRR output nodes (daily + monthly)
SELECT concat_ws(':','vrr',pattern_id,'daily',cast(vrr_date AS string)) node_id, 'vrr' node_type,
       concat('VRR ',pattern_name,' ',cast(vrr_date AS string),' (daily)') label,
       to_json(struct(vrr, cum_vrr, prod_res_bbl, inj_res_bbl, any_extrapolated)) attrs,
       pattern_id, CAST(NULL AS string) completion_id, vrr_date, '${run_id}' run_id, current_timestamp() built_at
FROM ${catalog}.vrr_curated.pattern_vrr_daily
UNION ALL
SELECT concat_ws(':','vrr',pattern_id,'monthly',cast(vrr_date AS string)), 'vrr',
       concat('VRR ',pattern_name,' ',cast(vrr_date AS string),' (monthly)'),
       to_json(struct(vrr, cum_vrr, prod_res_bbl, inj_res_bbl, any_extrapolated)),
       pattern_id, NULL, vrr_date, '${run_id}', current_timestamp()
FROM ${catalog}.vrr_curated.pattern_vrr_monthly
UNION ALL
-- per-completion contribution nodes (one per completion_contrib row)
SELECT concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)), 'contrib',
       concat(completion_id,' @ ',cast(vrr_date AS string)),
       to_json(struct(oil_res, water_res, free_gas_res, water_inj_res, gas_inj_res,
                      pressure_psi, pvt_method)),
       pattern_id, completion_id, vrr_date, '${run_id}', current_timestamp()
FROM c
UNION ALL
-- root: allocation factor (per completion+pattern)
SELECT DISTINCT concat_ws(':','factor',completion_id,pattern_id), 'factor',
       concat('FACTOR ',completion_id,'/',pattern_id),
       to_json(struct(factor AS factor)), pattern_id, completion_id, CAST(NULL AS date),
       '${run_id}', current_timestamp()
FROM c
UNION ALL
-- root: raw surface volumes (per completion+date)
SELECT DISTINCT concat_ws(':','volume',completion_id,cast(vrr_date AS string)), 'volume',
       concat('VOL ',completion_id,' ',cast(vrr_date AS string)),
       to_json(struct(oil, water, gas, water_inj, gas_inj)), pattern_id, completion_id, vrr_date,
       '${run_id}', current_timestamp()
FROM c
UNION ALL
-- root: pattern pressure (per pattern+date)
SELECT DISTINCT concat_ws(':','pressure',pattern_id,cast(vrr_date AS string)), 'pressure',
       concat('PRESSURE ',pattern_id,' ',cast(vrr_date AS string)),
       to_json(struct(pressure_psi AS pressure_psi)), pattern_id, CAST(NULL AS string), vrr_date,
       '${run_id}', current_timestamp()
FROM c
UNION ALL
-- root: PVT (per completion; interpolated at pressure -> method is confidence)
SELECT DISTINCT concat_ws(':','pvt',completion_id), 'pvt',
       concat('PVT ',completion_id),
       to_json(struct(bo, bw, bg, rs, bw_inj, bg_inj, pvt_method)), CAST(NULL AS string), completion_id,
       CAST(NULL AS date), '${run_id}', current_timestamp()
FROM c;

-- ---------------------------------------------------------------------------
-- STATEMENT 2 — edges.
-- ---------------------------------------------------------------------------
INSERT OVERWRITE ${catalog}.vrr_agent.lineage_edge
WITH c AS (SELECT * FROM ${catalog}.vrr_curated.completion_contrib)
-- vrr(daily) aggregates_from contrib (same day); weight = completion's net reservoir contribution
SELECT concat_ws(':','vrr',pattern_id,'daily',cast(vrr_date AS string)) src_id,
       concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)) dst_id,
       'aggregates_from' rel,
       coalesce(oil_res,0)+coalesce(water_res,0)+coalesce(free_gas_res,0)
         +coalesce(water_inj_res,0)+coalesce(gas_inj_res,0) weight,
       CAST(NULL AS string) confidence, '${run_id}' run_id, current_timestamp() built_at
FROM c
UNION ALL
-- vrr(monthly) aggregates_from contrib (same month)
SELECT concat_ws(':','vrr',pattern_id,'monthly',cast(date_trunc('MM',vrr_date) AS string)),
       concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)),
       'aggregates_from',
       coalesce(oil_res,0)+coalesce(water_res,0)+coalesce(free_gas_res,0)
         +coalesce(water_inj_res,0)+coalesce(gas_inj_res,0),
       NULL, '${run_id}', current_timestamp()
FROM c
UNION ALL
-- contrib -> factor
SELECT concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)),
       concat_ws(':','factor',completion_id,pattern_id), 'input:factor', factor,
       NULL, '${run_id}', current_timestamp() FROM c
UNION ALL
-- contrib -> volume
SELECT concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)),
       concat_ws(':','volume',completion_id,cast(vrr_date AS string)), 'input:volume', CAST(NULL AS double),
       NULL, '${run_id}', current_timestamp() FROM c
UNION ALL
-- contrib -> pressure
SELECT concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)),
       concat_ws(':','pressure',pattern_id,cast(vrr_date AS string)), 'input:pressure', pressure_psi,
       NULL, '${run_id}', current_timestamp() FROM c
UNION ALL
-- contrib -> pvt (confidence = the PVT interpolation method)
SELECT concat_ws(':','contrib',pattern_id,completion_id,cast(vrr_date AS string)),
       concat_ws(':','pvt',completion_id), 'input:pvt', CAST(NULL AS double),
       pvt_method, '${run_id}', current_timestamp() FROM c;
