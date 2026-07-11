"""collections agent — anomaly → diagnosis → drafted action (human-in-the-loop).

The flagship "agents beyond BI" build (see docs/specs/agentic-actions — pattern:
monitor -> diagnose -> draft -> HUMAN APPROVES -> learn). It watches
gold.collections_risk, flags accounts breaching AR-risk rules, has an LLM explain
the likely root cause and draft a tailored action (dunning email / CSM
escalation), and writes a PROPOSAL to ops.action_queue. It never sends anything —
a human approves in the queue, and the decision + outcome feed ops.action_feedback
so the agent improves.

Guardrails: read-only over governed gold; DRAFT-ONLY (no external action); every
proposal audited in the queue. Pure helpers (detection/priority/formatting) are
unit-tested off-cluster; the LLM step is lazily imported.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

GEN_MODEL = "databricks-claude-sonnet-5"

# Rules that make an account "actionable" (tunable; a real deployment would read
# these from config / a policy table).
DEFAULT_RULES = {
    "min_days_overdue": 30,
    "min_ar_balance": 5000.0,
    "actionable_tiers": {"High", "Medium"},
}


# --- pure logic (unit-tested) -----------------------------------------------
def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_actionable(account: dict, rules: dict = DEFAULT_RULES) -> bool:
    """True if the account breaches the collections rules (worth an action)."""
    return (
        account.get("risk_tier") in rules["actionable_tiers"]
        and _num(account.get("oldest_invoice_days")) >= rules["min_days_overdue"]
        and _num(account.get("ar_balance")) >= rules["min_ar_balance"]
    )


def priority_for(account: dict) -> str:
    """P1 (urgent, human touch) / P2 / P3 from risk, value, and health."""
    tier = account.get("risk_tier")
    ar = _num(account.get("ar_balance"))
    overdue = _num(account.get("oldest_invoice_days"))
    if tier == "High" and (ar >= 100_000 or account.get("account_health") == "Critical"):
        return "P1"
    if tier == "High" or overdue >= 60:
        return "P2"
    return "P3"


def recommend_action_type(account: dict) -> str:
    """High-value/urgent → human CSM call; otherwise an emailed dunning notice."""
    return "csm_escalation" if priority_for(account) == "P1" else "dunning_email"


def signal_for(account: dict) -> str:
    """One-line human-readable trigger summary for the queue."""
    return (f"{account.get('risk_tier')} risk · {int(_num(account.get('oldest_invoice_days')))}d overdue "
            f"· ${_num(account.get('ar_balance')):,.0f} AR · "
            f"{int(_num(account.get('open_invoice_count')))} open invoice(s)")


def action_id(account_id: str, run_id: str) -> str:
    import hashlib
    return hashlib.sha256(f"{account_id}::{run_id}".encode()).hexdigest()[:24]


def detect_actionable(accounts: list[dict], rules: dict = DEFAULT_RULES) -> list[dict]:
    """Filter + annotate the accounts that warrant an action, priority-ordered."""
    out = []
    for a in accounts:
        if is_actionable(a, rules):
            out.append({**a, "priority": priority_for(a),
                        "action_type": recommend_action_type(a),
                        "signal": signal_for(a)})
    return sorted(out, key=lambda x: (x["priority"], -_num(x.get("ar_balance"))))


# --- LLM diagnose + draft (lazy import) -------------------------------------
_PROMPT = """\
You are a B2B collections analyst. Given ONE account's AR facts, return STRICT JSON:
{{"diagnosis": "<1-2 sentences: likely root cause — oversight vs distress vs dispute — using the facts>",
  "draft": "<the {action_type}: a concise, professional {tone}. Reference the amount and days overdue. No placeholders like [NAME] unless data is missing.>"}}
Do not invent facts. Only use what is provided.

ACCOUNT FACTS:
{facts}
"""


def _facts_block(account: dict) -> str:
    keys = ["account_name", "risk_tier", "ar_balance", "oldest_invoice_days",
            "avg_days_to_pay", "open_invoice_count", "prior_slips",
            "account_health", "last_payment_date"]
    return "\n".join(f"- {k}: {account.get(k)}" for k in keys if k in account)


def diagnose_and_draft(account: dict, model: str = GEN_MODEL) -> dict:
    """Return {'diagnosis','draft'} from the LLM; robust to non-JSON replies."""
    from mlflow.deployments import get_deploy_client
    action_type = account.get("action_type", "dunning_email")
    tone = ("internal escalation note for a CSM to call the customer"
            if action_type == "csm_escalation" else "dunning email to the customer's AP contact")
    prompt = _PROMPT.format(action_type=action_type, tone=tone, facts=_facts_block(account))
    resp = get_deploy_client("databricks").predict(
        endpoint=model,
        inputs={"messages": [{"role": "user", "content": prompt}], "max_tokens": 600})
    text = resp["choices"][0]["message"]["content"]
    return parse_llm_json(text)


def parse_llm_json(text: str) -> dict:
    """Lenient extraction of {diagnosis, draft} from an LLM reply."""
    try:
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        obj = json.loads(m.group()) if m else {}
    except (json.JSONDecodeError, AttributeError):
        obj = {}
    return {"diagnosis": obj.get("diagnosis") or "(no diagnosis)",
            "draft": obj.get("draft") or (text or "").strip()}


def propose_actions(accounts: list[dict], run_id: str, model: str = GEN_MODEL) -> list[dict]:
    """Full agent turn: detect → diagnose+draft → proposal records for the queue."""
    proposals = []
    for a in detect_actionable(accounts):
        dd = diagnose_and_draft(a, model=model)
        proposals.append({
            "action_id": action_id(a["account_id"], run_id),
            "account_id": a["account_id"], "account_name": a.get("account_name"),
            "master_customer_id": a.get("master_customer_id"),
            "signal": a["signal"], "priority": a["priority"],
            "action_type": a["action_type"], "diagnosis": dd["diagnosis"],
            "draft": dd["draft"], "status": "pending", "run_id": run_id,
        })
    return proposals


def get_tools() -> list[dict]:
    return [{"name": "propose_collections_actions",
             "description": "Scan collections_risk, draft AR actions for human approval.",
             "parameters": {"run_id": "string"}, "fn": propose_actions}]
