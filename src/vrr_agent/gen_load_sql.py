"""Generate a self-contained SQL load for the VRR synthetic example.

Runs the VERIFIED physics.py locally over the same profiles as 02_seed_raw.py and
emits CREATE + INSERT SQL for raw AND curated (completion_contrib +
pattern_vrr_daily/_monthly). This lets the whole module land in cdp_dev via the SQL
warehouse alone — no PySpark cluster — while the curated numbers come from the same
single-source-of-truth physics the tests cover.

    python -m src.vrr_agent.gen_load_sql > /tmp/vrr_load.sql

(For real data, use the 03/04 PySpark notebooks on a cluster instead.)
"""
from __future__ import annotations

import calendar
import datetime as dt
import sys

from . import physics as ph
from . import tools as T

RUN_ID = "seed-2026-07-18"

PATTERNS = {"PUNITY": "UNITY", "PDELTA": "DELTA"}
FACTORS = {  # (completion, pattern, factor)
    ("PROD_WELL_001", "PUNITY"): 0.5, ("PROD_WELL_002", "PUNITY"): 0.5,
    ("PROD_WELL_003", "PUNITY"): 0.5, ("INJ_WELL_001", "PUNITY"): 1.0,
    ("PROD_WELL_010", "PDELTA"): 0.5, ("INJ_WELL_010", "PDELTA"): 1.0,
}
PROD = {  # completion -> (oil_stb, water_stb, gas_kscf) per day
    "PROD_WELL_001": (300.0, 200.0, 400.0), "PROD_WELL_002": (280.0, 220.0, 380.0),
    "PROD_WELL_003": (260.0, 240.0, 900.0), "PROD_WELL_010": (290.0, 210.0, 410.0),
}
INJ = {"INJ_WELL_001": (1500.0, 0.0), "INJ_WELL_010": (1450.0, 0.0)}
PROD_PATTERN = {"PROD_WELL_001": "PUNITY", "PROD_WELL_002": "PUNITY",
                "PROD_WELL_003": "PUNITY", "PROD_WELL_010": "PDELTA"}
INJ_PATTERN = {"INJ_WELL_001": "PUNITY", "INJ_WELL_010": "PDELTA"}
PRESSURE = {  # (pattern, month) -> psi
    ("PUNITY", 3): 3000.0, ("PUNITY", 4): 2780.0,
    ("PDELTA", 3): 2950.0, ("PDELTA", 4): 2930.0,
}
# two PVT points per completion (Bg ≈ 1/P: lower pressure -> higher Bg)
PVT_PTS = [ph.PVTPoint(2700, bo=1.25, bw=1.02, bg=0.00090, rs=520, bw_inj=1.0, bg_inj=0.0006),
           ph.PVTPoint(3100, bo=1.28, bw=1.01, bg=0.00078, rs=620, bw_inj=1.0, bg_inj=0.0006)]
MONTHS = [(2026, 3), (2026, 4)]


def _days(y, m):
    return [dt.date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def _num(x):
    return "NULL" if x is None else repr(round(float(x), 8))


def _contrib_rows():
    rows = []
    for (y, m) in MONTHS:
        for d in _days(y, m):
            for cid, (o, w, g) in PROD.items():
                pat = PROD_PATTERN[cid]
                pr = ph.pvt_lookup(PVT_PTS, PRESSURE[(pat, m)])
                t = ph.completion_contribution(factor=FACTORS[(cid, pat)], oil=o, water=w,
                                               gas=g, water_inj=0, gas_inj=0, pvt=pr.props,
                                               is_producer=True)
                rows.append(_row(pat, cid, d, FACTORS[(cid, pat)], o, w, g, 0, 0, pr, t))
            for cid, (wi, gi) in INJ.items():
                pat = INJ_PATTERN[cid]
                pr = ph.pvt_lookup(PVT_PTS, PRESSURE[(pat, m)])
                t = ph.completion_contribution(factor=FACTORS[(cid, pat)], oil=0, water=0,
                                               gas=0, water_inj=wi, gas_inj=gi, pvt=pr.props,
                                               is_producer=False)
                rows.append(_row(pat, cid, d, FACTORS[(cid, pat)], 0, 0, 0, wi, gi, pr, t))
    return rows


def _row(pat, cid, d, f, o, w, g, wi, gi, pr, t):  # returns a dict for reuse in aggregation
    p = pr.props
    return {"pattern_id": pat, "completion_id": cid, "vrr_date": str(d), "factor": f,
            "oil": o, "water": w, "gas": g, "water_inj": wi, "gas_inj": gi,
            "pressure_psi": PRESSURE_lookup(pat, d), "bo": p["bo"], "bw": p["bw"],
            "bg": p["bg"], "bw_inj": p["bw_inj"], "bg_inj": p["bg_inj"], "rs": p["rs"],
            "rv": p["rv"], "pvt_method": pr.method,
            "pvt_bracket_lo": pr.bracket[0] if pr.bracket else None,
            "pvt_bracket_hi": pr.bracket[1] if pr.bracket else None, "missing_input": None,
            "oil_res": t.oil_res, "water_res": t.water_res, "free_gas_res": t.free_gas_res,
            "water_inj_res": t.water_inj_res, "gas_inj_res": t.gas_inj_res, "run_id": RUN_ID}


def PRESSURE_lookup(pat, d):
    return PRESSURE[(pat, d.month)]


CONTRIB_COLS = ["pattern_id", "completion_id", "vrr_date", "factor", "oil", "water", "gas",
                "water_inj", "gas_inj", "pressure_psi", "bo", "bw", "bg", "bw_inj", "bg_inj",
                "rs", "rv", "pvt_method", "pvt_bracket_lo", "pvt_bracket_hi", "missing_input",
                "oil_res", "water_res", "free_gas_res", "water_inj_res", "gas_inj_res", "run_id"]


def _val(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return _num(v)


def _insert(table, cols, rows, cast_date=None):
    if not rows:
        return ""
    lines = []
    for r in rows:
        vals = []
        for c in cols:
            v = r.get(c)
            if cast_date and c in cast_date and v is not None:
                vals.append(f"DATE'{v}'")
            else:
                vals.append(_val(v))
        lines.append("(" + ", ".join(vals) + ")")
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n" + ",\n".join(lines) + ";\n"


def _vrr_aggregates(contrib):
    daily, monthly = [], []
    def agg(rows, date_key):
        groups = {}
        for r in rows:
            key = (r["pattern_id"], date_key(r["vrr_date"]))
            groups.setdefault(key, []).append(r)
        out = []
        for (pat, d), rs in sorted(groups.items()):
            prod = sum(r["oil_res"] + r["water_res"] + r["free_gas_res"] for r in rs)
            inj = sum(r["water_inj_res"] + r["gas_inj_res"] for r in rs)
            out.append({"pattern_id": pat, "pattern_name": PATTERNS[pat], "vrr_date": d,
                        "prod_res_bbl": prod, "inj_res_bbl": inj,
                        "vrr": (inj / prod) if prod else None,
                        "n_completions": len({r["completion_id"] for r in rs}),
                        "any_extrapolated": any(r["pvt_method"] == "extrapolated" for r in rs),
                        "run_id": RUN_ID})
        # cumulative per pattern
        for pat in PATTERNS:
            cp = ci = 0.0
            for row in [x for x in out if x["pattern_id"] == pat]:
                cp += row["prod_res_bbl"]; ci += row["inj_res_bbl"]
                row["cum_prod_res_bbl"], row["cum_inj_res_bbl"] = cp, ci
                row["cum_vrr"] = (ci / cp) if cp else None
        return out
    daily = agg(contrib, lambda d: d)
    monthly = agg(contrib, lambda d: d[:7] + "-01")
    return daily, monthly


VRR_COLS = ["pattern_id", "pattern_name", "vrr_date", "prod_res_bbl", "inj_res_bbl", "vrr",
            "cum_prod_res_bbl", "cum_inj_res_bbl", "cum_vrr", "n_completions",
            "any_extrapolated", "run_id"]


def _raw_rows():
    """The source-shaped raw tables (what 02_seed_raw.py writes) — so curated
    genuinely derives from raw, not just from the generator."""
    vols, facs, prs, pvt = [], [], [], []
    for (cid, pat), f in FACTORS.items():
        facs.append({"ID_COMPLETION": cid, "ID_PATTERN": pat, "FACTOR": f,
                     "EFFECT_DATE": "2024-01-01"})
    for (pat, m), p in PRESSURE.items():
        prs.append({"ID_PATTERN": pat, "DATE": f"2026-{m:02d}-01", "PRESSURE": p})
    for cid in list(PROD) + list(INJ):
        for pt in PVT_PTS:
            pvt.append({"ID_COMPLETION": cid, "TEST_DATE": "2025-01-01",
                        "PRESSURE": pt.pressure_psi, "OIL_FORMATION_VOLUME_FACTOR": pt.bo,
                        "WATER_FORMATION_VOLUME_FACTOR": pt.bw, "GAS_FORMATION_VOLUME_FACTOR": pt.bg,
                        "INJECTED_WATER_FORMATION_VOLUME_FACTOR": pt.bw_inj,
                        "INJECTED_GAS_FORMATION_VOLUME_FACTOR": pt.bg_inj,
                        "SOLUTION_GAS_OIL_RATIO": pt.rs, "VOLATIZED_OIL_GAS_RATIO": pt.rv})
    for (y, m) in MONTHS:
        for d in _days(y, m):
            for cid, (o, w, g) in PROD.items():
                vols.append({"EMSDB_PROD_COMPLETION_ID": cid, "PROD_DATE": str(d),
                             "ALLOC_OIL_VOL_STB": o, "ALLOC_WATER_VOL_STB": w,
                             "ALLOC_WATER_INJ_VOL_STB": 0.0, "ALLOC_GAS_VOL_KSCF": g,
                             "ALLOC_GAS_INJ_VOL_KSCF": 0.0})
            for cid, (wi, gi) in INJ.items():
                vols.append({"EMSDB_PROD_COMPLETION_ID": cid, "PROD_DATE": str(d),
                             "ALLOC_OIL_VOL_STB": 0.0, "ALLOC_WATER_VOL_STB": 0.0,
                             "ALLOC_WATER_INJ_VOL_STB": wi, "ALLOC_GAS_VOL_KSCF": 0.0,
                             "ALLOC_GAS_INJ_VOL_KSCF": gi})
    return vols, facs, prs, pvt


RAW_VOL_COLS = ["EMSDB_PROD_COMPLETION_ID", "PROD_DATE", "ALLOC_OIL_VOL_STB",
                "ALLOC_WATER_VOL_STB", "ALLOC_WATER_INJ_VOL_STB", "ALLOC_GAS_VOL_KSCF",
                "ALLOC_GAS_INJ_VOL_KSCF"]
RAW_FAC_COLS = ["ID_COMPLETION", "ID_PATTERN", "FACTOR", "EFFECT_DATE"]
RAW_PRS_COLS = ["ID_PATTERN", "DATE", "PRESSURE"]
RAW_PVT_COLS = ["ID_COMPLETION", "TEST_DATE", "PRESSURE", "OIL_FORMATION_VOLUME_FACTOR",
                "WATER_FORMATION_VOLUME_FACTOR", "GAS_FORMATION_VOLUME_FACTOR",
                "INJECTED_WATER_FORMATION_VOLUME_FACTOR", "INJECTED_GAS_FORMATION_VOLUME_FACTOR",
                "SOLUTION_GAS_OIL_RATIO", "VOLATIZED_OIL_GAS_RATIO"]


def main(catalog="cdp_dev"):
    contrib = _contrib_rows()
    daily, monthly = _vrr_aggregates(contrib)
    vols, facs, prs, pvt = _raw_rows()
    out = [f"-- VRR synthetic load (generated from physics.py; run_id={RUN_ID})",
           f"USE CATALOG {catalog};", ""]
    # raw (source-shaped)
    raw_pat = [{"ID_PATTERN": k, "PATTERN_NAME": v} for k, v in PATTERNS.items()]
    out.append(_insert(f"{catalog}.vrr_raw.pattern", ["ID_PATTERN", "PATTERN_NAME"], raw_pat))
    out.append(_insert(f"{catalog}.vrr_raw.production_volumes_daily_oilfield", RAW_VOL_COLS,
                       vols, cast_date={"PROD_DATE"}))
    out.append(_insert(f"{catalog}.vrr_raw.pattern_contribution_factor", RAW_FAC_COLS,
                       facs, cast_date={"EFFECT_DATE"}))
    out.append(_insert(f"{catalog}.vrr_raw.pattern_pressure", RAW_PRS_COLS, prs,
                       cast_date={"DATE"}))
    out.append(_insert(f"{catalog}.vrr_raw.completion_pvt_characteristics", RAW_PVT_COLS,
                       pvt, cast_date={"TEST_DATE"}))
    out.append(f"INSERT INTO {catalog}.vrr_curated.pattern_target "
               "(pattern_id, target_vrr, source) VALUES ('PUNITY', 1.0, 'RM_2026');\n")
    # curated
    out.append(_insert(f"{catalog}.vrr_curated.completion_contrib", CONTRIB_COLS, contrib,
                       cast_date={"vrr_date"}))
    out.append(_insert(f"{catalog}.vrr_curated.pattern_vrr_daily", VRR_COLS, daily,
                       cast_date={"vrr_date"}))
    out.append(_insert(f"{catalog}.vrr_curated.pattern_vrr_monthly", VRR_COLS, monthly,
                       cast_date={"vrr_date"}))
    return "\n".join(out)


if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "cdp_dev"))
