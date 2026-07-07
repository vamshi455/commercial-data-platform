"""Silver: parsed document text -> chunked, masked, embeddable rows.

Part of the RAG / unstructured track (see docs/rag-unstructured.md). Reads the
``bronze_docs_parsed_*`` tables, splits each page/sheet into retrieval-sized
chunks, attaches metadata + a stable ``chunk_id``, and masks PII on the chunk
text BEFORE it is embedded.

Output
------
``silver_doc_chunks`` — one row per chunk::

    chunk_id, doc_id, doc_type, source_path, page_or_sheet, chunk_index,
    master_customer_id, text (masked), _ingested_at, _batch_id

This is the table the Databricks Vector Search **Delta Sync Index** reads from
(``embedding_source_column = "text"``). The index — and the RAG agent retrieval
over it — are one-time workspace setup, sketched in docs/rag-unstructured.md §6,
not DLT tables.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---------------------------------------------------------------------------
# Inlined chunker — source of truth is src/pipelines/silver/_text_chunking.py
# (serverless DLT cannot import a .py from /Workspace files). Keep in sync.
# ---------------------------------------------------------------------------


def chunk_text(text, max_tokens: int = 800, overlap: int = 100):
    """Split text into overlapping, retrieval-sized chunks (word-window)."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError("overlap must be >= 0 and < max_tokens")
    if not text or not text.strip():
        return []
    words = text.split()
    if len(words) <= max_tokens:
        return [" ".join(words)]
    step = max_tokens - overlap
    chunks = []
    for start in range(0, len(words), step):
        window = words[start:start + max_tokens]
        if window:
            chunks.append(" ".join(window))
        if start + max_tokens >= len(words):
            break
    return chunks


# Chunk config (see docs/rag-unstructured.md §7 — tune per corpus).
MAX_TOKENS = 800
OVERLAP = 100

# UDF returning the ordered list of chunk strings for a page/sheet.
_chunk_udf = F.udf(lambda t: chunk_text(t, MAX_TOKENS, OVERLAP), T.ArrayType(T.StringType()))


def _mask_pii(col):
    """Lightweight free-text PII redaction applied BEFORE embedding.

    A spike-grade regex pass (emails, phone-ish, long digit runs) so no raw PII
    reaches the vector index on synthetic dev data. The production path routes
    through the platform's governed masking functions (governance/
    masking_functions.sql) and the prod-strict env guard (gold.is_prod); see
    docs/rag-unstructured.md §3.4.
    """
    c = F.regexp_replace(col, r"[\w.+-]+@[\w-]+\.[\w.-]+", "[EMAIL]")
    c = F.regexp_replace(c, r"\+?\d[\d\s().-]{7,}\d", "[PHONE]")
    return c


@dlt.table(
    name="silver_doc_chunks",
    comment="Chunked, PII-masked document text ready for Vector Search embedding.",
    table_properties={
        "quality": "silver",
        "delta.enableChangeDataFeed": "true",  # Vector Search Delta Sync reads CDF
    },
)
@dlt.expect_or_drop("has_text", "text IS NOT NULL AND length(trim(text)) > 0")
@dlt.expect("has_chunk_id", "chunk_id IS NOT NULL")
def silver_doc_chunks():
    catalog = spark.conf.get("cdp.catalog", "cdp_dev")  # noqa: F821
    # Union the per-doc-type parsed bronze tables (streaming reads, cross-flow
    # via fully-qualified names — the branch convention).
    pdf = spark.readStream.table(f"{catalog}.bronze.bronze_docs_parsed_pdf")    # noqa: F821
    xls = spark.readStream.table(f"{catalog}.bronze.bronze_docs_parsed_excel")  # noqa: F821
    parsed = pdf.unionByName(xls, allowMissingColumns=True)

    exploded = (
        parsed
        .filter(F.col("extracted_text").isNotNull())
        .withColumn("chunk", F.posexplode(_chunk_udf(F.col("extracted_text"))))
    )
    # posexplode yields columns `pos` (chunk_index) and `col` (chunk text).
    return (
        exploded
        .withColumnRenamed("pos", "chunk_index")
        .withColumn("text", _mask_pii(F.col("col")))
        # Stable, idempotent surrogate: sha2(doc_id || page || chunk_index).
        .withColumn(
            "chunk_id",
            F.sha2(F.concat_ws("||", "doc_id", "page_or_sheet",
                               F.col("chunk_index").cast("string")), 256),
        )
        # Customer link via filename convention now (e.g. .../<mcid>__file.pdf);
        # content-based linking is a documented later enhancement.
        .withColumn(
            "master_customer_id",
            F.regexp_extract(F.col("_source_file"), r"/([0-9a-f]{8,})__", 1),
        )
        .withColumnRenamed("_source_file", "source_path")
        .select(
            "chunk_id", "doc_id", "doc_type", "source_path", "page_or_sheet",
            "chunk_index", "master_customer_id", "text",
            "_ingested_at", "_batch_id",
        )
    )
