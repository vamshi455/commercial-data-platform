#!/usr/bin/env bash
# =============================================================================
# scripts/sync_project_fields.sh
# -----------------------------------------------------------------------------
# Syncs the CDP project board's Priority / Area / Status fields FROM the issue
# labels, which are the source of truth. Re-run any time labels change.
#
# Mapping:
#   priority:P0..P3        -> Priority = P0..P3
#   area:<x>               -> Area     = <x>
#   status:ready           -> Status   = Ready
#   status:blocked         -> Status   = Backlog   (label carries the nuance)
#   status:needs-decision  -> Status   = Backlog
#
# Prereq: gh auth login -s project,repo
# Run:    bash scripts/sync_project_fields.sh
# Idempotent: setting a field to its current value is a no-op.
# =============================================================================
set -uo pipefail

OWNER="vamshi455"
REPO="$OWNER/commercial-data-platform"
PROJECT_NUMBER="${PROJECT_NUMBER:-6}"

PID="$(gh project view "$PROJECT_NUMBER" --owner "$OWNER" --format json -q '.id')"
FIELDS="$(gh project field-list "$PROJECT_NUMBER" --owner "$OWNER" --format json)"

fid()  { echo "$FIELDS" | jq -r --arg n "$1" '.fields[] | select(.name==$n) | .id'; }
oid()  { echo "$FIELDS" | jq -r --arg n "$1" --arg o "$2" \
           '.fields[] | select(.name==$n) | .options[] | select(.name==$o) | .id'; }

F_PRIO="$(fid Priority)"; F_AREA="$(fid Area)"; F_STAT="$(fid Status)"

# item id -> issue number
gh project item-list "$PROJECT_NUMBER" --owner "$OWNER" --limit 200 --format json \
  | jq -r '.items[] | select(.content.number != null) | "\(.content.number)\t\(.id)"' \
  | sort -n > /tmp/cdp_items.tsv

# issue number -> labels
gh issue list --repo "$REPO" --state all --limit 200 --json number,labels \
  | jq -r '.[] | "\(.number)\t\([.labels[].name] | join(","))"' | sort -n > /tmp/cdp_labels.tsv

set_field() { # <item-id> <field-id> <option-id>
  [[ -z "$3" ]] && return
  gh project item-edit --id "$1" --project-id "$PID" \
    --field-id "$2" --single-select-option-id "$3" >/dev/null 2>&1
}

N=0
join -t $'\t' /tmp/cdp_items.tsv /tmp/cdp_labels.tsv | while IFS=$'\t' read -r num item labels; do
  prio=""; area=""; stat=""
  case ",$labels," in
    *,priority:P0,*) prio=P0 ;; *,priority:P1,*) prio=P1 ;;
    *,priority:P2,*) prio=P2 ;; *,priority:P3,*) prio=P3 ;;
  esac
  for a in mdm rag agent-ops ingestion governance ml platform; do
    case ",$labels," in *",area:$a,"*) area="$a"; break ;; esac
  done
  case ",$labels," in
    *,status:ready,*) stat="Ready" ;;
    *,status:blocked,*|*,status:needs-decision,*) stat="Backlog" ;;
  esac

  [[ -n "$prio" ]] && set_field "$item" "$F_PRIO" "$(oid Priority "$prio")"
  [[ -n "$area" ]] && set_field "$item" "$F_AREA" "$(oid Area "$area")"
  [[ -n "$stat" ]] && set_field "$item" "$F_STAT" "$(oid Status "$stat")"
  echo "  #$num -> ${prio:--} / ${area:--} / ${stat:--}"
done

echo "Done. View: gh project view $PROJECT_NUMBER --owner $OWNER --web"
