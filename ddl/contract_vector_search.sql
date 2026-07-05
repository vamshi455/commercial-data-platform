-- Databricks notebook source
-- =============================================================================
-- ddl/contract_vector_search.sql
-- -----------------------------------------------------------------------------
-- Schema, volumes, and tables for the contract_vector_search module.
-- Idempotent: safe to re-run. Parameterized on :catalog (job widget) so the
-- SAME DDL creates cdp_dev.contracts / cdp_qa.contracts / cdp_prod.contracts.
--
-- Run via the module Job (task 00_ddl) or manually:
--   spark.sql on a serverless SQL warehouse with catalog widget = cdp_dev
-- =============================================================================

-- Schema + volumes -----------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS ${catalog}.contracts
  COMMENT 'Crude-oil contract documents: raw files, parsed text, RAG chunks.';

CREATE VOLUME IF NOT EXISTS ${catalog}.contracts.raw_contract_files
  COMMENT 'Landing volume for incoming contract PDFs (Auto Loader source).';

CREATE VOLUME IF NOT EXISTS ${catalog}.contracts.checkpoints
  COMMENT 'Auto Loader / structured-streaming checkpoints (one dir per stream).';

-- Bronze: raw binary + file metadata ----------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.contracts.bronze_raw_contract_docs (
  path              STRING    COMMENT 'Full Volume path of the source PDF',
  modificationTime  TIMESTAMP COMMENT 'Source file mtime (Auto Loader binaryFile)',
  length            BIGINT    COMMENT 'File size in bytes',
  content           BINARY    COMMENT 'Raw file bytes',
  _ingested_at      TIMESTAMP COMMENT 'Processing time this row was ingested',
  _source_file      STRING    COMMENT 'Alias of path, standard audit column'
)
COMMENT 'Incremental raw contract PDFs landed by Auto Loader (binaryFile).';

-- Silver: parsed + chunked ---------------------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.contracts.silver_parsed_contracts (
  source_file     STRING COMMENT 'Origin PDF path',
  chunk_seq       INT    COMMENT '0-based chunk position within the file',
  chunk_text      STRING COMMENT 'Chunk body (contract-aware split)',
  page_number     INT    COMMENT 'Best-effort source page for the chunk',
  contract_id     STRING,
  counterparty    STRING,
  contract_type   STRING,
  effective_date  STRING,
  expiry_date     STRING,
  version         INT    COMMENT 'Document version (amendments increment this)',
  is_current      BOOLEAN COMMENT 'False once superseded by a newer version',
  _parsed_at      TIMESTAMP
)
COMMENT 'Parsed + chunked contract text with extracted metadata.';

-- Silver dead-letter: parse failures (never silently drop) -------------------
CREATE TABLE IF NOT EXISTS ${catalog}.contracts.silver_parse_failures (
  source_file  STRING    COMMENT 'PDF that failed to parse / produced empty text',
  error        STRING    COMMENT 'Failure reason',
  failed_at    TIMESTAMP
)
COMMENT 'Dead-letter table for documents that ai_parse_document could not parse.';

-- Gold: dedup chunks, CDF on for Delta Sync ----------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.contracts.gold_contract_chunks (
  chunk_id        STRING NOT NULL COMMENT 'sha2(source_file || ":" || chunk_seq, 256)',
  source_file     STRING,
  chunk_seq       INT,
  chunk_text      STRING,
  page_number     INT,
  contract_id     STRING,
  counterparty    STRING,
  contract_type   STRING,
  effective_date  STRING,
  expiry_date     STRING,
  version         INT,
  is_current      BOOLEAN,
  _merged_at      TIMESTAMP
)
COMMENT 'Deduplicated contract chunks; source of the Delta Sync vector index.'
TBLPROPERTIES (delta.enableChangeDataFeed = true);   -- REQUIRED for Delta Sync

-- Primary key enables the Delta Sync index primary_key = chunk_id.
ALTER TABLE ${catalog}.contracts.gold_contract_chunks
  ADD CONSTRAINT IF NOT EXISTS pk_gold_contract_chunks PRIMARY KEY (chunk_id);
