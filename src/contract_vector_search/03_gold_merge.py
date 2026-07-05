# Databricks notebook source
# =============================================================================
# 03_gold_merge — MERGE silver chunks into gold_contract_chunks (dedup + CDF)
# -----------------------------------------------------------------------------
# * chunk_id = sha2(source_file || ':' || chunk_seq, 256)  (matches chunking.make_chunk_id)
# * MERGE keyed on chunk_id -> never blind append -> idempotent re-runs.
# * Amendment handling: when a NEW source_file arrives for a contract_id that is
#   already current under a DIFFERENT file, the prior version's chunks are set
#   is_current=false and the incoming chunks get an incremented version.
# CDF is already enabled on the gold table (DDL) so these updates+inserts flow
# into the Delta Sync vector index.
# =============================================================================
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")
from config import from_widgets  # noqa: E402
from versioning import detect_amendments  # noqa: E402

from pyspark.sql import functions as F  # noqa: E402

cfg = from_widgets(dbutils)  # noqa: F821

# COMMAND ----------
# Stage incoming chunks with deterministic chunk_id (Spark sha2 == sha256 hex,
# identical to chunking.make_chunk_id so tests and runtime agree).
incoming = (
    spark.table(cfg.silver_table)  # noqa: F821
    .withColumn("chunk_id", F.sha2(F.concat_ws(":", F.col("source_file"),
                                               F.col("chunk_seq").cast("string")), 256))
)
incoming.createOrReplaceTempView("incoming_chunks")

# COMMAND ----------
# Amendment detection (pure logic in versioning.detect_amendments): a contract_id
# is amended when an incoming file references it under a source_file that differs
# from its currently-active file(s). Collect the small driver-side sets and decide.
current = [
    (r["contract_id"], r["source_file"], r["version"])
    for r in spark.table(cfg.gold_table)  # noqa: F821
    .filter("is_current = true").select("contract_id", "source_file", "version").collect()
]
incoming_pairs = [
    (r["contract_id"], r["source_file"])
    for r in incoming.select("contract_id", "source_file").distinct().collect()
]
bump = detect_amendments(current, incoming_pairs)   # {contract_id: new_version}
print(f"[gold] {len(bump)} contract(s) being amended")

# COMMAND ----------
# Step A — retire prior versions for amended contracts (is_current=false).
for contract_id in bump:
    spark.sql(  # noqa: F821
        f"UPDATE {cfg.gold_table} SET is_current = false, _merged_at = current_timestamp() "
        "WHERE contract_id = :cid AND is_current = true",
        args={"cid": contract_id},
    )

# Assign incoming versions: amended contracts get new_version, else keep 1.
bump_expr = F.create_map(*sum(([F.lit(k), F.lit(v)] for k, v in bump.items()), [])) if bump else None
staged = spark.table("incoming_chunks")  # noqa: F821
if bump_expr is not None:
    staged = staged.withColumn(
        "version",
        F.coalesce(bump_expr.getItem(F.col("contract_id")), F.col("version")),
    ).withColumn("is_current", F.lit(True))
staged.createOrReplaceTempView("staged_chunks")

# COMMAND ----------
# Step B — MERGE on chunk_id. Idempotent: same file re-run overwrites in place.
spark.sql(f"""  -- noqa: F821
MERGE INTO {cfg.gold_table} AS t
USING (
  SELECT chunk_id, source_file, chunk_seq, chunk_text, page_number,
         contract_id, counterparty, contract_type, effective_date, expiry_date,
         version, is_current
  FROM staged_chunks
) AS s
ON t.chunk_id = s.chunk_id
WHEN MATCHED THEN UPDATE SET
  t.chunk_text = s.chunk_text, t.page_number = s.page_number,
  t.counterparty = s.counterparty, t.contract_type = s.contract_type,
  t.effective_date = s.effective_date, t.expiry_date = s.expiry_date,
  t.version = s.version, t.is_current = s.is_current, t._merged_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (
  chunk_id, source_file, chunk_seq, chunk_text, page_number, contract_id,
  counterparty, contract_type, effective_date, expiry_date, version, is_current, _merged_at
) VALUES (
  s.chunk_id, s.source_file, s.chunk_seq, s.chunk_text, s.page_number, s.contract_id,
  s.counterparty, s.contract_type, s.effective_date, s.expiry_date, s.version, s.is_current,
  current_timestamp()
)
""")
print(f"[gold] merged into {cfg.gold_table}")
