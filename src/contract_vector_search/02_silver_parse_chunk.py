# Databricks notebook source
# =============================================================================
# 02_silver_parse_chunk — parse PDFs, chunk, extract metadata
# -----------------------------------------------------------------------------
# Reads NEW bronze rows (those not yet parsed), runs ai_parse_document() on each,
# chunks the text (contract-aware), extracts metadata, and writes:
#   * silver_parsed_contracts   (one row per chunk)
#   * silver_parse_failures     (dead-letter: parse error / empty text)
# Idempotent: we only process bronze files whose path is not already present in
# silver (or failures), so re-runs don't duplicate.
# =============================================================================
import sys, os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")
from config import from_widgets           # noqa: E402
from chunking import chunk_text, make_chunk_id  # noqa: E402  (make_chunk_id used in gold)
from metadata_extract import extract_metadata   # noqa: E402
from masking import mask_pii                    # noqa: E402  (PII masked pre-embedding)
from parsing import (                           # noqa: E402
    extract_elements, elements_to_text, build_page_map, page_for_chunk,
)

from pyspark.sql import functions as F, Row, types as T  # noqa: E402

cfg = from_widgets(dbutils)  # noqa: F821
spark.conf.set("spark.sql.shuffle.partitions", "8")  # noqa: F821  (small doc volume)


# COMMAND ----------
# ---- helpers (defined first so later cells can call them) ------------------
# Text + page extraction lives in the pure `parsing` module (unit-tested
# off-cluster). It raises ParseShapeError rather than str()-ing an unrecognized
# result — the old inline helper's silent fallback wrote raw parse JSON into
# chunk_text, so every embedding/citation was built from JSON, not prose.


# COMMAND ----------
# Determine which bronze files still need parsing (anti-join on source_file).
bronze = spark.table(cfg.bronze_table)  # noqa: F821
# Union whichever of silver / failures already exist. A run with zero failures
# never creates the failures table, so guard each table independently — reading
# a not-yet-created table would raise TABLE_OR_VIEW_NOT_FOUND on the next run.
done = None
for tbl in (cfg.silver_table, cfg.failures_table):
    if spark.catalog.tableExists(tbl):  # noqa: F821
        part = spark.table(tbl).select(F.col("source_file"))  # noqa: F821
        done = part if done is None else done.union(part)
if done is not None:
    done = done.distinct()

todo = bronze.join(done, bronze.path == done.source_file, "left_anti") if done is not None else bronze
files = [r.path for r in todo.select("path").distinct().collect()]
print(f"[silver] {len(files)} new file(s) to parse")

# COMMAND ----------
# ai_parse_document() is a Databricks SQL AI function. We call it per file and
# pull back the extracted text. On failure / empty -> dead-letter.
parsed_rows, failed_rows = [], []
for path in files:
    try:
        df = spark.sql(  # noqa: F821
            "SELECT ai_parse_document(content) AS parsed "
            f"FROM {cfg.bronze_table} WHERE path = :p",
            args={"p": path},
        )
        parsed = df.collect()[0]["parsed"]
        # [(text, page)] — page comes from elements[].bbox[].page_id, so chunk
        # citations carry the real page rather than a hardcoded 1.
        elements = extract_elements(parsed)
        if not elements:
            failed_rows.append(Row(source_file=path, error="empty_parse"))
            continue
        # Metadata comes from the RAW text (the counterparty/date regexes need the
        # original). Masking is applied PER ELEMENT so the page-offset map stays
        # aligned with the masked text everything downstream actually sees.
        meta = extract_metadata(path, elements_to_text(elements))
        elements = [(mask_pii(t), p) for t, p in elements]
        text = elements_to_text(elements)
        page_map = build_page_map(elements)
        for ch in chunk_text(text):
            page = page_for_chunk(text, page_map, ch.text)
            parsed_rows.append(Row(
                source_file=path, chunk_seq=ch.seq, chunk_text=ch.text, page_number=page,
                contract_id=meta.contract_id, counterparty=meta.counterparty,
                contract_type=meta.contract_type, effective_date=meta.effective_date,
                expiry_date=meta.expiry_date, version=meta.version, is_current=meta.is_current,
            ))
    except Exception as e:  # noqa: BLE001 - never silently drop
        failed_rows.append(Row(source_file=path, error=str(e)[:1000]))

# COMMAND ----------
# Explicit schemas (mirror the DDL) — never rely on inference: with only a few
# docs, an all-None metadata column (e.g. effective_date) infers as NullType and
# raises [CANNOT_DETERMINE_TYPE]. Field order matches the Row(...) construction.
_SILVER_SCHEMA = T.StructType([
    T.StructField("source_file", T.StringType()),
    T.StructField("chunk_seq", T.IntegerType()),
    T.StructField("chunk_text", T.StringType()),
    T.StructField("page_number", T.IntegerType()),
    T.StructField("contract_id", T.StringType()),
    T.StructField("counterparty", T.StringType()),
    T.StructField("contract_type", T.StringType()),
    T.StructField("effective_date", T.StringType()),
    T.StructField("expiry_date", T.StringType()),
    T.StructField("version", T.IntegerType()),
    T.StructField("is_current", T.BooleanType()),
])
_FAILURES_SCHEMA = T.StructType([
    T.StructField("source_file", T.StringType()),
    T.StructField("error", T.StringType()),
])

if parsed_rows:
    (spark.createDataFrame(parsed_rows, schema=_SILVER_SCHEMA)  # noqa: F821
        .withColumn("_parsed_at", F.current_timestamp())
        .write.mode("append").saveAsTable(cfg.silver_table))
if failed_rows:
    (spark.createDataFrame(failed_rows, schema=_FAILURES_SCHEMA)  # noqa: F821
        .withColumn("failed_at", F.current_timestamp())
        .write.mode("append").saveAsTable(cfg.failures_table))
print(f"[silver] wrote {len(parsed_rows)} chunks, {len(failed_rows)} failures")
