#!/usr/bin/env bash
# =============================================================================
# deploy.sh — validate + deploy (+ optionally run) the Databricks Asset Bundle
# for a given target. Wraps `databricks bundle` with safety prompts for prod.
#
# Usage:
#   scripts/deploy.sh -t dev
#   scripts/deploy.sh -t qa
#   scripts/deploy.sh -t prod                # prompts for confirmation
#   scripts/deploy.sh -t dev -r job_orchestration_daily   # also run a resource
#   scripts/deploy.sh -t prod --yes          # skip the prod confirmation prompt
#
# Auth: the Databricks CLI reads DATABRICKS_HOST / DATABRICKS_CLIENT_ID /
#       DATABRICKS_CLIENT_SECRET (OAuth M2M) or your configured profile.
# =============================================================================
set -euo pipefail

TARGET=""
RUN_RESOURCE=""
ASSUME_YES="false"

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//' | sed '/^!/d'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target) TARGET="${2:-}"; shift 2 ;;
    -r|--run)    RUN_RESOURCE="${2:-}"; shift 2 ;;
    -y|--yes)    ASSUME_YES="true"; shift ;;
    -h|--help)   usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

if [[ -z "${TARGET}" ]]; then
  echo "ERROR: -t|--target is required (dev|qa|prod)" >&2
  usage 1
fi

case "${TARGET}" in
  dev|qa|prod) ;;
  *) echo "ERROR: target must be one of dev|qa|prod (got '${TARGET}')" >&2; exit 1 ;;
esac

# Run from the repo root (parent of this script's dir) so databricks.yml is found.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if ! command -v databricks >/dev/null 2>&1; then
  echo "ERROR: databricks CLI not found on PATH." >&2
  exit 1
fi

# ---- Prod safety gate -------------------------------------------------------
if [[ "${TARGET}" == "prod" && "${ASSUME_YES}" != "true" ]]; then
  echo "============================================================"
  echo "  You are about to DEPLOY TO PRODUCTION (cdp_prod)."
  echo "  Workspace: https://adb-7405618019865738.18.azuredatabricks.net"
  echo "============================================================"
  read -r -p "Type 'deploy-prod' to continue: " CONFIRM
  if [[ "${CONFIRM}" != "deploy-prod" ]]; then
    echo "Aborted." >&2
    exit 1
  fi
fi

echo ">> [${TARGET}] databricks bundle validate"
databricks bundle validate -t "${TARGET}"

echo ">> [${TARGET}] databricks bundle deploy"
databricks bundle deploy -t "${TARGET}"

if [[ -n "${RUN_RESOURCE}" ]]; then
  echo ">> [${TARGET}] databricks bundle run ${RUN_RESOURCE}"
  databricks bundle run "${RUN_RESOURCE}" -t "${TARGET}"
fi

echo ">> Done (${TARGET})."
