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
#
# Workspace hosts: NOT stored in this repo. databricks.yml omits workspace.host
# (the CLI rejects ${var.*} interpolation there because it configures auth), so
# this script resolves the host per target from CDP_HOST_DEV / CDP_HOST_QA /
# CDP_HOST_PROD — read from a local .env (gitignored, see .env.example) — and
# exports it as DATABRICKS_HOST. It fails loudly if the target's host is unset.
#
# Using this script is what maps target -> workspace. A raw `databricks bundle
# deploy -t prod` deploys to whatever DATABRICKS_HOST already points at, which
# is why it is not the recommended path.
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

# ---- Resolve the workspace host for this target -----------------------------
# Load local, gitignored host config if present (does not override an already-
# exported value, so CI can inject hosts without a .env file).
if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

case "${TARGET}" in
  dev)  WORKSPACE_HOST="${CDP_HOST_DEV:-}"  ;;
  qa)   WORKSPACE_HOST="${CDP_HOST_QA:-}"   ;;
  prod) WORKSPACE_HOST="${CDP_HOST_PROD:-}" ;;
esac

if [[ -z "${WORKSPACE_HOST}" ]]; then
  VARNAME="CDP_HOST_$(echo "${TARGET}" | tr '[:lower:]' '[:upper:]')"
  cat >&2 <<EOF
ERROR: no workspace host configured for target '${TARGET}'.

  Workspace hosts are not stored in this repo. Set ${VARNAME} to the
  ${TARGET} workspace URL, either in a local .env file or in your shell:

      cp .env.example .env      # then fill in the CDP_HOST_* values
      # or:
      export ${VARNAME}=https://<host>.azuredatabricks.net

  See .env.example and databricks.yml (var.workspace_host).
EOF
  exit 1
fi

# databricks.yml omits workspace.host on purpose (the CLI rejects ${var.*} there,
# since it configures auth) — DATABRICKS_HOST is the supported injection point.
export DATABRICKS_HOST="${WORKSPACE_HOST}"

# ---- Prod safety gate -------------------------------------------------------
if [[ "${TARGET}" == "prod" && "${ASSUME_YES}" != "true" ]]; then
  echo "============================================================"
  echo "  You are about to DEPLOY TO PRODUCTION (cdp_prod)."
  echo "  Workspace: ${WORKSPACE_HOST}"
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
