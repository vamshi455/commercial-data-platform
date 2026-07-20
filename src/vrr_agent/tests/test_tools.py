"""Unit tests for the deterministic VRR tools + agent helpers — off-cluster.

Builds an in-memory dataset that mirrors ``02_seed_raw.py`` (pattern UNITY, March
vs April, a ~220 psi pressure decline, PROD_WELL_003 the gassy well) by running
the real ``physics`` functions, then exercises VRR_GET / VRR_DECOMPOSE /
VRR_LINEAGE and the faithfulness gate.
"""
import math

import pytest

from src.vrr_agent import physics as ph
from src.vrr_agent import tools as T
from src.vrr_agent import agent as A


PVT_PTS = [
    ph.PVTPoint(pressure_psi=2700, bo=1.25, bw=1.02, bg=0.00090, rs=520, bw_inj=1.0, bg_inj=0.0006),
    ph.PVTPoint(pressure_psi=3100, bo=1.28, bw=1.01, bg=0.00078, rs=620, bw_inj=1.0, bg_inj=0.0006),
]
PROD = {"PROD_WELL_001": (300, 200, 400), "PROD_WELL_002": (280, 220, 380),
        "PROD_WELL_003": (260, 240, 900)}                      # gassy driver
INJ = {"INJ_WELL_001": (1500, 0)}
DAYS = {"2026-03": 31, "2026-04": 30}
PRESSURE = {"2026-03": 3000.0, "2026-04": 2780.0}              # −220 psi


def _contrib_row(pattern, cid, date, factor, o, w, g, wi, gi, pressure, producer):
    pr = ph.pvt_lookup(PVT_PTS, pressure)
    t = ph.completion_contribution(factor=factor, oil=o, water=w, gas=g,
                                   water_inj=wi, gas_inj=gi, pvt=pr.props, is_producer=producer)
    p = pr.props
    return {"pattern_id": pattern, "completion_id": cid, "vrr_date": date, "factor": factor,
            "oil": o, "water": w, "gas": g, "water_inj": wi, "gas_inj": gi,
            "pressure_psi": pressure, "bo": p["bo"], "bw": p["bw"], "bg": p["bg"],
            "bw_inj": p["bw_inj"], "bg_inj": p["bg_inj"], "rs": p["rs"], "rv": p["rv"],
            "pvt_method": pr.method, "pvt_bracket_lo": pr.bracket[0] if pr.bracket else None,
            "pvt_bracket_hi": pr.bracket[1] if pr.bracket else None, "missing_input": None,
            "oil_res": t.oil_res, "water_res": t.water_res, "free_gas_res": t.free_gas_res,
            "water_inj_res": t.water_inj_res, "gas_inj_res": t.gas_inj_res, "run_id": "test"}


def _build():
    contrib, monthly = [], []
    for ym, ndays in DAYS.items():
        pressure = PRESSURE[ym]
        for day in range(1, ndays + 1):
            d = f"{ym}-{day:02d}"
            for cid, (o, w, g) in PROD.items():
                contrib.append(_contrib_row("PUNITY", cid, d, 0.5, o, w, g, 0, 0, pressure, True))
            for cid, (wi, gi) in INJ.items():
                contrib.append(_contrib_row("PUNITY", cid, d, 1.0, 0, 0, 0, wi, gi, pressure, False))
        # monthly aggregate row (what pattern_vrr_monthly would hold)
        month_rows = T.aggregate_contrib_monthly(
            [r for r in contrib if r["vrr_date"].startswith(ym)], "PUNITY", f"{ym}-01")
        prod = sum(r["oil_res"] + r["water_res"] + r["free_gas_res"] for r in month_rows)
        inj = sum(r["water_inj_res"] + r["gas_inj_res"] for r in month_rows)
        monthly.append({"pattern_id": "PUNITY", "pattern_name": "UNITY", "vrr_date": f"{ym}-01",
                        "prod_res_bbl": prod, "inj_res_bbl": inj, "vrr": inj / prod,
                        "cum_vrr": inj / prod, "any_extrapolated": False, "run_id": "test"})
    return T.InMemoryData(vrr_monthly=monthly, contrib=contrib, targets={"PUNITY": 1.0})


DATA = _build()


def test_vrr_get_returns_target_and_prior():
    g = T.vrr_get(DATA, "PUNITY", "2026-04-01")
    assert g["found"]
    assert g["target_vrr"] == 1.0 and g["target_is_default"] is False
    assert g["prior_date"] == "2026-03-01"
    assert g["vrr"] > 0


def test_decompose_is_exact_and_additive():
    """The whole point of LMDI: driver contributions sum EXACTLY to Δln(VRR)."""
    d = T.vrr_decompose(DATA, "PUNITY", "2026-03-01", "2026-04-01")  # monthly
    assert d["ok"]
    total = sum(x["contribution"] for x in d["drivers"])
    assert total == pytest.approx(d["dln_vrr"], abs=1e-9)
    assert sum(x["abs_share"] for x in d["drivers"]) == pytest.approx(1.0, abs=1e-9)


def test_decompose_pressure_delta_and_top_completion():
    # Daily grain (a March day vs an April day) isolates the pressure/free-gas
    # driver from the calendar-days confounder in monthly sums.
    d = T.vrr_decompose(DATA, "PUNITY", "2026-03-15", "2026-04-15", grain=T.CURATED_DAILY)
    assert d["ok"]
    assert d["pressure"]["delta_psi"] == pytest.approx(-220.0, abs=1e-6)
    # free gas is the dominant driver of the move
    assert d["drivers"][0]["driver"] == "free gas"
    # PROD_WELL_003 (the gassy well) drives the free-gas change
    assert d["top_completions"][0]["completion_id"] == "PROD_WELL_003"


def test_lineage_traces_to_root_with_confidence():
    lin = T.vrr_lineage(DATA, "PUNITY", "2026-04-01", field_name="free_gas_res")
    assert lin["found"]
    assert lin["vrr"] == pytest.approx(lin["INJ_RES"] / lin["PROD_RES"])
    node = lin["completions"][0]
    assert node["completion_id"] == "PROD_WELL_003"          # sorted by |free_gas_res|
    assert node["roots"]["pvt"]["method"] == "interpolated"  # in-range ⇒ trusted
    assert node["roots"]["pressure"]["source"] == "vrr_raw.pattern_pressure"
    assert lin["any_extrapolated"] is False


def test_faithfulness_flags_wrong_driver():
    d = T.vrr_decompose(DATA, "PUNITY", "2026-03-15", "2026-04-15", grain=T.CURATED_DAILY)
    good = "VRR moved mainly via the free gas term as pattern pressure fell."
    bad = "The change was driven by water injection."   # immaterial / wrong
    assert A.check_faithfulness(good, d, {})["ok"] is True
    assert A.check_faithfulness(bad, d, {})["ok"] is False


def test_tool_specs_are_wellformed():
    names = {s["function"]["name"] for s in T.TOOL_SPECS}
    assert names == {"VRR_LIST_PATTERNS", "VRR_OVERVIEW", "VRR_GET", "VRR_DECOMPOSE",
                     "VRR_LINEAGE", "VRR_IMPACT", "VRR_LINEAGE_GRAPH", "VRR_EXPLAIN_CALC"}
    for s in T.TOOL_SPECS:  # OpenAI function-calling shape
        assert s["type"] == "function"
        assert s["function"]["parameters"]["type"] == "object"


def test_list_patterns_discovery():
    r = T.call_tool(DATA, "VRR_LIST_PATTERNS", {})
    assert r["count"] == 1                      # only PUNITY has monthly rows in DATA
    p = r["patterns"][0]
    assert p["pattern_id"] == "PUNITY" and p["pattern_name"] == "UNITY"
    assert p["first_date"] == "2026-03-01" and p["last_date"] == "2026-04-01"
    assert p["n_periods"] == 2


def test_overview_ranks_by_drift():
    r = T.call_tool(DATA, "VRR_OVERVIEW", {})   # latest per pattern
    assert r["count"] == 1
    row = r["patterns"][0]
    assert row["pattern_id"] == "PUNITY" and row["verdict"] == "on-target"  # ~1.07 in [0.9,1.1]
    assert row["vrr_date"] == "2026-04-01"      # latest
    assert row["drift"] == pytest.approx(abs(row["vrr"] - 1.0))


def test_resolve_pattern_by_name_or_id():
    assert DATA.resolve_pattern("UNITY") == "PUNITY"   # name -> id
    assert DATA.resolve_pattern("punity") == "PUNITY"  # case-insensitive id
    assert DATA.resolve_pattern("ZZZ") == "ZZZ"        # unknown passes through
    # VRR_GET works when the user says the pattern NAME
    assert T.call_tool(DATA, "VRR_GET", {"pattern": "UNITY", "date": "2026-04-01"})["found"]


def test_call_tool_dispatch():
    g = T.call_tool(DATA, "VRR_GET", {"pattern": "PUNITY", "date": "2026-04-01"})
    assert g["found"] and g["vrr"] > 0
    d = T.call_tool(DATA, "VRR_DECOMPOSE",
                    {"pattern": "PUNITY", "date_a": "2026-03-15", "date_b": "2026-04-15",
                     "grain": "daily"})
    assert d["ok"] and d["drivers"][0]["driver"] == "free gas"
    lin = T.call_tool(DATA, "VRR_LINEAGE", {"pattern": "PUNITY", "date": "2026-04-01"})
    assert lin["found"]
    assert T.call_tool(DATA, "NOPE", {})["error"]


def test_impact_forward_from_pressure():
    """What-if: which VRRs depend on UNITY's April pressure? -> April daily+monthly."""
    r = T.call_tool(DATA, "VRR_IMPACT",
                    {"input_type": "pressure", "pattern": "UNITY", "date": "2026-04-15"})
    assert r["ok"]
    nodes = {v["vrr_node"] for v in r["impacted_vrrs"]}
    assert "vrr:PUNITY:daily:2026-04-15" in nodes        # the day itself
    assert "vrr:PUNITY:monthly:2026-04-01" in nodes      # the month it rolls into
    # a March pressure must NOT impact April VRRs
    assert all("2026-03" not in n for n in nodes)


def test_impact_from_pvt_carries_confidence():
    r = T.call_tool(DATA, "VRR_IMPACT", {"input_type": "pvt", "completion": "PROD_WELL_003"})
    assert r["ok"] and r["impacted_count"] > 0
    assert any(v["edge_confidence"] == "interpolated" for v in r["impacted_vrrs"])


def test_lineage_graph_traces_vrr_to_roots():
    r = T.call_tool(DATA, "VRR_LINEAGE_GRAPH",
                    {"pattern": "UNITY", "date": "2026-04-15", "grain": "daily"})
    assert r["ok"] and r["vrr_node"] == "vrr:PUNITY:daily:2026-04-15"
    types = {x["node_type"] for x in r["roots"]}
    assert types == {"factor", "volume", "pressure", "pvt"}
    # the pressure root behind the April daily VRR is the April pressure node
    assert any(x["root_node"] == "pressure:PUNITY:2026-04-15" for x in r["roots"])


def test_explain_calc_returns_logged_sql():
    d = T.InMemoryData(transform_log=[
        {"aggregation_type": "Monthly", "sql_text": "INSERT ... pattern_vrr_monthly ...",
         "run_id": "r1", "log_ts": "2026-07-19T00:00:00", "asset_name": "CDP_VRR", "uom": "OilField"},
        {"aggregation_type": "Monthly", "sql_text": "INSERT ... NEWER ...",
         "run_id": "r2", "log_ts": "2026-07-19T06:00:00", "asset_name": "CDP_VRR", "uom": "OilField"},
    ])
    r = T.call_tool(d, "VRR_EXPLAIN_CALC", {"grain": "monthly"})
    assert r["found"] and r["run_id"] == "r2"        # latest wins
    assert "NEWER" in r["sql_text"]
    assert T.call_tool(d, "VRR_EXPLAIN_CALC", {"grain": "daily"})["found"] is False


def test_explain_why_payload_without_llm():
    """narrate=False gives a fully deterministic payload (no endpoint needed)."""
    out = A.explain_why(DATA, "PUNITY", "2026-04-01", narrate=False)
    assert out["ok"]
    assert out["payload"]["decompose"]["ok"]
    assert "narration" not in out
