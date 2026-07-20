-- ============================================================================
-- VRR build — Databricks port of the production Snowflake vrr_sql_builder.sql
-- (CreateVRR/src/vrr_sql_builder.sql @74676ae). Faithful to the 11 CHECKPOINTS.
-- ----------------------------------------------------------------------------
-- Reads cdp_dev.vrr_raw.* and writes the curated lineage layer + VRR:
--   completion_contrib   <- CHECKPOINT 9 (VolumeWithPVT) + reservoir-term formulas
--   pattern_vrr_daily    <- CHECKPOINTS 10-11 with period_bucket = DATE
--   pattern_vrr_monthly  <- CHECKPOINTS 10-11 with period_bucket = DATE_TRUNC('MM', DATE)
--
-- Scope of this port: UOM = OilField (gas_multiplier = 1000, KSCF->SCF),
-- include_volatilization = FALSE (simplified formulas). The volatilization branch
-- and the METRIC/HIB UNION path are documented in the original; add here only if
-- needed. ${catalog} is substituted by the runner (default cdp_dev).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- STATEMENT 1 — completion_contrib (the lineage layer). The full CHECKPOINT 1-9
-- pipeline is inlined as CTEs so this is ONE self-contained statement (the runner
-- executes each statement in its own session — no cross-statement temp views).
-- ---------------------------------------------------------------------------
INSERT OVERWRITE ${catalog}.vrr_curated.completion_contrib
WITH
-- CHECKPOINT 1: factor windows — END_DATE = next EFFECT_DATE for the SAME
-- (COMPLETION, PATTERN); half-open [EFFECT_DATE, END_DATE). A completion keeps
-- contributing to an old pattern until THAT pattern gets a newer factor.
FactorsWithEndDate AS (
  SELECT pcf.ID_COMPLETION, pcf.ID_PATTERN, pcf.FACTOR, pcf.EFFECT_DATE, p.PATTERN_NAME,
         COALESCE(
           (SELECT MIN(pcf2.EFFECT_DATE)
              FROM ${catalog}.vrr_raw.pattern_contribution_factor pcf2
             WHERE pcf2.ID_COMPLETION = pcf.ID_COMPLETION
               AND pcf2.ID_PATTERN    = pcf.ID_PATTERN
               AND pcf2.EFFECT_DATE   > pcf.EFFECT_DATE),
           DATE'9999-12-31') AS END_DATE
    FROM ${catalog}.vrr_raw.pattern_contribution_factor pcf
    JOIN ${catalog}.vrr_raw.pattern p ON pcf.ID_PATTERN = p.ID_PATTERN
),
PressureWithEndDate AS (
  SELECT ID_PATTERN, DATE, PRESSURE,
         COALESCE(LEAD(DATE) OVER (PARTITION BY ID_PATTERN ORDER BY DATE), DATE'9999-12-31') AS END_DATE
    FROM ${catalog}.vrr_raw.pattern_pressure
),
-- CHECKPOINT 2: daily volumes. WATER clamped to >= 0 (legacy IIF(water>0,water,0)).
DailyVolumes AS (
  SELECT EMSDB_PROD_COMPLETION_ID AS COMPLETION_ID, PROD_DATE AS DATE,
         SUM(COALESCE(ALLOC_OIL_VOL_STB, 0))            AS OIL_VOL,
         SUM(GREATEST(COALESCE(ALLOC_WATER_VOL_STB,0),0)) AS WATER_VOL,
         SUM(COALESCE(ALLOC_WATER_INJ_VOL_STB, 0))      AS WATER_INJ_VOL,
         SUM(COALESCE(ALLOC_GAS_VOL_KSCF, 0))           AS GAS_VOL,
         SUM(COALESCE(ALLOC_GAS_INJ_VOL_KSCF, 0))       AS GAS_INJ_VOL
    FROM ${catalog}.vrr_raw.production_volumes_daily_oilfield
   GROUP BY EMSDB_PROD_COMPLETION_ID, PROD_DATE
),
-- CHECKPOINT 3: join volumes -> factor window -> pressure window. Amount_Type
-- from surface production presence (oil+water+gas > 0).
VolumeContext AS (
  SELECT dv.COMPLETION_ID, dv.DATE, f.ID_PATTERN, f.PATTERN_NAME, f.FACTOR, p.PRESSURE,
         dv.OIL_VOL, dv.WATER_VOL, dv.WATER_INJ_VOL, dv.GAS_VOL, dv.GAS_INJ_VOL,
         CASE WHEN (dv.OIL_VOL + dv.WATER_VOL + dv.GAS_VOL) > 0 THEN 'Production' ELSE 'Injection' END AS Amount_Type
    FROM DailyVolumes dv
    JOIN FactorsWithEndDate f
      ON dv.COMPLETION_ID = f.ID_COMPLETION AND dv.DATE >= f.EFFECT_DATE AND dv.DATE < f.END_DATE
    JOIN PressureWithEndDate p
      ON f.ID_PATTERN = p.ID_PATTERN AND dv.DATE >= p.DATE AND dv.DATE < p.END_DATE
),
-- CHECKPOINT 4/5: PVT test-date windows (which lab test applies on DATE).
UniquePVTNeeds AS (SELECT DISTINCT COMPLETION_ID, DATE, PRESSURE FROM VolumeContext),
PVTTestDates AS (
  SELECT ID_COMPLETION, TEST_DATE,
         COALESCE(LEAD(TEST_DATE) OVER (PARTITION BY ID_COMPLETION ORDER BY TEST_DATE), DATE'9999-12-31') AS END_DATE
    FROM (SELECT DISTINCT ID_COMPLETION, TEST_DATE FROM ${catalog}.vrr_raw.completion_pvt_characteristics)
),
PVTWithEndDate AS (
  SELECT pvt.*, td.END_DATE
    FROM ${catalog}.vrr_raw.completion_pvt_characteristics pvt
    JOIN PVTTestDates td ON pvt.ID_COMPLETION = td.ID_COMPLETION AND pvt.TEST_DATE = td.TEST_DATE
),
-- CHECKPOINT 6: classify each PVT point vs target pressure + rank per side.
PVTAnalysis AS (
  SELECT upn.COMPLETION_ID, upn.DATE, upn.PRESSURE AS target_pressure, pvt.PRESSURE AS pvt_pressure,
         pvt.OIL_FORMATION_VOLUME_FACTOR, pvt.GAS_FORMATION_VOLUME_FACTOR, pvt.WATER_FORMATION_VOLUME_FACTOR,
         pvt.SOLUTION_GAS_OIL_RATIO, pvt.VOLATIZED_OIL_GAS_RATIO,
         pvt.INJECTED_GAS_FORMATION_VOLUME_FACTOR, pvt.INJECTED_WATER_FORMATION_VOLUME_FACTOR,
         CASE WHEN pvt.PRESSURE = upn.PRESSURE THEN 'exact'
              WHEN pvt.PRESSURE < upn.PRESSURE THEN 'lower' ELSE 'upper' END AS pressure_type,
         ROW_NUMBER() OVER (
           PARTITION BY upn.COMPLETION_ID, upn.DATE, upn.PRESSURE,
             CASE WHEN pvt.PRESSURE < upn.PRESSURE THEN 'lower'
                  WHEN pvt.PRESSURE > upn.PRESSURE THEN 'upper' ELSE 'exact' END
           ORDER BY CASE WHEN pvt.PRESSURE < upn.PRESSURE THEN -pvt.PRESSURE ELSE pvt.PRESSURE END
         ) AS rank_in_type
    FROM UniquePVTNeeds upn
    JOIN PVTWithEndDate pvt ON upn.COMPLETION_ID = pvt.ID_COMPLETION
     AND upn.DATE >= pvt.TEST_DATE AND upn.DATE < pvt.END_DATE
),
-- CHECKPOINT 7: pivot nearest lower/upper (+ second points for extrapolation).
PVTBounds AS (
  SELECT COMPLETION_ID, DATE, target_pressure,
    MAX(CASE WHEN pressure_type='exact' THEN OIL_FORMATION_VOLUME_FACTOR END) exact_oil_fvf,
    MAX(CASE WHEN pressure_type='exact' THEN GAS_FORMATION_VOLUME_FACTOR END) exact_gas_fvf,
    MAX(CASE WHEN pressure_type='exact' THEN WATER_FORMATION_VOLUME_FACTOR END) exact_water_fvf,
    MAX(CASE WHEN pressure_type='exact' THEN SOLUTION_GAS_OIL_RATIO END) exact_gor,
    MAX(CASE WHEN pressure_type='exact' THEN INJECTED_GAS_FORMATION_VOLUME_FACTOR END) exact_inj_gas_fvf,
    MAX(CASE WHEN pressure_type='exact' THEN INJECTED_WATER_FORMATION_VOLUME_FACTOR END) exact_inj_water_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN pvt_pressure END) lower_pressure,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN OIL_FORMATION_VOLUME_FACTOR END) lower_oil_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN GAS_FORMATION_VOLUME_FACTOR END) lower_gas_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN WATER_FORMATION_VOLUME_FACTOR END) lower_water_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN SOLUTION_GAS_OIL_RATIO END) lower_gor,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN INJECTED_GAS_FORMATION_VOLUME_FACTOR END) lower_inj_gas_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=1 THEN INJECTED_WATER_FORMATION_VOLUME_FACTOR END) lower_inj_water_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN pvt_pressure END) upper_pressure,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN OIL_FORMATION_VOLUME_FACTOR END) upper_oil_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN GAS_FORMATION_VOLUME_FACTOR END) upper_gas_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN WATER_FORMATION_VOLUME_FACTOR END) upper_water_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN SOLUTION_GAS_OIL_RATIO END) upper_gor,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN INJECTED_GAS_FORMATION_VOLUME_FACTOR END) upper_inj_gas_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=1 THEN INJECTED_WATER_FORMATION_VOLUME_FACTOR END) upper_inj_water_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN pvt_pressure END) second_lower_pressure,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN OIL_FORMATION_VOLUME_FACTOR END) second_lower_oil_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN GAS_FORMATION_VOLUME_FACTOR END) second_lower_gas_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN WATER_FORMATION_VOLUME_FACTOR END) second_lower_water_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN SOLUTION_GAS_OIL_RATIO END) second_lower_gor,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN INJECTED_GAS_FORMATION_VOLUME_FACTOR END) second_lower_inj_gas_fvf,
    MAX(CASE WHEN pressure_type='lower' AND rank_in_type=2 THEN INJECTED_WATER_FORMATION_VOLUME_FACTOR END) second_lower_inj_water_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN pvt_pressure END) second_upper_pressure,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN OIL_FORMATION_VOLUME_FACTOR END) second_upper_oil_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN GAS_FORMATION_VOLUME_FACTOR END) second_upper_gas_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN WATER_FORMATION_VOLUME_FACTOR END) second_upper_water_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN SOLUTION_GAS_OIL_RATIO END) second_upper_gor,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN INJECTED_GAS_FORMATION_VOLUME_FACTOR END) second_upper_inj_gas_fvf,
    MAX(CASE WHEN pressure_type='upper' AND rank_in_type=2 THEN INJECTED_WATER_FORMATION_VOLUME_FACTOR END) second_upper_inj_water_fvf,
    COUNT(CASE WHEN pressure_type='exact' THEN 1 END) exact_count,
    COUNT(CASE WHEN pressure_type='lower' THEN 1 END) lower_count,
    COUNT(CASE WHEN pressure_type='upper' THEN 1 END) upper_count
  FROM PVTAnalysis GROUP BY COMPLETION_ID, DATE, target_pressure
),
-- CHECKPOINT 8: interpolate / 2-point extrapolate each PVT prop (NO DEFAULTS).
-- A reusable interp expression per property via the 6-priority ladder; Bg rounded
-- to 5 dp (legacy DECIMAL(_,5)). Also derive pvt_method for the confidence flag.
CalculatedPVT AS (
  SELECT COMPLETION_ID, DATE, target_pressure AS PRESSURE,
    CASE WHEN exact_count>0 THEN 'exact'
         WHEN lower_count>0 AND upper_count>0 THEN 'interpolated'
         WHEN (lower_count>0 AND second_lower_pressure IS NOT NULL)
           OR (upper_count>0 AND second_upper_pressure IS NOT NULL) THEN 'extrapolated'
         ELSE 'closest' END AS pvt_method,
    -- OIL FVF
    CASE WHEN exact_count>0 THEN exact_oil_fvf
         WHEN lower_count>0 AND upper_count>0 THEN lower_oil_fvf+(upper_oil_fvf-lower_oil_fvf)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_oil_fvf IS NOT NULL THEN lower_oil_fvf+(lower_oil_fvf-second_lower_oil_fvf)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_oil_fvf IS NOT NULL THEN upper_oil_fvf+(second_upper_oil_fvf-upper_oil_fvf)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_oil_fvf WHEN upper_count>0 THEN upper_oil_fvf ELSE NULL END AS OIL_FORMATION_VOLUME_FACTOR,
    -- GAS FVF (ROUND 5)
    ROUND(CASE WHEN exact_count>0 THEN exact_gas_fvf
         WHEN lower_count>0 AND upper_count>0 THEN lower_gas_fvf+(upper_gas_fvf-lower_gas_fvf)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_gas_fvf IS NOT NULL THEN lower_gas_fvf+(lower_gas_fvf-second_lower_gas_fvf)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_gas_fvf IS NOT NULL THEN upper_gas_fvf+(second_upper_gas_fvf-upper_gas_fvf)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_gas_fvf WHEN upper_count>0 THEN upper_gas_fvf ELSE NULL END, 5) AS GAS_FORMATION_VOLUME_FACTOR,
    -- WATER FVF
    CASE WHEN exact_count>0 THEN exact_water_fvf
         WHEN lower_count>0 AND upper_count>0 THEN lower_water_fvf+(upper_water_fvf-lower_water_fvf)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_water_fvf IS NOT NULL THEN lower_water_fvf+(lower_water_fvf-second_lower_water_fvf)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_water_fvf IS NOT NULL THEN upper_water_fvf+(second_upper_water_fvf-upper_water_fvf)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_water_fvf WHEN upper_count>0 THEN upper_water_fvf ELSE NULL END AS WATER_FORMATION_VOLUME_FACTOR,
    -- Rs (GOR)
    CASE WHEN exact_count>0 THEN exact_gor
         WHEN lower_count>0 AND upper_count>0 THEN lower_gor+(upper_gor-lower_gor)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_gor IS NOT NULL THEN lower_gor+(lower_gor-second_lower_gor)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_gor IS NOT NULL THEN upper_gor+(second_upper_gor-upper_gor)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_gor WHEN upper_count>0 THEN upper_gor ELSE NULL END AS SOLUTION_GAS_OIL_RATIO,
    -- Inj gas FVF
    CASE WHEN exact_count>0 THEN exact_inj_gas_fvf
         WHEN lower_count>0 AND upper_count>0 THEN lower_inj_gas_fvf+(upper_inj_gas_fvf-lower_inj_gas_fvf)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_inj_gas_fvf IS NOT NULL THEN lower_inj_gas_fvf+(lower_inj_gas_fvf-second_lower_inj_gas_fvf)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_inj_gas_fvf IS NOT NULL THEN upper_inj_gas_fvf+(second_upper_inj_gas_fvf-upper_inj_gas_fvf)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_inj_gas_fvf WHEN upper_count>0 THEN upper_inj_gas_fvf ELSE NULL END AS INJECTED_GAS_FORMATION_VOLUME_FACTOR,
    -- Inj water FVF
    CASE WHEN exact_count>0 THEN exact_inj_water_fvf
         WHEN lower_count>0 AND upper_count>0 THEN lower_inj_water_fvf+(upper_inj_water_fvf-lower_inj_water_fvf)*(target_pressure-lower_pressure)/NULLIF(upper_pressure-lower_pressure,0)
         WHEN lower_count>0 AND upper_count=0 AND second_lower_inj_water_fvf IS NOT NULL THEN lower_inj_water_fvf+(lower_inj_water_fvf-second_lower_inj_water_fvf)*(target_pressure-lower_pressure)/NULLIF(lower_pressure-second_lower_pressure,0)
         WHEN lower_count=0 AND upper_count>0 AND second_upper_inj_water_fvf IS NOT NULL THEN upper_inj_water_fvf+(second_upper_inj_water_fvf-upper_inj_water_fvf)*(target_pressure-upper_pressure)/NULLIF(second_upper_pressure-upper_pressure,0)
         WHEN lower_count>0 THEN lower_inj_water_fvf WHEN upper_count>0 THEN upper_inj_water_fvf ELSE NULL END AS INJECTED_WATER_FORMATION_VOLUME_FACTOR
  FROM PVTBounds
),
-- CHECKPOINT 9: volumes + interpolated PVT, per (pattern, completion, DATE).
VolumeWithPVT AS (
  SELECT vc.*, cp.pvt_method,
         cp.OIL_FORMATION_VOLUME_FACTOR, cp.GAS_FORMATION_VOLUME_FACTOR, cp.WATER_FORMATION_VOLUME_FACTOR,
         cp.SOLUTION_GAS_OIL_RATIO, cp.INJECTED_GAS_FORMATION_VOLUME_FACTOR, cp.INJECTED_WATER_FORMATION_VOLUME_FACTOR
    FROM VolumeContext vc
    LEFT JOIN CalculatedPVT cp
      ON vc.COMPLETION_ID = cp.COMPLETION_ID AND vc.DATE = cp.DATE AND vc.PRESSURE = cp.PRESSURE
)
-- reservoir-term formulas per completion. gas_multiplier = 1000 (KSCF->SCF).
-- Free gas gated on Amount_Type='Production' AND OIL_VOL>0 (NULL otherwise);
-- negative free gas allowed.
SELECT
  ID_PATTERN AS pattern_id, COMPLETION_ID AS completion_id, DATE AS vrr_date, FACTOR AS factor,
  OIL_VOL AS oil, WATER_VOL AS water, GAS_VOL AS gas, WATER_INJ_VOL AS water_inj, GAS_INJ_VOL AS gas_inj,
  PRESSURE AS pressure_psi,
  OIL_FORMATION_VOLUME_FACTOR AS bo, WATER_FORMATION_VOLUME_FACTOR AS bw, GAS_FORMATION_VOLUME_FACTOR AS bg,
  INJECTED_WATER_FORMATION_VOLUME_FACTOR AS bw_inj, INJECTED_GAS_FORMATION_VOLUME_FACTOR AS bg_inj,
  SOLUTION_GAS_OIL_RATIO AS rs, CAST(NULL AS DOUBLE) AS rv,
  pvt_method,
  CAST(NULL AS DOUBLE) AS pvt_bracket_lo, CAST(NULL AS DOUBLE) AS pvt_bracket_hi,
  CASE WHEN PRESSURE IS NULL THEN 'pressure'
       WHEN GAS_FORMATION_VOLUME_FACTOR IS NULL AND OIL_FORMATION_VOLUME_FACTOR IS NULL THEN 'pvt' ELSE NULL END AS missing_input,
  CASE WHEN OIL_FORMATION_VOLUME_FACTOR IS NOT NULL THEN FACTOR*OIL_VOL*OIL_FORMATION_VOLUME_FACTOR END AS oil_res,
  CASE WHEN WATER_FORMATION_VOLUME_FACTOR IS NOT NULL THEN WATER_VOL*FACTOR*WATER_FORMATION_VOLUME_FACTOR END AS water_res,
  CASE WHEN Amount_Type='Production' AND OIL_VOL>0 AND SOLUTION_GAS_OIL_RATIO IS NOT NULL AND GAS_FORMATION_VOLUME_FACTOR IS NOT NULL
       THEN ((GAS_VOL*1000)-(SOLUTION_GAS_OIL_RATIO*OIL_VOL))*FACTOR*GAS_FORMATION_VOLUME_FACTOR END AS free_gas_res,
  CASE WHEN INJECTED_WATER_FORMATION_VOLUME_FACTOR IS NOT NULL THEN WATER_INJ_VOL*FACTOR*INJECTED_WATER_FORMATION_VOLUME_FACTOR END AS water_inj_res,
  CASE WHEN INJECTED_GAS_FORMATION_VOLUME_FACTOR IS NOT NULL THEN GAS_INJ_VOL*1000*FACTOR*INJECTED_GAS_FORMATION_VOLUME_FACTOR END AS gas_inj_res,
  '${run_id}' AS run_id, current_timestamp() AS built_at
FROM VolumeWithPVT;

-- ---------------------------------------------------------------------------
-- STATEMENT 2 — pattern_vrr_daily (CHECKPOINTS 10-11) aggregated FROM the lineage
-- layer. VRR = COALESCE(INJ/NULLIF(PROD,0), 0); cumulative Σinj/Σprod to date.
-- HAVING keeps a row when production reservoir != 0 OR any injection > 0.
-- ---------------------------------------------------------------------------
INSERT OVERWRITE ${catalog}.vrr_curated.pattern_vrr_daily
WITH agg AS (
  SELECT c.pattern_id, MAX(p.PATTERN_NAME) pattern_name, c.vrr_date,
         SUM(COALESCE(oil_res,0)+COALESCE(water_res,0)+COALESCE(free_gas_res,0)) prod_res_bbl,
         SUM(COALESCE(water_inj_res,0)+COALESCE(gas_inj_res,0)) inj_res_bbl,
         COUNT(DISTINCT completion_id) n_completions,
         MAX(CASE WHEN pvt_method IN ('extrapolated','closest') THEN true ELSE false END) any_extrapolated,
         MIN(run_id) run_id,
         SUM(COALESCE(c.water_inj,0)+COALESCE(c.gas_inj,0)) _inj_surface
  FROM ${catalog}.vrr_curated.completion_contrib c
  LEFT JOIN ${catalog}.vrr_raw.pattern p ON c.pattern_id = p.ID_PATTERN
  GROUP BY c.pattern_id, c.vrr_date
  HAVING prod_res_bbl != 0 OR _inj_surface > 0
)
SELECT pattern_id, pattern_name, vrr_date, prod_res_bbl, inj_res_bbl,
       COALESCE(inj_res_bbl/NULLIF(prod_res_bbl,0), 0) AS vrr,
       SUM(prod_res_bbl) OVER w AS cum_prod_res_bbl,
       SUM(inj_res_bbl)  OVER w AS cum_inj_res_bbl,
       COALESCE(SUM(inj_res_bbl) OVER w / NULLIF(SUM(prod_res_bbl) OVER w,0),0) AS cum_vrr,
       n_completions, any_extrapolated, run_id, current_timestamp()
FROM agg
WINDOW w AS (PARTITION BY pattern_id ORDER BY vrr_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

-- ---------------------------------------------------------------------------
-- STATEMENT 3 — pattern_vrr_monthly (period_bucket = DATE_TRUNC('MM', DATE)).
-- ---------------------------------------------------------------------------
INSERT OVERWRITE ${catalog}.vrr_curated.pattern_vrr_monthly
WITH agg AS (
  SELECT c.pattern_id, MAX(p.PATTERN_NAME) pattern_name, date_trunc('MM', c.vrr_date) vrr_date,
         SUM(COALESCE(oil_res,0)+COALESCE(water_res,0)+COALESCE(free_gas_res,0)) prod_res_bbl,
         SUM(COALESCE(water_inj_res,0)+COALESCE(gas_inj_res,0)) inj_res_bbl,
         COUNT(DISTINCT completion_id) n_completions,
         MAX(CASE WHEN pvt_method IN ('extrapolated','closest') THEN true ELSE false END) any_extrapolated,
         MIN(run_id) run_id,
         SUM(COALESCE(c.water_inj,0)+COALESCE(c.gas_inj,0)) _inj_surface
  FROM ${catalog}.vrr_curated.completion_contrib c
  LEFT JOIN ${catalog}.vrr_raw.pattern p ON c.pattern_id = p.ID_PATTERN
  GROUP BY c.pattern_id, date_trunc('MM', c.vrr_date)
  HAVING prod_res_bbl != 0 OR _inj_surface > 0
)
SELECT pattern_id, pattern_name, vrr_date, prod_res_bbl, inj_res_bbl,
       COALESCE(inj_res_bbl/NULLIF(prod_res_bbl,0), 0) AS vrr,
       SUM(prod_res_bbl) OVER w AS cum_prod_res_bbl,
       SUM(inj_res_bbl)  OVER w AS cum_inj_res_bbl,
       COALESCE(SUM(inj_res_bbl) OVER w / NULLIF(SUM(prod_res_bbl) OVER w,0),0) AS cum_vrr,
       n_completions, any_extrapolated, run_id, current_timestamp()
FROM agg
WINDOW w AS (PARTITION BY pattern_id ORDER BY vrr_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);
