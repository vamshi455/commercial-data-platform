"""Unstructured ingestion: PDF/Excel files -> bronze (raw bytes + parsed text).

Part of the RAG / unstructured track (see docs/rag-unstructured.md). This is the
**bronze** half: it lands documents faithfully, then extracts their text. Chunking,
masking and embedding happen downstream (silver + Vector Search).

Inputs
------
Documents dropped under the SAME landing Volume as the structured feeds::

    <landing>/unstructured/pdf/dt=YYYY-MM-DD/*.pdf
    <landing>/unstructured/excel/dt=YYYY-MM-DD/*.xlsx

Outputs
-------
* ``bronze_docs_raw``    — one row per file: content (binary), path, length,
  modificationTime + standard audit columns. Faithful, replayable capture.
* ``bronze_docs_parsed`` — one row per (file, page/sheet): ``extracted_text`` +
  document metadata. Parsing is deferred here so a parser change never requires
  re-landing files.

Why binaryFile Auto Loader
--------------------------
PDFs/XLSX are binary. Auto Loader with ``cloudFiles.format=binaryFile`` streams
one row per file incrementally + exactly-once, exactly like the CSV feeds — we
just capture bytes and parse in a second step.

Extraction (spike = Option B, portable)
---------------------------------------
* PDF   -> ``pymupdf`` (fitz) in a ``pandas_udf``, one row per page.
* Excel -> ``openpyxl``/pandas in a ``pandas_udf``, one row per sheet.
The pipeline must declare these pip deps (see resources/unstructured_ingestion.
pipeline.yml). The managed drop-in upgrade is the built-in ``ai_parse_document``
(Option A) once GA in-region — see docs/rag-unstructured.md §3.3.

Parsing is deliberately fault-tolerant: a file that fails to parse is KEPT with
``extracted_text=NULL`` and a ``parse_error`` string, surfaced as a soft DQ
expectation rather than failing the whole batch.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---------------------------------------------------------------------------
# Inlined config/audit helpers — serverless DLT cannot reliably IMPORT a .py
# from /Workspace files (OSError Errno 5), so the shared helpers are inlined
# here, mirroring the CRM/ERP ingestion modules. src/pipelines/_common.py stays
# the source of truth for local/test use.
# ---------------------------------------------------------------------------

SOURCE_SYSTEM = "docs"


def get_landing_path(default: str = "/Volumes/cdp_dev/landing/files") -> str:
    """Root landing path/Volume for raw source files (from Spark conf)."""
    return spark.conf.get("cdp.landing_path", default).rstrip("/")  # noqa: F821


def unstructured_glob(doc_type: str) -> str:
    """Auto Loader input path for a document type (``pdf`` / ``excel``)."""
    return f"{get_landing_path()}/unstructured/{doc_type}"


def schema_location(doc_type: str) -> str:
    """Per-doc-type schema/checkpoint location for Auto Loader."""
    return f"{get_landing_path()}/_schemas/{SOURCE_SYSTEM}/{doc_type}"


def with_audit_columns(df, batch_id: str | None = None):
    """Append the standard bronze audit columns (see bronze/README.md)."""
    out = (
        df.withColumn("_ingested_at", F.current_timestamp())
          .withColumn("_source_file", F.col("_metadata.file_path"))
          .withColumn("_source_system", F.lit(SOURCE_SYSTEM))
    )
    if batch_id is None:
        out = out.withColumn("_batch_id", F.date_format(F.current_timestamp(), "yyyy-MM-dd"))
    else:
        out = out.withColumn("_batch_id", F.lit(batch_id))
    return out


# Document types we ingest and how Auto Loader should find them.
DOC_TYPES: list[str] = ["pdf", "excel"]


# ---------------------------------------------------------------------------
# BRONZE 1 — raw capture, one streaming table per doc type (binaryFile).
# ---------------------------------------------------------------------------

def _make_raw_table(doc_type: str) -> None:
    @dlt.table(
        name=f"bronze_docs_raw_{doc_type}",
        comment=f"Raw {doc_type} documents landed via Auto Loader (binaryFile, append-only).",
        table_properties={
            "quality": "bronze",
            "pipelines.reset.allowed": "false",   # protect raw history from full refresh
            "delta.enableChangeDataFeed": "true",
        },
    )
    @dlt.expect("valid_source_file", "_source_file IS NOT NULL")
    def _raw():
        df = (
            spark.readStream.format("cloudFiles")  # noqa: F821 (spark runtime global)
            .option("cloudFiles.format", "binaryFile")
            .option("cloudFiles.schemaLocation", schema_location(doc_type))
            .option("pathGlobFilter", "*.pdf" if doc_type == "pdf" else "*.xlsx")
            .load(unstructured_glob(doc_type))
        )
        # binaryFile yields: path, modificationTime, length, content.
        return with_audit_columns(df).withColumn("doc_type", F.lit(doc_type))


for _dt in DOC_TYPES:
    _make_raw_table(_dt)


# ---------------------------------------------------------------------------
# Extraction UDFs (Option B — portable). One (page/sheet, text) pair per file.
# Returned as an array<struct> so we can explode to one row per logical unit.
# ---------------------------------------------------------------------------

_PARSE_SCHEMA = T.ArrayType(
    T.StructType([
        T.StructField("page_or_sheet", T.StringType()),
        T.StructField("extracted_text", T.StringType()),
        T.StructField("parse_error", T.StringType()),
    ])
)


@F.udf(returnType=_PARSE_SCHEMA)
def _extract_pdf(content: bytes):
    """Extract text per page from PDF bytes using pymupdf (fitz)."""
    try:
        import fitz  # pymupdf; declared as a pipeline dependency
    except Exception as e:  # dep missing at runtime
        return [{"page_or_sheet": None, "extracted_text": None,
                 "parse_error": f"pymupdf import failed: {e}"}]
    if content is None:
        return [{"page_or_sheet": None, "extracted_text": None, "parse_error": "empty content"}]
    try:
        out = []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for i, page in enumerate(doc):
                out.append({"page_or_sheet": f"page_{i + 1}",
                            "extracted_text": page.get_text("text") or "",
                            "parse_error": None})
        return out or [{"page_or_sheet": None, "extracted_text": "",
                        "parse_error": "no pages"}]
    except Exception as e:
        return [{"page_or_sheet": None, "extracted_text": None, "parse_error": str(e)}]


@F.udf(returnType=_PARSE_SCHEMA)
def _extract_excel(content: bytes):
    """Extract text per sheet from XLSX bytes using openpyxl (values only)."""
    try:
        import io
        import openpyxl  # declared as a pipeline dependency
    except Exception as e:
        return [{"page_or_sheet": None, "extracted_text": None,
                 "parse_error": f"openpyxl import failed: {e}"}]
    if content is None:
        return [{"page_or_sheet": None, "extracted_text": None, "parse_error": "empty content"}]
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows.append(" | ".join(cells))
            out.append({"page_or_sheet": ws.title,
                        "extracted_text": "\n".join(rows),
                        "parse_error": None})
        return out or [{"page_or_sheet": None, "extracted_text": "",
                        "parse_error": "no sheets"}]
    except Exception as e:
        return [{"page_or_sheet": None, "extracted_text": None, "parse_error": str(e)}]


# ---------------------------------------------------------------------------
# BRONZE 2 — parsed text, one row per (file, page/sheet).
# Reads the raw bronze tables cross-flow via fully-qualified names (the branch
# convention: spark.readStream.table(...) rather than dlt.read_stream).
# ---------------------------------------------------------------------------

def _make_parsed_table(doc_type: str, extractor) -> None:
    @dlt.table(
        name=f"bronze_docs_parsed_{doc_type}",
        comment=f"Extracted per-unit text from {doc_type} documents (bronze).",
        table_properties={"quality": "bronze"},
    )
    # Soft DQ: measure parse-failure rate without dropping rows.
    @dlt.expect("text_extracted", "extracted_text IS NOT NULL")
    def _parsed():
        catalog = spark.conf.get("cdp.catalog", "cdp_dev")  # noqa: F821
        raw = spark.readStream.table(f"{catalog}.bronze.bronze_docs_raw_{doc_type}")  # noqa: F821
        exploded = raw.withColumn("unit", F.explode(extractor(F.col("content"))))
        return (
            exploded
            .withColumn("doc_id", F.sha2(F.col("_source_file"), 256))
            .withColumn("page_or_sheet", F.col("unit.page_or_sheet"))
            .withColumn("extracted_text", F.col("unit.extracted_text"))
            .withColumn("parse_error", F.col("unit.parse_error"))
            .select(
                "doc_id", "doc_type", "page_or_sheet", "extracted_text", "parse_error",
                "_source_file", "_source_system", "_ingested_at", "_batch_id",
            )
        )


_make_parsed_table("pdf", _extract_pdf)
_make_parsed_table("excel", _extract_excel)
