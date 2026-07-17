#!/usr/bin/env bash
# =============================================================================
# check_idle_compute.sh — find and stop unnecessary Databricks compute so
# nothing bills overnight. Meant to run at EOD (manually, or via a scheduled
# check) against the dev workspace.
#
# Categories and what happens to each (auto-remediation is intentionally NOT
# uniform — see the note on serving endpoints below):
#   * All-purpose clusters running       -> TERMINATED  (safe: config kept,
#                                            restart any time; not a hard delete)
#   * SQL warehouses running             -> STOPPED      (same: instant restart)
#   * Vector Search endpoints (any)      -> DELETED      (STANDARD endpoints bill
#                                            always-on regardless of query volume —
#                                            existence itself is the cost. This repo's
#                                            established pattern is recreate-when-needed;
#                                            see docs/checkpoint.md)
#   * Model serving endpoints            -> FLAGGED ONLY, never auto-deleted.
#       Foundation-model endpoints (system.ai.*) are pay-per-token with no idle
#       cost and are skipped entirely. Custom UC-model endpoints (e.g. the
#       contract_intelligence agent) already scale to zero by design
#       (agents.deploy(scale_to_zero=True)) so idle cost is ~0; deleting one
#       requires a full redeploy to restore, which is a much bigger blast
#       radius than the money saved. If one is found WITHOUT scale-to-zero,
#       that's a real cost leak — this script flags it loudly for a human
#       decision rather than deleting a live agent endpoint unattended.
#
# Usage:
#   scripts/check_idle_compute.sh              # report + remediate (see above)
#   scripts/check_idle_compute.sh --dry-run    # report only, remediate nothing
#
# Exit code 0 = clean or successfully remediated; 1 = a serving endpoint needs
# a human decision (see FLAG output).
# =============================================================================
set -uo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

FOUND=0; REMEDIATED=0; FLAGGED=0
ok()   { printf "  \033[32mCLEAN\033[0m  %s\n" "$1"; }
warn() { printf "  \033[33mFOUND\033[0m  %s\n"  "$1"; FOUND=$((FOUND+1)); }
did()  { printf "  \033[36m ->\033[0m %s\n" "$1"; REMEDIATED=$((REMEDIATED+1)); }
flag() { printf "  \033[31mFLAG\033[0m  %s\n"  "$1"; FLAGGED=$((FLAGGED+1)); }

echo "Idle compute check — $(date '+%Y-%m-%d %H:%M %Z')$($DRY_RUN && echo ' [dry-run]')"
echo "-------------------------------------------------------"

# 1) All-purpose clusters -----------------------------------------------------
echo "Clusters:"
clusters="$(databricks clusters list --output json 2>/dev/null)"
running="$(echo "${clusters}" | jq -c '[.[] | select(.state=="RUNNING" or .state=="PENDING" or .state=="RESIZING")]')"
count="$(echo "${running}" | jq 'length')"
if [[ "${count}" -eq 0 ]]; then
  ok "no clusters running"
else
  while read -r cid cname cstate; do
    warn "cluster '${cname}' (${cid}) is ${cstate}"
    if ! $DRY_RUN; then
      databricks clusters delete "${cid}" >/dev/null 2>&1 && did "terminated ${cname}"
    fi
  done < <(echo "${running}" | jq -r '.[] | "\(.cluster_id) \(.cluster_name) \(.state)"')
fi

# 2) SQL warehouses ------------------------------------------------------------
echo "SQL warehouses:"
warehouses="$(databricks warehouses list --output json 2>/dev/null)"
running_wh="$(echo "${warehouses}" | jq -c '[.[] | select(.state=="RUNNING")]')"
count="$(echo "${running_wh}" | jq 'length')"
if [[ "${count}" -eq 0 ]]; then
  ok "no warehouses running"
else
  while read -r wid wname; do
    warn "warehouse '${wname}' (${wid}) is RUNNING"
    if ! $DRY_RUN; then
      databricks warehouses stop "${wid}" >/dev/null 2>&1 && did "stopped ${wname}"
    fi
  done < <(echo "${running_wh}" | jq -r '.[] | "\(.id) \(.name)"')
fi

# 3) Vector Search endpoints ---------------------------------------------------
echo "Vector Search endpoints:"
vs="$(databricks vector-search-endpoints list-endpoints 2>/dev/null)"
count="$(echo "${vs}" | jq 'length')"
if [[ "${count}" -eq 0 ]]; then
  ok "no VS Search endpoints (no always-on billing)"
else
  while read -r vname; do
    warn "VS Search endpoint '${vname}' exists (always-on billing regardless of activity)"
    if ! $DRY_RUN; then
      databricks vector-search-endpoints delete-endpoint "${vname}" >/dev/null 2>&1 && did "deleted ${vname} (recreate via job_contract_vector_search when next needed — remember to 'vector-search-indexes delete-index' the orphaned UC entity first if get-index says missing but create says already-exists, per docs/checkpoint.md)"
    fi
  done < <(echo "${vs}" | jq -r '.[] | .name')
fi

# 4) Model serving endpoints — flag only, never auto-delete --------------------
# NB: `serving-endpoints list` omits scale_to_zero_enabled from served_entities;
# only `serving-endpoints get <name>` returns it, so each custom endpoint needs
# an individual get call for an accurate reading.
echo "Serving endpoints:"
se="$(databricks serving-endpoints list --output json 2>/dev/null)"
custom_names="$(echo "${se}" | jq -r '.[] | select(.config.served_entities[0].entity_name != null and (.config.served_entities[0].entity_name | startswith("system.ai.") | not)) | .name')"
if [[ -z "${custom_names}" ]]; then
  ok "no custom-model serving endpoints (foundation-model endpoints are pay-per-token, skipped)"
else
  while read -r name; do
    [[ -z "${name}" ]] && continue
    detail="$(databricks serving-endpoints get "${name}" --output json 2>/dev/null)"
    stz="$(echo "${detail}" | jq -r '[.config.served_entities[].scale_to_zero_enabled] | all')"
    if [[ "${stz}" == "true" ]]; then
      ok "serving endpoint '${name}' — scale-to-zero on, no idle cost"
    else
      flag "serving endpoint '${name}' — NOT scale-to-zero; idle cost likely — needs a human decision, not auto-deleted"
    fi
  done <<< "${custom_names}"
fi

echo "-------------------------------------------------------"
echo "Summary: ${FOUND} found, ${REMEDIATED} remediated, ${FLAGGED} flagged for review."
[[ "${FLAGGED}" -eq 0 ]] || exit 1
exit 0
