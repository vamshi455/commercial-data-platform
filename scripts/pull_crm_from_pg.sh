#!/usr/bin/env bash
# =============================================================================
# pull_crm_from_pg.sh — ON-DEMAND CRM pull: local Postgres -> Databricks bronze.
#
# Detects the live ngrok tunnel endpoint, points the crm_postgres_ingestion
# Lakeflow pipeline at it (host/port injected via --var, since the ngrok endpoint
# changes each restart), then deploys + runs the pipeline. Lands bronze.crm_pg_*.
#
# Prereqs: `ngrok tcp 5432` running, Postgres loaded (data_gen/postgres/load_crm.py),
#          the `cdp` secret scope holds pg_reader_password, and you're authed
#          (profile cdp-<target>).
#
# Usage:
#   scripts/pull_crm_from_pg.sh            # target dev
#   scripts/pull_crm_from_pg.sh qa
# =============================================================================
set -euo pipefail

TARGET="${1:-dev}"
PROFILE="cdp-${TARGET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

# 1) discover the current ngrok TCP endpoint from the local ngrok agent API
EP=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
  | python3 -c "import sys,json
try:
    t=json.load(sys.stdin).get('tunnels',[])
    print(t[0]['public_url'] if t else '')
except Exception:
    print('')")

if [[ -z "${EP}" ]]; then
  echo "ERROR: no ngrok tunnel found. Start it first:  ngrok tcp 5432" >&2
  exit 1
fi

HOST="$(echo "${EP}" | sed -E 's#tcp://([^:]+):([0-9]+)#\1#')"
PORT="$(echo "${EP}" | sed -E 's#tcp://([^:]+):([0-9]+)#\2#')"

echo ">> ngrok tunnel: ${HOST}:${PORT}"
echo ">> [${TARGET}] deploy crm_postgres_ingestion with current tunnel endpoint"
databricks bundle deploy -t "${TARGET}" -p "${PROFILE}" \
  --var "pg_host=${HOST}" --var "pg_port=${PORT}"

echo ">> [${TARGET}] run the pull (Postgres crm.* -> bronze.crm_pg_*)"
databricks bundle run crm_postgres_ingestion -t "${TARGET}" -p "${PROFILE}"

echo ">> done. Bronze tables: ${TARGET} catalog, schema bronze, crm_pg_*"
