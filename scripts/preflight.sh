#!/usr/bin/env bash
# =============================================================================
# preflight.sh — verify the local environment is ready to run the platform
# scripts (deploy.sh / generate_and_land.sh) against an Azure Databricks
# workspace. All checks are READ-ONLY; nothing is created or deployed.
#
# Usage:
#   scripts/preflight.sh            # tool + auth checks (defaults to dev)
#   scripts/preflight.sh -t qa      # also probe the cdp_qa catalog/volume
#
# Exit code 0 = ready; non-zero = at least one check failed.
# =============================================================================
set -uo pipefail

TARGET="dev"
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target) TARGET="${2:-}"; shift 2 ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

case "${TARGET}" in
  dev) CATALOG="cdp_dev" ;;
  qa)  CATALOG="cdp_qa" ;;
  prod) CATALOG="cdp_prod" ;;
  *) echo "ERROR: target must be dev|qa|prod (got '${TARGET}')" >&2; exit 1 ;;
esac
LANDING_VOLUME="/Volumes/${CATALOG}/landing/files"

PASS=0; FAIL=0
ok()   { printf "  \033[32mPASS\033[0m  %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[31mFAIL\033[0m  %s\n"  "$1"; FAIL=$((FAIL+1)); }
note() { printf "  ----  %s\n" "$1"; }

echo "Preflight checks (target=${TARGET}, catalog=${CATALOG})"
echo "-------------------------------------------------------"

# 1) Required CLI tooling -----------------------------------------------------
if command -v python3 >/dev/null 2>&1; then ok "python3: $(python3 --version 2>&1)"; else bad "python3 not found"; fi

if command -v databricks >/dev/null 2>&1; then
  ok "databricks CLI: $(databricks version 2>&1 | head -1)"
else
  bad "databricks CLI not found — install:  curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh"
fi

# 2) Auth to the workspace ----------------------------------------------------
if command -v databricks >/dev/null 2>&1; then
  if ME="$(databricks current-user me 2>/dev/null)"; then
    WHO="$(printf '%s' "$ME" | grep -oE '"userName"[^,]*' | head -1)"
    ok "authenticated as ${WHO:-<unknown>}"
  else
    bad "not authenticated — set DATABRICKS_HOST/CLIENT_ID/CLIENT_SECRET (see .env.example) or run 'databricks auth login'"
  fi

  # 3) Bundle validates for this target --------------------------------------
  if databricks bundle validate -t "${TARGET}" >/dev/null 2>&1; then
    ok "bundle validates (-t ${TARGET})"
  else
    bad "bundle validate -t ${TARGET} failed — run it directly to see why"
  fi

  # 4) Unity Catalog reachable (informational — created by job_platform_setup) -
  if databricks catalogs get "${CATALOG}" >/dev/null 2>&1; then
    ok "catalog ${CATALOG} exists"
    if databricks fs ls "dbfs:${LANDING_VOLUME}" >/dev/null 2>&1; then
      ok "landing volume ${LANDING_VOLUME} reachable"
    else
      note "landing volume ${LANDING_VOLUME} not found yet (created by job_platform_setup)"
    fi
  else
    note "catalog ${CATALOG} not found yet (created by job_platform_setup after deploy)"
  fi
fi

echo "-------------------------------------------------------"
echo "Summary: ${PASS} passed, ${FAIL} failed."
[[ "${FAIL}" -eq 0 ]] || { echo "Environment not ready — resolve the FAILs above."; exit 1; }
echo "Environment ready."
