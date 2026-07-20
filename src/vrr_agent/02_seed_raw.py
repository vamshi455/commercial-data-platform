# Databricks notebook source
# MAGIC %md
# MAGIC # VRR — seed raw tables (synthetic, source-shaped)
# MAGIC
# MAGIC Populates `vrr_raw.*` with a small, **deterministic** synthetic dataset shaped
# MAGIC exactly like the real pipeline (design §10), including the design's **worked
# MAGIC example (§8)**: pattern **UNITY** over-replaces in **April 2026** (VRR ≈ 1.3) vs
# MAGIC ~1.0 in **March**, driven by a **pattern-pressure decline** that shrinks the
# MAGIC free-gas term — with **PROD_WELL_003** the top contributor.
# MAGIC
# MAGIC The exact VRR is whatever the deterministic build (`03`/`04`) computes from this
# MAGIC data — we shape the *inputs*, never the answer. Idempotent (overwrites raw).

# COMMAND ----------
import datetime as dt

from src.vrr_agent.config import from_widgets

cfg = from_widgets(dbutils)  # noqa: F821 (Databricks-provided)
print("Catalog:", cfg.catalog)

# COMMAND ----------
# --- patterns -----------------------------------------------------------------
patterns = [("PUNITY", "UNITY"), ("PDELTA", "DELTA")]  # DELTA = a peer pattern
spark.createDataFrame(patterns, "ID_PATTERN string, PATTERN_NAME string") \
    .write.mode("overwrite").saveAsTable(cfg.raw_pattern)

# COMMAND ----------
# --- contribution factors (effective-dated; stable over the window) -----------
completions = ["PROD_WELL_001", "PROD_WELL_002", "PROD_WELL_003", "INJ_WELL_001"]
factors = [
    ("PROD_WELL_001", "PUNITY", 0.5, dt.date(2024, 1, 1)),
    ("PROD_WELL_002", "PUNITY", 0.5, dt.date(2024, 1, 1)),
    ("PROD_WELL_003", "PUNITY", 0.5, dt.date(2024, 1, 1)),
    ("INJ_WELL_001", "PUNITY", 1.0, dt.date(2024, 1, 1)),
    ("PROD_WELL_010", "PDELTA", 0.5, dt.date(2024, 1, 1)),
    ("INJ_WELL_010", "PDELTA", 1.0, dt.date(2024, 1, 1)),
]
spark.createDataFrame(
    factors, "ID_COMPLETION string, ID_PATTERN string, FACTOR double, EFFECT_DATE date"
).write.mode("overwrite").saveAsTable(cfg.raw_contribution_factor)

# COMMAND ----------
# --- pattern pressure: UNITY declines ~220 psi from March -> April ------------
# March ~3000 psi (on target), April ~2780 psi (the decline that swells free gas).
pressures = [
    ("PUNITY", dt.date(2026, 3, 1), 3000.0),
    ("PUNITY", dt.date(2026, 4, 1), 2780.0),   # ← −220 psi
    ("PDELTA", dt.date(2026, 3, 1), 2950.0),
    ("PDELTA", dt.date(2026, 4, 1), 2930.0),
]
spark.createDataFrame(
    pressures, "ID_PATTERN string, DATE date, PRESSURE double"
).write.mode("overwrite").saveAsTable(cfg.raw_pattern_pressure)

# COMMAND ----------
# --- PVT points per completion (Bg ≈ 1/P physics: higher pressure -> lower Bg) -
# Two lab points per producer bracket the operating range so April (2780) and
# March (3000) both INTERPOLATE (in-range, ✅). Bg rises as pressure falls, Rs falls.
def pvt(cid, p, bo, bw, bg, rs, rv=0.0):
    return (cid, dt.date(2025, 1, 1), p, bo, bw, bg,
            1.0, 0.0006, rs, rv)  # Bw_inj=1.0, Bg_inj≈0.0006 rb/scf


pvt_rows = []
for cid in ["PROD_WELL_001", "PROD_WELL_002", "PROD_WELL_003", "PROD_WELL_010"]:
    # low-pressure point (2700 psi): higher Bg, lower Rs
    pvt_rows.append(pvt(cid, 2700.0, 1.25, 1.02, 0.00090, 520.0))
    # high-pressure point (3100 psi): lower Bg, higher Rs
    pvt_rows.append((cid, dt.date(2025, 6, 1), 3100.0, 1.28, 1.01, 0.00078, 620.0, 0.0,
                     1.0, 0.0006))
# injectors reuse producer-like PVT (only inj FVFs matter for them)
for cid in ["INJ_WELL_001", "INJ_WELL_010"]:
    pvt_rows.append(pvt(cid, 2700.0, 1.25, 1.02, 0.00090, 520.0))
    pvt_rows.append((cid, dt.date(2025, 6, 1), 3100.0, 1.28, 1.01, 0.00078, 620.0, 0.0,
                     1.0, 0.0006))

pvt_schema = ("ID_COMPLETION string, TEST_DATE date, PRESSURE double, "
              "OIL_FORMATION_VOLUME_FACTOR double, WATER_FORMATION_VOLUME_FACTOR double, "
              "GAS_FORMATION_VOLUME_FACTOR double, INJECTED_WATER_FORMATION_VOLUME_FACTOR double, "
              "INJECTED_GAS_FORMATION_VOLUME_FACTOR double, SOLUTION_GAS_OIL_RATIO double, "
              "VOLATIZED_OIL_GAS_RATIO double")
spark.createDataFrame(pvt_rows, pvt_schema) \
    .write.mode("overwrite").saveAsTable(cfg.raw_pvt)

# COMMAND ----------
# --- daily volumes: injection ~flat, production ~flat; the VRR move comes from
# --- the PRESSURE decline (free-gas term), exactly per the design narrative.
# --- PROD_WELL_003 carries the largest gas rate -> it dominates the free-gas move.
import calendar


def days(year, month):
    n = calendar.monthrange(year, month)[1]
    return [dt.date(year, month, d) for d in range(1, n + 1)]


vol_rows = []
prod_profile = {  # (oil_stb/day, water_stb/day, gas_kscf/day)
    "PROD_WELL_001": (300.0, 200.0, 400.0),
    "PROD_WELL_002": (280.0, 220.0, 380.0),
    "PROD_WELL_003": (260.0, 240.0, 900.0),   # gassy well -> free-gas driver
    "PROD_WELL_010": (290.0, 210.0, 410.0),
}
inj_profile = {  # (water_inj_stb/day, gas_inj_kscf/day)
    "INJ_WELL_001": (1500.0, 0.0),
    "INJ_WELL_010": (1450.0, 0.0),
}
for (y, m) in [(2026, 3), (2026, 4)]:
    for d in days(y, m):
        for cid, (o, w, g) in prod_profile.items():
            vol_rows.append((cid, d, o, w, 0.0, g, 0.0))
        for cid, (wi, gi) in inj_profile.items():
            vol_rows.append((cid, d, 0.0, 0.0, wi, 0.0, gi))

vol_schema = ("EMSDB_PROD_COMPLETION_ID string, PROD_DATE date, "
              "ALLOC_OIL_VOL_STB double, ALLOC_WATER_VOL_STB double, "
              "ALLOC_WATER_INJ_VOL_STB double, ALLOC_GAS_VOL_KSCF double, "
              "ALLOC_GAS_INJ_VOL_KSCF double")
spark.createDataFrame(vol_rows, vol_schema) \
    .write.mode("overwrite").saveAsTable(cfg.raw_volumes_daily)

# COMMAND ----------
# --- optional per-pattern target (RM). UNITY target 1.0; DELTA left to default.
spark.createDataFrame(
    [("PUNITY", 1.0, "RM_2026")], "pattern_id string, target_vrr double, source string"
).write.mode("overwrite").saveAsTable(cfg.pattern_target)

print("seeded raw:", cfg.raw_volumes_daily, cfg.raw_pattern_pressure, cfg.raw_pvt)
