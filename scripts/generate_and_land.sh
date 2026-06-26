#!/usr/bin/env bash
# =============================================================================
# generate_and_land.sh — run the synthetic data generators, then upload the
# output into the target environment's Unity Catalog landing Volume so Auto
# Loader can ingest it into bronze.
#
# Usage:
#   scripts/generate_and_land.sh -t dev
#   scripts/generate_and_land.sh -t qa  --days 7 --seed 42
#   scripts/generate_and_land.sh -t dev --no-upload     # generate only
#
# The landing volume is derived from the target:
#   dev  -> /Volumes/cdp_dev/landing/files
#   qa   -> /Volumes/cdp_qa/landing/files
#   prod -> /Volumes/cdp_prod/landing/files   (generators are NOT for prod;
#           prod ingests real sources — this is blocked unless --force.)
#
# Auth: databricks CLI reads DATABRICKS_HOST / DATABRICKS_CLIENT_ID /
#       DATABRICKS_CLIENT_SECRET (OAuth M2M) or a configured profile.
# =============================================================================
set -euo pipefail

TARGET=""
DAYS="7"
SEED="42"
ACCOUNTS="50"
CUSTOMERS="60"
DO_UPLOAD="true"
FORCE="false"

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed '/^!/d'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target)    TARGET="${2:-}"; shift 2 ;;
    --days)         DAYS="${2:-}"; shift 2 ;;
    --seed)         SEED="${2:-}"; shift 2 ;;
    --accounts)     ACCOUNTS="${2:-}"; shift 2 ;;
    --customers)    CUSTOMERS="${2:-}"; shift 2 ;;
    --no-upload)    DO_UPLOAD="false"; shift ;;
    --force)        FORCE="true"; shift ;;
    -h|--help)      usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

if [[ -z "${TARGET}" ]]; then
  echo "ERROR: -t|--target is required (dev|qa|prod)" >&2
  usage 1
fi

case "${TARGET}" in
  dev) CATALOG="cdp_dev" ;;
  qa)  CATALOG="cdp_qa" ;;
  prod)
    CATALOG="cdp_prod"
    if [[ "${FORCE}" != "true" ]]; then
      echo "ERROR: refusing to land synthetic data into PROD. Use --force to override." >&2
      exit 1
    fi
    ;;
  *) echo "ERROR: target must be dev|qa|prod (got '${TARGET}')" >&2; exit 1 ;;
esac

LANDING_VOLUME="/Volumes/${CATALOG}/landing/files"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

OUT="data_gen/output"
PY="$(command -v python3 || command -v python)"

echo ">> Generating synthetic data into ${OUT} (days=${DAYS} seed=${SEED})"

# Reference + CRM first (CRM writes the crosswalk), then ERP (reads it).
"${PY}" data_gen/reference_data_generator.py --out "${OUT}/reference" --years 2
"${PY}" data_gen/crm_generator.py --out "${OUT}/crm" --days "${DAYS}" --seed "${SEED}" --accounts "${ACCOUNTS}"
"${PY}" data_gen/erp_generator.py --out "${OUT}/erp" --days "${DAYS}" --seed "${SEED}" \
    --customers "${CUSTOMERS}" --crm-out "${OUT}/crm"

if [[ "${DO_UPLOAD}" != "true" ]]; then
  echo ">> --no-upload set; generation complete, skipping landing."
  exit 0
fi

if ! command -v databricks >/dev/null 2>&1; then
  echo "ERROR: databricks CLI not found on PATH (needed to upload to ${LANDING_VOLUME})." >&2
  exit 1
fi

echo ">> Uploading ${OUT} -> ${LANDING_VOLUME} (recursive, overwrite)"
# `databricks fs cp -r` copies the local tree into the UC Volume; Auto Loader
# then discovers the dt=YYYY-MM-DD partitions under each entity.
databricks fs cp -r --overwrite "${OUT}" "dbfs:${LANDING_VOLUME}"

echo ">> Landed into ${LANDING_VOLUME} (catalog ${CATALOG}). Done."
