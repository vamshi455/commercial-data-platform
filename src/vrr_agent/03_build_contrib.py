# Databricks notebook source
# MAGIC %md
# MAGIC # VRR — build `curated.completion_contrib` (the lineage layer)
# MAGIC
# MAGIC The step that **makes lineage real** (design §10, handoff #2): one row per
# MAGIC `(pattern, completion, date)` carrying **every root input** (factor, raw
# MAGIC volumes, pressure, interpolated PVT + method) **and** the per-term reservoir
# MAGIC contributions. Every downstream VRR aggregates straight back to these rows.
# MAGIC
# MAGIC All arithmetic uses `physics.py` (the same pure functions the tools use) — the
# MAGIC LLM is never in this path. As-of joins: FACTOR and PRESSURE use the latest
# MAGIC effective row ≤ the volume date; PVT is interpolated at that pressure.

# COMMAND ----------
import datetime as dt

from pyspark.sql import functions as F, Window

from src.vrr_agent.config import from_widgets
from src.vrr_agent import physics

cfg = from_widgets(dbutils)          # noqa: F821
try:
    dbutils.widgets.text("run_id", "")  # noqa: F821
    run_id = dbutils.widgets.get("run_id") or None  # noqa: F821
except Exception:
    run_id = None

# COMMAND ----------
# --- load raw ----------------------------------------------------------------
vol = spark.table(cfg.raw_volumes_daily)
fac = spark.table(cfg.raw_contribution_factor)
prs = spark.table(cfg.raw_pattern_pressure)
pvt = spark.table(cfg.raw_pvt)
pat = spark.table(cfg.raw_pattern)

# COMMAND ----------
# --- as-of FACTOR: latest EFFECT_DATE <= PROD_DATE, per (completion, pattern) --
# The factor also tells us which pattern a completion belongs to on that date.
vf = (vol.alias("v")
      .join(fac.alias("f"), F.col("v.EMSDB_PROD_COMPLETION_ID") == F.col("f.ID_COMPLETION"))
      .where(F.col("f.EFFECT_DATE") <= F.col("v.PROD_DATE")))
w_fac = Window.partitionBy("v.EMSDB_PROD_COMPLETION_ID", "f.ID_PATTERN", "v.PROD_DATE") \
             .orderBy(F.col("f.EFFECT_DATE").desc())
vf = (vf.withColumn("_rn", F.row_number().over(w_fac)).where("_rn = 1").drop("_rn"))

# --- as-of PRESSURE: latest pattern_pressure.DATE <= PROD_DATE ----------------
vfp = (vf.join(prs.alias("p"), F.col("f.ID_PATTERN") == F.col("p.ID_PATTERN"))
       .where(F.col("p.DATE") <= F.col("v.PROD_DATE")))
w_prs = Window.partitionBy("f.ID_COMPLETION", "f.ID_PATTERN", "v.PROD_DATE") \
             .orderBy(F.col("p.DATE").desc())
vfp = (vfp.withColumn("_rn", F.row_number().over(w_prs)).where("_rn = 1").drop("_rn"))

# COMMAND ----------
# --- collect PVT points per completion once, apply physics per row in a UDF ----
# physics.pvt_lookup + completion_contribution run per (completion,date) using the
# completion's PVT points and the as-of pressure. We broadcast the PVT points map.
pvt_by_comp: dict[str, list] = {}
for r in pvt.collect():
    pvt_by_comp.setdefault(r["ID_COMPLETION"], []).append(
        physics.PVTPoint(
            pressure_psi=r["PRESSURE"],
            bo=r["OIL_FORMATION_VOLUME_FACTOR"], bw=r["WATER_FORMATION_VOLUME_FACTOR"],
            bg=r["GAS_FORMATION_VOLUME_FACTOR"], rs=r["SOLUTION_GAS_OIL_RATIO"],
            rv=r["VOLATIZED_OIL_GAS_RATIO"] or 0.0,
            bw_inj=r["INJECTED_WATER_FORMATION_VOLUME_FACTOR"],
            bg_inj=r["INJECTED_GAS_FORMATION_VOLUME_FACTOR"],
            test_date=str(r["TEST_DATE"]),
        ))
pvt_bc = spark.sparkContext.broadcast(pvt_by_comp)
_run = run_id or f"contrib-{dt.datetime.utcnow().isoformat(timespec='seconds')}"


def _build_rows(rows):
    pvt_map = pvt_bc.value
    for r in rows:
        cid = r["ID_COMPLETION"]
        is_producer = (r["ALLOC_WATER_INJ_VOL_STB"] or 0) == 0 and (r["ALLOC_GAS_INJ_VOL_KSCF"] or 0) == 0
        pr = physics.pvt_lookup(pvt_map.get(cid, []), r["PRESSURE"])
        missing = None
        if r["PRESSURE"] is None:
            missing = "pressure"
        elif not pvt_map.get(cid):
            missing = "pvt"
        terms = physics.completion_contribution(
            factor=r["FACTOR"], oil=r["ALLOC_OIL_VOL_STB"], water=r["ALLOC_WATER_VOL_STB"],
            gas=r["ALLOC_GAS_VOL_KSCF"], water_inj=r["ALLOC_WATER_INJ_VOL_STB"],
            gas_inj=r["ALLOC_GAS_INJ_VOL_KSCF"], pvt=pr.props, is_producer=is_producer)
        p = pr.props
        yield (
            r["ID_PATTERN"], cid, r["PROD_DATE"], r["FACTOR"],
            r["ALLOC_OIL_VOL_STB"], r["ALLOC_WATER_VOL_STB"], r["ALLOC_GAS_VOL_KSCF"],
            r["ALLOC_WATER_INJ_VOL_STB"], r["ALLOC_GAS_INJ_VOL_KSCF"], r["PRESSURE"],
            p.get("bo"), p.get("bw"), p.get("bg"), p.get("bw_inj"), p.get("bg_inj"),
            p.get("rs"), p.get("rv"), pr.method,
            (pr.bracket[0] if pr.bracket else None), (pr.bracket[1] if pr.bracket else None),
            missing,
            terms.oil_res, terms.water_res, terms.free_gas_res,
            terms.water_inj_res, terms.gas_inj_res, _run,
        )


out_schema = ("pattern_id string, completion_id string, vrr_date date, factor double, "
              "oil double, water double, gas double, water_inj double, gas_inj double, "
              "pressure_psi double, bo double, bw double, bg double, bw_inj double, bg_inj double, "
              "rs double, rv double, pvt_method string, pvt_bracket_lo double, pvt_bracket_hi double, "
              "missing_input string, oil_res double, water_res double, free_gas_res double, "
              "water_inj_res double, gas_inj_res double, run_id string")

src = vfp.select(
    "f.ID_PATTERN", "f.ID_COMPLETION", "v.PROD_DATE", "f.FACTOR",
    "v.ALLOC_OIL_VOL_STB", "v.ALLOC_WATER_VOL_STB", "v.ALLOC_GAS_VOL_KSCF",
    "v.ALLOC_WATER_INJ_VOL_STB", "v.ALLOC_GAS_INJ_VOL_KSCF", "p.PRESSURE")

contrib = (src.rdd.mapPartitions(_build_rows).toDF(out_schema)
           .withColumn("built_at", F.current_timestamp()))

(contrib.write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(cfg.completion_contrib))
print("built:", cfg.completion_contrib, contrib.count(), "rows · run", _run)
