# Databricks notebook source
# MAGIC %md
# MAGIC # VRR — aggregate `completion_contrib` → `pattern_vrr_daily` / `_monthly`
# MAGIC
# MAGIC Design §10, handoff #2. VRR is just the aggregate of the lineage layer, so
# MAGIC every VRR traces straight back to `completion_contrib`:
# MAGIC
# MAGIC ```
# MAGIC PROD_RES = Σ(oil_res + water_res + free_gas_res)
# MAGIC INJ_RES  = Σ(water_inj_res + gas_inj_res)
# MAGIC VRR      = INJ_RES / PROD_RES          cum_VRR = Σinj / Σprod (running)
# MAGIC ```
# MAGIC No PVT/physics here — that already happened in `03`. Pure aggregation.

# COMMAND ----------
from pyspark.sql import functions as F, Window

from src.vrr_agent.config import from_widgets

cfg = from_widgets(dbutils)  # noqa: F821

contrib = spark.table(cfg.completion_contrib)
pat = spark.table(cfg.raw_pattern).select(
    F.col("ID_PATTERN").alias("pattern_id"), F.col("PATTERN_NAME").alias("pattern_name"))


def aggregate(df, date_col):
    g = (df.groupBy("pattern_id", date_col.alias("vrr_date"))
         .agg(
            (F.sum("oil_res") + F.sum("water_res") + F.sum("free_gas_res")).alias("prod_res_bbl"),
            (F.sum("water_inj_res") + F.sum("gas_inj_res")).alias("inj_res_bbl"),
            F.countDistinct("completion_id").alias("n_completions"),
            F.max(F.col("pvt_method") == F.lit("extrapolated")).alias("any_extrapolated"),
            F.first("run_id").alias("run_id")))
    g = g.withColumn("vrr", F.when(F.col("prod_res_bbl") != 0,
                                   F.col("inj_res_bbl") / F.col("prod_res_bbl")))
    # cumulative (running Σinj / Σprod to date, per pattern)
    w = Window.partitionBy("pattern_id").orderBy("vrr_date") \
              .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    g = (g.withColumn("cum_prod_res_bbl", F.sum("prod_res_bbl").over(w))
          .withColumn("cum_inj_res_bbl", F.sum("inj_res_bbl").over(w))
          .withColumn("cum_vrr", F.when(F.col("cum_prod_res_bbl") != 0,
                                        F.col("cum_inj_res_bbl") / F.col("cum_prod_res_bbl"))))
    return (g.join(pat, "pattern_id", "left")
             .withColumn("built_at", F.current_timestamp())
             .select("pattern_id", "pattern_name", "vrr_date", "prod_res_bbl", "inj_res_bbl",
                     "vrr", "cum_prod_res_bbl", "cum_inj_res_bbl", "cum_vrr",
                     "n_completions", "any_extrapolated", "run_id", "built_at"))


# COMMAND ----------
# --- daily -------------------------------------------------------------------
daily = aggregate(contrib, F.col("vrr_date"))
(daily.write.mode("overwrite").option("overwriteSchema", "true")
      .saveAsTable(cfg.pattern_vrr_daily))
print("built daily:", cfg.pattern_vrr_daily, daily.count(), "rows")

# COMMAND ----------
# --- monthly (grain = month-start date) --------------------------------------
monthly = aggregate(contrib, F.trunc(F.col("vrr_date"), "MM"))
(monthly.write.mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(cfg.pattern_vrr_monthly))
print("built monthly:", cfg.pattern_vrr_monthly, monthly.count(), "rows")

# COMMAND ----------
display(spark.table(cfg.pattern_vrr_monthly).orderBy("pattern_name", "vrr_date"))  # noqa: F821
