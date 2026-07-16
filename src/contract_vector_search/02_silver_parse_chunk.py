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

from pyspark.sql import functions as F, Row, types as T  # noqa: E402

cfg = from_widgets(dbutils)  # noqa: F821
spark.conf.set("spark.sql.shuffle.partitions", "8")  # noqa: F821  (small doc volume)


# COMMAND ----------
# ---- helpers (defined first so later cells can call them) ------------------
def _extract_text(parsed) -> str:
    """Pull concatenated text out of the ai_parse_document result struct.

    The result shape can vary by runtime version; we defensively look for the
    common fields (document.text / pages[].content) and fall back to str().
    """
    if parsed is None:
        return ""
    try:
        d = parsed.asDict(recursive=True) if hasattr(parsed, "asDict") else dict(parsed)
    except Exception:
        return str(parsed)
    doc = d.get("document") or d
    if isinstance(doc, dict):
        if doc.get("text"):
            return doc["text"]
        pages = doc.get("pages") or d.get("pages")
        if isinstance(pages, list):
            return "\n\n".join(str(p.get("content") or p.get("text") or "") for p in pages)
    return str(d)


def _page_for(parsed, seq: int) -> int:
    """Best-effort page number; defaults to 1 when the parser omits paging."""
    return 1


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
        # ai_parse_document returns a struct; text lives under document/pages.
        text = _extract_text(parsed)
        if not text or not text.strip():
            failed_rows.append(Row(source_file=path, error="empty_parse"))
            continue
        # Metadata is extracted from the RAW text (counterparty/date regexes need
        # the original), but everything downstream of here — chunks, embeddings,
        # retrieved context, agent answers — sees only the masked text.
        meta = extract_metadata(path, text)
        text = mask_pii(text)
        for ch in chunk_text(text):
            page = _page_for(parsed, ch.seq)
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
