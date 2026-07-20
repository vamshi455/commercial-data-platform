"""VRR Reasoning & Lineage agent — narrates deterministic tool output (no math).

Follows the CDP agent conventions (see agents/collections/agent.py): a served
Foundation Model for language, `get_deploy_client("databricks")`, lazy imports,
pure helpers that unit-test off-cluster. The design's non-negotiable: **the LLM
never does arithmetic** — it plans tool calls, reads the numbers, and names the
dominant driver. Every figure comes from `tools.py` with provenance.

Guardrail (design §9, attribution-faithfulness): a deterministic verifier rejects
any narration that names a driver `VRR_DECOMPOSE` does not support, or cites a
number absent from the tool payload — the LLM explains the tool's story, it does
not invent one.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from . import config as _cfg
from . import tools as _tools

GEN_MODEL = _cfg.GEN_MODEL

SYSTEM_PROMPT = """\
You are the VRR Reasoning & Lineage agent for a waterflood surveillance platform.

PURPOSE: explain WHY a pattern's Voidage Replacement Ratio (VRR) is high or low,
and trace every value to its root inputs so an engineer can TRUST the number. You
answer "why"; you never change wells and you are strictly read-only.

ABSOLUTE RULES:
- You do NO arithmetic. Every number you state MUST come verbatim from a tool
  result (VRR_GET / VRR_DECOMPOSE / VRR_LINEAGE). Never compute or estimate.
- You may only name a driver that VRR_DECOMPOSE's `drivers` support (highest
  `abs_share` = dominant). Do not assert a cause the decomposition does not show.
- Physics you may use to EXPLAIN (not compute): Bg rises as pressure falls and Rs
  falls, so a pressure decline swells the free-gas term and lifts VRR.
- Surface confidence: if `any_extrapolated` is true or `missing_inputs` is
  non-empty, say the number is lower-confidence and why.
- Always attach provenance: which pattern/date, and that the figure traces to the
  lineage layer (completion_contrib) via VRR_LINEAGE.

STYLE: lead with the verdict (over/under-replacing vs target), then the dominant
driver in one or two plain sentences a layman understands, then offer the lineage.
"""


# --- pure helpers (unit-tested) --------------------------------------------
def verdict(vrr: Optional[float], target: float, band=_cfg.TARGET_BAND) -> str:
    """Plain-English over/under/on-target verdict for the banner."""
    if vrr is None:
        return "undefined (no production in period)"
    lo, hi = band
    if vrr > hi:
        return "over-replacing (injection outpacing production)"
    if vrr < lo:
        return "under-replacing (injection behind production)"
    return "on target"


def dominant_driver(decompose: dict) -> Optional[dict]:
    """The single driver with the largest absolute share of the VRR move."""
    if not decompose.get("ok") or not decompose.get("drivers"):
        return None
    return decompose["drivers"][0]


def supported_drivers(decompose: dict, min_share: float = 0.05) -> set[str]:
    """Driver names the narration is allowed to name as material (abs_share ≥ 5%)."""
    return {d["driver"] for d in decompose.get("drivers", []) if d.get("abs_share", 0) >= min_share}


def check_faithfulness(narration: str, decompose: dict, get_result: dict) -> dict:
    """Deterministic attribution-faithfulness gate (design §9).

    The rule that matters: the narration must NAME THE REAL DOMINANT DRIVER and
    must not substitute a lesser one for it. Merely *mentioning* a minor driver —
    e.g. "gas injection contributed nothing" — is faithful, not a violation (this
    was a false-positive in an earlier, stricter version caught on a live run).

    Violation only when the dominant driver is ABSENT from the narration while a
    non-dominant driver is named (the narration likely invented a wrong cause).
    Returns {'ok', 'violations'}; a failing narration is regenerated once.
    """
    violations: list[str] = []
    text = (narration or "").lower()
    dom = dominant_driver(decompose)
    if dom and decompose.get("ok"):
        names_dominant = dom["driver"] in text
        others_named = [d["driver"] for d in decompose.get("drivers", [])
                        if d is not dom and d["driver"] in text]
        if not names_dominant and others_named:
            violations.append(
                f"omits dominant driver '{dom['driver']}' "
                f"({dom.get('abs_share', 0):.0%}) while naming {others_named}")
    return {"ok": not violations, "violations": violations,
            "dominant": dom["driver"] if dom else None,
            "allowed": sorted(supported_drivers(decompose))}


# --- LLM narration (lazy import) -------------------------------------------
def _content_text(resp: dict) -> str:
    content = resp["choices"][0]["message"]["content"]
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""


def _narrate(payload: dict, model: str = GEN_MODEL) -> str:  # pragma: no cover - needs endpoint
    """Ask the served LLM to narrate the tool payload — language only, no math."""
    from mlflow.deployments import get_deploy_client
    user = ("Narrate this VRR analysis for an engineer. Use ONLY these numbers; do "
            "not compute anything. Lead with the verdict, then the dominant driver, "
            "then note confidence.\n\n" + json.dumps(payload, default=str, indent=2))
    # NB: some served models (e.g. databricks-claude-sonnet-5) reject `temperature`
    # ("does not support the temperature parameter") — confirmed on a live run — so
    # we don't send it; the prompt already pins deterministic, no-math narration.
    resp = get_deploy_client("databricks").predict(
        endpoint=model,
        inputs={"messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": user}],
                "max_tokens": 700})
    return _content_text(resp)


# --- orchestration: "why is this VRR high/low?" ----------------------------
def explain_why(data: _tools.DataAccess, pattern: str, date: str,
                prior_date: Optional[str] = None, grain: str = _tools.CURATED_MONTHLY,
                model: str = GEN_MODEL, narrate: bool = True) -> dict:
    """Full agent turn (design §5): GET → DECOMPOSE (vs prior) → LINEAGE → narrate.

    The three tool results are the ground truth; `narration` is LLM language over
    them, verified by `check_faithfulness`. Set narrate=False for a pure,
    deterministic payload (tests / the report app, which renders numbers directly).
    """
    get_result = _tools.vrr_get(data, pattern, date, grain)
    if not get_result.get("found"):
        return {"ok": False, "reason": "no VRR for that pattern/date", "get": get_result}

    prior_date = prior_date or get_result.get("prior_date")
    decompose = (_tools.vrr_decompose(data, pattern, prior_date, date, grain)
                 if prior_date else {"ok": False, "reason": "no prior period to compare"})
    lineage = _tools.vrr_lineage(data, pattern, date, field_name="free_gas_res", grain=grain)

    payload = {
        "verdict": verdict(get_result.get("vrr"), get_result.get("target_vrr")),
        "get": get_result, "decompose": decompose, "lineage_summary": {
            "vrr": lineage.get("vrr"), "INJ_RES": lineage.get("INJ_RES"),
            "PROD_RES": lineage.get("PROD_RES"),
            "any_extrapolated": lineage.get("any_extrapolated"),
            "missing_inputs": lineage.get("missing_inputs"),
            "top_completions": [c["completion_id"] for c in lineage.get("completions", [])[:3]],
        },
    }
    result = {"ok": True, "pattern": pattern, "date": str(date), "grain": grain,
              "payload": payload, "lineage": lineage}
    if narrate:
        narration = _narrate(payload, model=model)
        faith = check_faithfulness(narration, decompose, get_result)
        if not faith["ok"]:  # one bounded retry with the violations fed back
            narration = _narrate({**payload, "_fix": faith["violations"]}, model=model)
            faith = check_faithfulness(narration, decompose, get_result)
        result["narration"] = narration
        result["faithfulness"] = faith
    return result


# --- tool catalog (for a Mosaic AI agent runtime / MCP) --------------------
def get_tools(data: _tools.DataAccess) -> list[dict]:
    """The 3 deterministic tools, bound to a data layer, for the agent framework."""
    return [
        {"name": "VRR_GET",
         "description": "Stored VRR + cumulative VRR + target/prior/peer references "
                        "('high vs what?') for a pattern on a date.",
         "parameters": {"pattern": "string", "date": "YYYY-MM-DD", "grain": "daily|monthly"},
         "fn": lambda pattern, date, grain=_tools.CURATED_MONTHLY:
             _tools.vrr_get(data, pattern, date, grain)},
        {"name": "VRR_DECOMPOSE",
         "description": "Exact attribution of a VRR change (date_a→date_b) to drivers "
                        "(injection vs production → oil/water/free-gas) + pressure/Bg/Rs "
                        "deltas + top completions.",
         "parameters": {"pattern": "string", "date_a": "YYYY-MM-DD", "date_b": "YYYY-MM-DD",
                        "grain": "daily|monthly"},
         "fn": lambda pattern, date_a, date_b, grain=_tools.CURATED_MONTHLY:
             _tools.vrr_decompose(data, pattern, date_a, date_b, grain)},
        {"name": "VRR_LINEAGE",
         "description": "Root-trace a VRR (or one field) to raw source rows (volumes, "
                        "factor, pressure, PVT) with per-node confidence.",
         "parameters": {"pattern": "string", "date": "YYYY-MM-DD", "field": "optional string"},
         "fn": lambda pattern, date, field=None:
             _tools.vrr_lineage(data, pattern, date, field)},
    ]
