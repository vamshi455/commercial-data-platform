# Databricks notebook source
# =============================================================================
# 01_bronze_ingest — Auto Loader: contract PDFs -> bronze_raw_contract_docs
# -----------------------------------------------------------------------------
# Incremental, exactly-once, drain-and-stop. The SAME code does the historical
# backfill and every incremental load: the Auto Loader checkpoint decides what's
# new. First run (empty checkpoint) drains all existing files; later runs only
# pick up files that arrived since. trigger(availableNow=True) => no always-on
# compute (cost matters).
# =============================================================================
import sys, os

# Sibling module imports: the module folder is deployed intact by the bundle, so
# config lives next to this notebook. Ensure it's importable.
sys.path.append(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")
from config import from_widgets  # noqa: E402

from pyspark.sql import functions as F  # noqa: E402

cfg = from_widgets(dbutils)  # noqa: F821  (dbutils is a runtime global)
print(f"[bronze] catalog={cfg.catalog} schema={cfg.schema} source={cfg.raw_volume}")

# COMMAND ----------

# binaryFile Auto Loader stream. pathGlobFilter accepts *.pdf and *.PDF.
stream = (
    spark.readStream  # noqa: F821
    .format("cloudFiles")
    .option("cloudFiles.format", "binaryFile")
    .option("pathGlobFilter", "*.[pP][dD][fF]")
    .option("cloudFiles.includeExistingFiles", "true")
    .load(cfg.raw_volume)
    # binaryFile yields: path, modificationTime, length, content
    .withColumn("_ingested_at", F.current_timestamp())
    .withColumn("_source_file", F.col("path"))
)

(
    stream.writeStream
    .option("checkpointLocation", cfg.checkpoint("bronze_raw_contract_docs"))
    .option("mergeSchema", "true")
    .trigger(availableNow=True)          # drain-and-stop
    .toTable(cfg.bronze_table)
    .awaitTermination()
)

print(f"[bronze] wrote to {cfg.bronze_table}")
