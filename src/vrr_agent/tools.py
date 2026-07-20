"""Deterministic VRR tools — every number the agent shows comes from here.

The three reasoning tools of design §4, implemented as **pure Python over an
injectable data layer** (``DataAccess``). On a cluster the data layer is Spark
SQL over ``vrr_curated``; in a test it is in-memory rows — so the exact same tool
logic unit-tests off-cluster (matching the CDP's ``run_sql`` placeholder pattern).

  - ``vrr_get``       — stored VRR + cum VRR + "high vs what?" refs (target/prior/peer)
  - ``vrr_decompose`` — exact log-mean (LMDI) attribution of a VRR change to drivers
  - ``vrr_lineage``   — root-trace one value down to the raw source rows + confidence

The LLM calls these and narrates the result; it never computes. Every return
carries provenance (source table + row keys + run_id).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from . import config as _cfg

# Production and injection term columns on completion_contrib (the lineage layer).
PROD_TERMS = ("oil_res", "water_res", "free_gas_res")
INJ_TERMS = ("water_inj_res", "gas_inj_res")
_TERM_LABEL = {
    "oil_res": "oil", "water_res": "water", "free_gas_res": "free gas",
    "water_inj_res": "water injection", "gas_inj_res": "gas injection",
}
CURATED_DAILY, CURATED_MONTHLY = "daily", "monthly"


def log_mean(a: float, b: float) -> float:
    """Logarithmic mean L(a,b) = (b-a)/ln(b/a); L(a,a)=a. Requires a,b > 0.

    The identity ``L(a,b)·ln(b/a) = b-a`` is what makes the LMDI decomposition
    below exact and additive.
    """
    if a <= 0 or b <= 0:
        raise ValueError(f"log_mean requires positive args, got {a},{b}")
    if a == b:
        return a
    return (b - a) / (math.log(b) - math.log(a))


# --------------------------------------------------------------------------- #
# Data layer — injectable so tools are pure & testable.
# --------------------------------------------------------------------------- #
class DataAccess(Protocol):
    def resolve_pattern(self, pattern: str) -> str: ...
    def list_patterns(self) -> list[dict]: ...
    def overview(self, date: Optional[str], grain: str) -> list[dict]: ...
    def vrr_row(self, pattern: str, date: str, grain: str) -> Optional[dict]: ...
    def peer_vrr(self, pattern: str, date: str, grain: str) -> list[dict]: ...
    def prior_vrr(self, pattern: str, date: str, grain: str) -> Optional[dict]: ...
    def target_vrr(self, pattern: str) -> Optional[float]: ...
    def contrib_rows(self, pattern: str, date: str, grain: str) -> list[dict]: ...
    def impact(self, root_node_id: str) -> list[dict]: ...      # forward: root -> VRRs
    def trace(self, vrr_node_id: str) -> list[dict]: ...        # backward: VRR -> roots
    def latest_transform_sql(self, grain: str, asset: Optional[str]) -> Optional[dict]: ...


# Aggregate daily contrib rows to one row per completion for a monthly period, so
# the decompose/lineage tools work on the same grain as pattern_vrr_monthly. The
# *_res terms sum; pressure/PVT are averaged; PVT method is worst-case (any
# extrapolated -> extrapolated), so confidence never looks better than it is.
_SUM_COLS = ("oil", "water", "gas", "water_inj", "gas_inj",
             "oil_res", "water_res", "free_gas_res", "water_inj_res", "gas_inj_res")
_AVG_COLS = ("factor", "pressure_psi", "bo", "bw", "bg", "bw_inj", "bg_inj", "rs", "rv")


def aggregate_contrib_monthly(rows: list[dict], pattern: str, month_start: str) -> list[dict]:
    by_comp: dict[str, list[dict]] = {}
    for r in rows:
        by_comp.setdefault(r["completion_id"], []).append(r)
    out = []
    for cid, rs in by_comp.items():
        agg = {"pattern_id": pattern, "completion_id": cid, "vrr_date": month_start}
        for c in _SUM_COLS:
            agg[c] = sum((r.get(c) or 0.0) for r in rs)
        for c in _AVG_COLS:
            vals = [r.get(c) for r in rs if r.get(c) is not None]
            agg[c] = (sum(vals) / len(vals)) if vals else None
        methods = {r.get("pvt_method") for r in rs}
        agg["pvt_method"] = "extrapolated" if "extrapolated" in methods else (
            "interpolated" if "interpolated" in methods else "exact")
        agg["pvt_bracket_lo"] = min((r.get("pvt_bracket_lo") for r in rs
                                     if r.get("pvt_bracket_lo") is not None), default=None)
        agg["pvt_bracket_hi"] = max((r.get("pvt_bracket_hi") for r in rs
                                     if r.get("pvt_bracket_hi") is not None), default=None)
        agg["missing_input"] = next((r.get("missing_input") for r in rs if r.get("missing_input")), None)
        agg["run_id"] = next((r.get("run_id") for r in rs if r.get("run_id")), None)
        out.append(agg)
    return out


def _same_month(vrr_date, month_start: str) -> bool:
    return str(vrr_date)[:7] == str(month_start)[:7]


@dataclass
class InMemoryData:
    """Test/prototype data layer backed by plain dict rows."""
    vrr_daily: list[dict] = field(default_factory=list)
    vrr_monthly: list[dict] = field(default_factory=list)
    contrib: list[dict] = field(default_factory=list)
    targets: dict[str, float] = field(default_factory=dict)
    transform_log: list[dict] = field(default_factory=list)   # pattern_vrr_log rows

    def latest_transform_sql(self, grain, asset=None):
        agg = "Monthly" if grain == CURATED_MONTHLY else "Daily"
        rows = [r for r in self.transform_log if r.get("aggregation_type") == agg
                and (asset is None or r.get("asset_name") == asset)]
        return sorted(rows, key=lambda r: str(r.get("log_ts")))[-1] if rows else None

    def _vrr(self, grain):
        return self.vrr_monthly if grain == CURATED_MONTHLY else self.vrr_daily

    def resolve_pattern(self, pattern):
        p = (pattern or "").strip().lower()
        for r in self.vrr_monthly + self.vrr_daily:
            if p in (str(r.get("pattern_id", "")).lower(), str(r.get("pattern_name", "")).lower()):
                return r["pattern_id"]
        return pattern

    def list_patterns(self):
        by = {}
        for r in self.vrr_monthly:
            by.setdefault(r["pattern_id"], []).append(r)
        out = []
        for pid, rows in by.items():
            rows = sorted(rows, key=lambda r: str(r["vrr_date"]))
            out.append({"pattern_id": pid, "pattern_name": rows[-1].get("pattern_name"),
                        "n_periods": len(rows), "first_date": str(rows[0]["vrr_date"]),
                        "last_date": str(rows[-1]["vrr_date"]), "latest_vrr": rows[-1].get("vrr")})
        return sorted(out, key=lambda x: x["pattern_id"])

    def overview(self, date, grain):
        rows = self._vrr(grain)
        if date:
            return [r for r in rows if str(r["vrr_date"]) == str(date)]
        latest = {}
        for r in sorted(rows, key=lambda r: str(r["vrr_date"])):
            latest[r["pattern_id"]] = r      # last wins = latest date
        return list(latest.values())

    def vrr_row(self, pattern, date, grain):
        for r in self._vrr(grain):
            if r["pattern_id"] == pattern and str(r["vrr_date"]) == str(date):
                return r
        return None

    def peer_vrr(self, pattern, date, grain):
        return [r for r in self._vrr(grain)
                if r["pattern_id"] != pattern and str(r["vrr_date"]) == str(date)]

    def prior_vrr(self, pattern, date, grain):
        rows = sorted((r for r in self._vrr(grain) if r["pattern_id"] == pattern),
                      key=lambda r: str(r["vrr_date"]))
        prev = None
        for r in rows:
            if str(r["vrr_date"]) == str(date):
                return prev
            prev = r
        return None

    def target_vrr(self, pattern):
        return self.targets.get(pattern)

    def contrib_rows(self, pattern, date, grain=CURATED_MONTHLY):
        if grain == CURATED_MONTHLY:
            rows = [r for r in self.contrib
                    if r["pattern_id"] == pattern and _same_month(r["vrr_date"], date)]
            return aggregate_contrib_monthly(rows, pattern, str(date))
        return [r for r in self.contrib
                if r["pattern_id"] == pattern and str(r["vrr_date"]) == str(date)]

    def _vrr_of(self, pid, grain, date):
        for r in self._vrr(grain):
            if r["pattern_id"] == pid and str(r["vrr_date"]) == str(date):
                return r.get("vrr")
        return None

    def impact(self, root_node_id):
        """Forward: every VRR (daily+monthly) that derives from this raw-input node."""
        out, seen = [], set()
        for r in self.contrib:
            roots = _contrib_roots(r)
            hit = next((rel for rel, nid in roots.items() if nid == root_node_id), None)
            if not hit:
                continue
            d = str(r["vrr_date"])
            for grain, gdate in ((CURATED_DAILY, d), (CURATED_MONTHLY, d[:7] + "-01")):
                nid = vrr_node_id(r["pattern_id"], grain, gdate)
                if nid in seen:
                    continue
                seen.add(nid)
                out.append({"vrr_node": nid, "pattern_id": r["pattern_id"], "grain": grain,
                            "vrr_date": gdate, "vrr": self._vrr_of(r["pattern_id"], grain, gdate),
                            "via_completion": r["completion_id"],
                            "edge_confidence": r.get("pvt_method") if hit == "pvt" else None})
        return out

    def trace(self, vrr_node_id_str):
        """Backward: every raw-input root behind a VRR output node."""
        parts = vrr_node_id_str.split(":")           # vrr:{pid}:{grain}:{date}
        _, pid, grain, date = parts[0], parts[1], parts[2], parts[3]
        rows = [r for r in self.contrib if r["pattern_id"] == pid and (
            _same_month(r["vrr_date"], date) if grain == CURATED_MONTHLY
            else str(r["vrr_date"]) == date)]
        out, seen = [], set()
        for r in rows:
            for rel, nid in _contrib_roots(r).items():
                if nid in seen:
                    continue
                seen.add(nid)
                out.append({"root_node": nid, "node_type": rel, "via_completion": r["completion_id"],
                            "edge_rel": f"input:{rel}",
                            "confidence": r.get("pvt_method") if rel == "pvt" else None})
        return out


class SparkData:  # pragma: no cover - needs a cluster
    """Production data layer: Spark SQL over ``vrr_curated``."""

    def __init__(self, spark, cfg: Optional[_cfg.Config] = None):
        self.spark = spark
        self.cfg = cfg or _cfg.load_config()

    def _tbl(self, grain):
        return self.cfg.pattern_vrr_monthly if grain == CURATED_MONTHLY else self.cfg.pattern_vrr_daily

    def resolve_pattern(self, pattern):
        r = self.spark.sql(
            f"SELECT pattern_id FROM {self.cfg.pattern_vrr_monthly} "
            "WHERE lower(pattern_id)=lower(:p) OR lower(pattern_name)=lower(:p) LIMIT 1",
            args={"p": pattern}).collect()
        return r[0]["pattern_id"] if r else pattern

    def list_patterns(self):
        return [x.asDict() for x in self.spark.sql(
            f"SELECT pattern_id, max(pattern_name) pattern_name, count(*) n_periods, "
            "min(vrr_date) first_date, max(vrr_date) last_date, "
            f"max_by(vrr, vrr_date) latest_vrr FROM {self.cfg.pattern_vrr_monthly} "
            "GROUP BY pattern_id ORDER BY pattern_id").collect()]

    def overview(self, date, grain):
        if date:
            return [x.asDict() for x in self.spark.sql(
                f"SELECT * FROM {self._tbl(grain)} WHERE vrr_date=:d", args={"d": date}).collect()]
        return [x.asDict() for x in self.spark.sql(
            f"SELECT * FROM {self._tbl(grain)} QUALIFY row_number() OVER "
            "(PARTITION BY pattern_id ORDER BY vrr_date DESC)=1").collect()]

    def vrr_row(self, pattern, date, grain):
        r = self.spark.sql(
            f"SELECT * FROM {self._tbl(grain)} WHERE pattern_id=:p AND vrr_date=:d",
            args={"p": pattern, "d": date}).collect()
        return r[0].asDict() if r else None

    def peer_vrr(self, pattern, date, grain):
        return [x.asDict() for x in self.spark.sql(
            f"SELECT * FROM {self._tbl(grain)} WHERE vrr_date=:d AND pattern_id<>:p",
            args={"p": pattern, "d": date}).collect()]

    def prior_vrr(self, pattern, date, grain):
        r = self.spark.sql(
            f"SELECT * FROM {self._tbl(grain)} WHERE pattern_id=:p AND vrr_date < :d "
            "ORDER BY vrr_date DESC LIMIT 1", args={"p": pattern, "d": date}).collect()
        return r[0].asDict() if r else None

    def target_vrr(self, pattern):
        r = self.spark.sql(
            f"SELECT target_vrr FROM {self.cfg.pattern_target} WHERE pattern_id=:p",
            args={"p": pattern}).collect()
        return float(r[0]["target_vrr"]) if r else None

    def contrib_rows(self, pattern, date, grain=CURATED_MONTHLY):
        if grain == CURATED_MONTHLY:
            rows = [x.asDict() for x in self.spark.sql(
                f"SELECT * FROM {self.cfg.completion_contrib} "
                "WHERE pattern_id=:p AND date_trunc('MM', vrr_date)=date_trunc('MM', :d)",
                args={"p": pattern, "d": date}).collect()]
            return aggregate_contrib_monthly(rows, pattern, str(date))
        return [x.asDict() for x in self.spark.sql(
            f"SELECT * FROM {self.cfg.completion_contrib} WHERE pattern_id=:p AND vrr_date=:d",
            args={"p": pattern, "d": date}).collect()]

    def impact(self, root_node_id):
        return [x.asDict() for x in self.spark.sql(
            f"SELECT * FROM {self.cfg.catalog}.vrr_agent.vrr_impact(:n)",
            args={"n": root_node_id}).collect()]

    def trace(self, vrr_node_id_str):
        return [x.asDict() for x in self.spark.sql(
            f"SELECT * FROM {self.cfg.catalog}.vrr_agent.vrr_trace(:n)",
            args={"n": vrr_node_id_str}).collect()]

    def latest_transform_sql(self, grain, asset=None):
        agg = "Monthly" if grain == CURATED_MONTHLY else "Daily"
        cond = "aggregation_type=:a" + (" AND asset_name=:s" if asset else "")
        r = self.spark.sql(
            f"SELECT * FROM {self.cfg.catalog}.vrr_agent.pattern_vrr_log WHERE {cond} "
            "ORDER BY log_ts DESC LIMIT 1",
            args={"a": agg, **({"s": asset} if asset else {})}).collect()
        return r[0].asDict() if r else None


class SqlWarehouseData:  # pragma: no cover - needs a warehouse + creds
    """Serving-friendly data layer: databricks-sql-connector over a SQL warehouse.

    Model Serving has no Spark session, so the deployed agent reads vrr_curated
    through a warehouse (same pattern as the CDP stub agents' ``run_sql``). Creds
    come from the environment / serving OAuth, never source. Parameterized queries
    only (read-only).
    """

    def __init__(self, connect_fn, cfg: Optional[_cfg.Config] = None):
        # connect_fn() -> a live databricks.sql Connection (injected so this stays
        # testable and credential-agnostic).
        self._connect = connect_fn
        self.cfg = cfg or _cfg.load_config()

    def _q(self, sql: str, params: dict) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _tbl(self, grain):
        return self.cfg.pattern_vrr_monthly if grain == CURATED_MONTHLY else self.cfg.pattern_vrr_daily

    def resolve_pattern(self, pattern):
        r = self._q(f"SELECT pattern_id FROM {self.cfg.pattern_vrr_monthly} "
                    "WHERE lower(pattern_id)=lower(%(p)s) OR lower(pattern_name)=lower(%(p)s) LIMIT 1",
                    {"p": pattern})
        return r[0]["pattern_id"] if r else pattern

    def list_patterns(self):
        return self._q(
            f"SELECT pattern_id, max(pattern_name) pattern_name, count(*) n_periods, "
            "min(vrr_date) first_date, max(vrr_date) last_date, "
            f"max_by(vrr, vrr_date) latest_vrr FROM {self.cfg.pattern_vrr_monthly} "
            "GROUP BY pattern_id ORDER BY pattern_id", {})

    def overview(self, date, grain):
        if date:
            return self._q(f"SELECT * FROM {self._tbl(grain)} WHERE vrr_date=%(d)s", {"d": date})
        return self._q(f"SELECT * FROM {self._tbl(grain)} QUALIFY row_number() OVER "
                       "(PARTITION BY pattern_id ORDER BY vrr_date DESC)=1", {})

    def vrr_row(self, pattern, date, grain):
        r = self._q(f"SELECT * FROM {self._tbl(grain)} WHERE pattern_id=%(p)s AND vrr_date=%(d)s",
                    {"p": pattern, "d": date})
        return r[0] if r else None

    def peer_vrr(self, pattern, date, grain):
        return self._q(f"SELECT * FROM {self._tbl(grain)} WHERE vrr_date=%(d)s AND pattern_id<>%(p)s",
                       {"p": pattern, "d": date})

    def prior_vrr(self, pattern, date, grain):
        r = self._q(f"SELECT * FROM {self._tbl(grain)} WHERE pattern_id=%(p)s AND vrr_date<%(d)s "
                    "ORDER BY vrr_date DESC LIMIT 1", {"p": pattern, "d": date})
        return r[0] if r else None

    def target_vrr(self, pattern):
        r = self._q(f"SELECT target_vrr FROM {self.cfg.pattern_target} WHERE pattern_id=%(p)s",
                    {"p": pattern})
        return float(r[0]["target_vrr"]) if r else None

    def contrib_rows(self, pattern, date, grain=CURATED_MONTHLY):
        if grain == CURATED_MONTHLY:
            rows = self._q(
                f"SELECT * FROM {self.cfg.completion_contrib} WHERE pattern_id=%(p)s "
                "AND date_trunc('MM', vrr_date)=date_trunc('MM', %(d)s)", {"p": pattern, "d": date})
            return aggregate_contrib_monthly(rows, pattern, str(date))
        return self._q(f"SELECT * FROM {self.cfg.completion_contrib} "
                       "WHERE pattern_id=%(p)s AND vrr_date=%(d)s", {"p": pattern, "d": date})

    def impact(self, root_node_id):
        return self._q(f"SELECT * FROM {self.cfg.catalog}.vrr_agent.vrr_impact(%(n)s)",
                       {"n": root_node_id})

    def trace(self, vrr_node_id_str):
        return self._q(f"SELECT * FROM {self.cfg.catalog}.vrr_agent.vrr_trace(%(n)s)",
                       {"n": vrr_node_id_str})

    def latest_transform_sql(self, grain, asset=None):
        agg = "Monthly" if grain == CURATED_MONTHLY else "Daily"
        p = {"a": agg}
        cond = "aggregation_type=%(a)s"
        if asset:
            cond += " AND asset_name=%(s)s"; p["s"] = asset
        r = self._q(f"SELECT * FROM {self.cfg.catalog}.vrr_agent.pattern_vrr_log "
                    f"WHERE {cond} ORDER BY log_ts DESC LIMIT 1", p)
        return r[0] if r else None


# --------------------------------------------------------------------------- #
# Tool A/B/C
# --------------------------------------------------------------------------- #
def vrr_list_patterns(data: DataAccess) -> dict:
    """VRR_LIST_PATTERNS — catalog of available patterns + their period coverage.

    The discovery tool: answers "what patterns exist?" / "what periods are loaded?"
    so the agent can handle open-ended questions instead of demanding an exact id.
    """
    pats = data.list_patterns()
    return {"count": len(pats), "patterns": pats}


def vrr_overview(data: DataAccess, date: Optional[str] = None,
                 grain: str = CURATED_MONTHLY,
                 default_target: float = _cfg.DEFAULT_TARGET_VRR) -> dict:
    """VRR_OVERVIEW — every pattern's VRR vs target at a period (or each pattern's
    latest), ranked by drift from target. Answers "which patterns are over/under-
    replacing?" / "give me a summary" without naming a pattern first.
    """
    rows = data.overview(date, grain)
    lo, hi = _cfg.TARGET_BAND
    out = []
    for r in rows:
        v = r.get("vrr")
        tgt = data.target_vrr(r["pattern_id"])
        tgt = tgt if tgt is not None else default_target
        verdict = ("undefined" if v is None else
                   "over-replacing" if v > hi else "under-replacing" if v < lo else "on-target")
        out.append({"pattern_id": r["pattern_id"], "pattern_name": r.get("pattern_name"),
                    "vrr_date": str(r["vrr_date"]), "vrr": v, "target_vrr": tgt,
                    "verdict": verdict, "drift": (abs(v - tgt) if v is not None else None),
                    "any_extrapolated": bool(r.get("any_extrapolated"))})
    out.sort(key=lambda x: (x["drift"] is None, -(x["drift"] or 0)))
    return {"grain": grain, "date": date or "latest-per-pattern", "count": len(out), "patterns": out}


def vrr_get(data: DataAccess, pattern: str, date: str, grain: str = CURATED_MONTHLY,
            default_target: float = _cfg.DEFAULT_TARGET_VRR) -> dict:
    """VRR_GET — the stored VRR plus the references for "high vs *what*?"."""
    pattern = data.resolve_pattern(pattern)   # accept pattern name (UNITY) or id (PUNITY)
    row = data.vrr_row(pattern, date, grain)
    if not row:
        return {"found": False, "pattern": pattern, "date": str(date), "grain": grain}
    target = data.target_vrr(pattern)
    prior = data.prior_vrr(pattern, date, grain)
    peers = data.peer_vrr(pattern, date, grain)
    peer_vals = [p["vrr"] for p in peers if p.get("vrr") is not None]
    return {
        "found": True, "pattern": pattern, "date": str(date), "grain": grain,
        "vrr": row.get("vrr"), "cum_vrr": row.get("cum_vrr"),
        "prod_res_bbl": row.get("prod_res_bbl"), "inj_res_bbl": row.get("inj_res_bbl"),
        "target_vrr": target if target is not None else default_target,
        "target_is_default": target is None,
        "prior_date": str(prior["vrr_date"]) if prior else None,
        "prior_vrr": prior.get("vrr") if prior else None,
        "peer_avg_vrr": (sum(peer_vals) / len(peer_vals)) if peer_vals else None,
        "any_extrapolated": bool(row.get("any_extrapolated")),
        "provenance": {"table": "vrr_curated.pattern_vrr_" + grain,
                       "keys": {"pattern_id": pattern, "vrr_date": str(date)},
                       "run_id": row.get("run_id")},
    }


def _term_totals(rows: list[dict], terms) -> dict:
    return {t: sum((r.get(t) or 0.0) for r in rows) for t in terms}


def vrr_decompose(data: DataAccess, pattern: str, date_a: str, date_b: str,
                  grain: str = CURATED_MONTHLY) -> dict:
    """VRR_DECOMPOSE — exact attribution of ΔVRR (a→b) to its drivers (design §6).

    Works in log space: Δln(VRR) = Δln(INJ) − Δln(PROD). Each additive term's
    contribution uses the log-mean identity so it is **exact even when a term is
    negative** (free-gas can be < 0):

        contribution_to_Δln(total)  =  (term_b − term_a) / L(total_a, total_b)

    which sums exactly to Δln(total). The LLM may only name a driver this tool
    supports (attribution-faithfulness guardrail, design §9).
    """
    pattern = data.resolve_pattern(pattern)   # accept pattern name or id
    ca = data.contrib_rows(pattern, date_a, grain)
    cb = data.contrib_rows(pattern, date_b, grain)
    if not ca or not cb:
        return {"ok": False, "reason": "missing contrib rows for one endpoint",
                "date_a": str(date_a), "date_b": str(date_b)}

    prod_a = _term_totals(ca, PROD_TERMS); prod_b = _term_totals(cb, PROD_TERMS)
    inj_a = _term_totals(ca, INJ_TERMS);  inj_b = _term_totals(cb, INJ_TERMS)
    PROD_a, PROD_b = sum(prod_a.values()), sum(prod_b.values())
    INJ_a, INJ_b = sum(inj_a.values()), sum(inj_b.values())
    if min(PROD_a, PROD_b, INJ_a, INJ_b) <= 0:
        return {"ok": False, "reason": "non-positive INJ/PROD total; decomposition undefined",
                "PROD": (PROD_a, PROD_b), "INJ": (INJ_a, INJ_b)}

    Lp, Li = log_mean(PROD_a, PROD_b), log_mean(INJ_a, INJ_b)
    vrr_a, vrr_b = INJ_a / PROD_a, INJ_b / PROD_b
    dln_vrr = math.log(vrr_b) - math.log(vrr_a)

    drivers = []
    # injection-side terms push VRR up (+), production-side terms push it down (−)
    for t in INJ_TERMS:
        drivers.append({"driver": _TERM_LABEL[t], "side": "injection",
                        "contribution": (inj_b[t] - inj_a[t]) / Li})
    for t in PROD_TERMS:
        drivers.append({"driver": _TERM_LABEL[t], "side": "production",
                        "contribution": -(prod_b[t] - prod_a[t]) / Lp})
    total_abs = sum(abs(d["contribution"]) for d in drivers) or 1.0
    for d in drivers:
        d["abs_share"] = abs(d["contribution"]) / total_abs
    drivers.sort(key=lambda d: -abs(d["contribution"]))

    # pressure / PVT deltas (the free-gas driver's root) + top completions
    def _avg(rows, k):
        vals = [r.get(k) for r in rows if r.get(k) is not None]
        return sum(vals) / len(vals) if vals else None

    p_a, p_b = _avg(ca, "pressure_psi"), _avg(cb, "pressure_psi")
    bg_a, bg_b = _avg(ca, "bg"), _avg(cb, "bg")
    rs_a, rs_b = _avg(ca, "rs"), _avg(cb, "rs")

    by_comp = {}
    for r in ca:
        by_comp.setdefault(r["completion_id"], {})["a"] = r.get("free_gas_res") or 0.0
    for r in cb:
        by_comp.setdefault(r["completion_id"], {})["b"] = r.get("free_gas_res") or 0.0
    top = sorted(
        ({"completion_id": c, "d_free_gas_res": v.get("b", 0.0) - v.get("a", 0.0)}
         for c, v in by_comp.items()),
        key=lambda x: -abs(x["d_free_gas_res"]))[:3]

    return {
        "ok": True, "pattern": pattern, "grain": grain,
        "date_a": str(date_a), "date_b": str(date_b),
        "vrr_a": vrr_a, "vrr_b": vrr_b, "dln_vrr": dln_vrr,
        "drivers": drivers,
        "pressure": {"a": p_a, "b": p_b,
                     "delta_psi": (p_b - p_a) if (p_a is not None and p_b is not None) else None},
        "bg": {"a": bg_a, "b": bg_b,
               "pct": ((bg_b - bg_a) / bg_a) if (bg_a and bg_b) else None},
        "rs": {"a": rs_a, "b": rs_b,
               "pct": ((rs_b - rs_a) / rs_a) if (rs_a and rs_b) else None},
        "top_completions": top,
        "any_extrapolated": any(r.get("pvt_method") == "extrapolated" for r in ca + cb),
    }


def vrr_lineage(data: DataAccess, pattern: str, date: str,
                field_name: Optional[str] = None, grain: str = CURATED_MONTHLY) -> dict:
    """VRR_LINEAGE — root-trace VRR (or one field) to the raw source rows (design §7).

    Returns the field → formula → **source table + row keys** tree with the actual
    value and a per-node confidence flag (the PVT method). This is the on-screen
    "proof of data" an engineer clicks through — no black box.
    """
    pattern = data.resolve_pattern(pattern)   # accept pattern name or id
    rows = data.contrib_rows(pattern, date, grain)
    if not rows:
        return {"found": False, "pattern": pattern, "date": str(date)}

    prod = sum((r.get(t) or 0.0) for r in rows for t in PROD_TERMS)
    inj = sum((r.get(t) or 0.0) for r in rows for t in INJ_TERMS)
    vrr = inj / prod if prod else None

    def _node(r):
        return {
            "completion_id": r["completion_id"],
            "free_gas_res": r.get("free_gas_res"),
            "oil_res": r.get("oil_res"), "water_res": r.get("water_res"),
            "water_inj_res": r.get("water_inj_res"), "gas_inj_res": r.get("gas_inj_res"),
            "roots": {
                "factor": {"value": r.get("factor"),
                           "source": "vrr_raw.pattern_contribution_factor",
                           "keys": {"ID_COMPLETION": r["completion_id"],
                                    "ID_PATTERN": pattern}},
                "volumes": {"oil": r.get("oil"), "water": r.get("water"), "gas": r.get("gas"),
                            "water_inj": r.get("water_inj"), "gas_inj": r.get("gas_inj"),
                            "source": "vrr_raw.production_volumes_daily_oilfield",
                            "keys": {"EMSDB_PROD_COMPLETION_ID": r["completion_id"],
                                     "PROD_DATE": str(date)}},
                "pressure": {"value": r.get("pressure_psi"),
                             "source": "vrr_raw.pattern_pressure",
                             "keys": {"ID_PATTERN": pattern}},
                "pvt": {"bo": r.get("bo"), "bw": r.get("bw"), "bg": r.get("bg"),
                        "rs": r.get("rs"), "bw_inj": r.get("bw_inj"), "bg_inj": r.get("bg_inj"),
                        "method": r.get("pvt_method"),
                        "bracket": [r.get("pvt_bracket_lo"), r.get("pvt_bracket_hi")],
                        "confidence": "low" if r.get("pvt_method") == "extrapolated" else "ok",
                        "source": "vrr_raw.completion_pvt_characteristics",
                        "keys": {"ID_COMPLETION": r["completion_id"]}},
            },
            "missing_input": r.get("missing_input"),
            "run_id": r.get("run_id"),
        }

    nodes = [_node(r) for r in rows]
    if field_name:  # narrow to the completions that actually drive that field
        nodes = sorted(nodes, key=lambda n: -abs((n.get(field_name) or 0.0)))

    return {
        "found": True, "pattern": pattern, "date": str(date),
        "vrr": vrr, "formula": "VRR = INJ_RES / PROD_RES",
        "INJ_RES": inj, "PROD_RES": prod,
        "field": field_name,
        "any_extrapolated": any(r.get("pvt_method") == "extrapolated" for r in rows),
        "missing_inputs": sorted({r.get("missing_input") for r in rows if r.get("missing_input")}),
        "completions": nodes,
    }


# --------------------------------------------------------------------------- #
# Value-level lineage graph — node-id helpers. These MUST match the concat_ws keys
# in 06_build_lineage_graph.sql exactly, so the in-memory (test) traversal and the
# persisted-Delta traversal (UC functions vrr_impact/vrr_trace) agree.
# --------------------------------------------------------------------------- #
def contrib_node_id(r: dict) -> str:
    return f"contrib:{r['pattern_id']}:{r['completion_id']}:{r['vrr_date']}"


def vrr_node_id(pattern_id: str, grain: str, date: str) -> str:
    return f"vrr:{pattern_id}:{grain}:{date}"


def root_node_id(input_type: str, *, pattern_id=None, completion_id=None, date=None) -> str:
    if input_type == "factor":   return f"factor:{completion_id}:{pattern_id}"
    if input_type == "volume":   return f"volume:{completion_id}:{date}"
    if input_type == "pressure": return f"pressure:{pattern_id}:{date}"
    if input_type == "pvt":      return f"pvt:{completion_id}"
    raise ValueError(f"bad input_type {input_type}")


def _contrib_roots(r: dict) -> dict:
    """The four root node_ids a completion_contrib row derives from (matches SQL)."""
    d = str(r["vrr_date"])
    return {"factor": root_node_id("factor", pattern_id=r["pattern_id"], completion_id=r["completion_id"]),
            "volume": root_node_id("volume", completion_id=r["completion_id"], date=d),
            "pressure": root_node_id("pressure", pattern_id=r["pattern_id"], date=d),
            "pvt": root_node_id("pvt", completion_id=r["completion_id"])}


def vrr_impact(data: DataAccess, input_type: str, date: Optional[str] = None,
               pattern: Optional[str] = None, completion: Optional[str] = None) -> dict:
    """VRR_IMPACT — what-if / impact: which VRR outputs depend on a given raw input?

    Forward reachability over the persisted lineage graph. E.g. "if the April 2026
    pressure for UNITY changed, which VRRs move?" -> every VRR downstream of
    ``pressure:PUNITY:2026-04-01``.
    """
    pid = data.resolve_pattern(pattern) if pattern else None
    try:
        node = root_node_id(input_type, pattern_id=pid, completion_id=completion, date=date)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    rows = data.impact(node)
    return {"ok": True, "input_node": node, "input_type": input_type,
            "impacted_count": len(rows), "impacted_vrrs": rows}


def vrr_explain_calc(data: DataAccess, grain: str = CURATED_MONTHLY,
                     asset: Optional[str] = None) -> dict:
    """VRR_EXPLAIN_CALC — retrieve the ACTUAL transformation SQL that built the VRR
    for an asset+grain (the latest row of pattern_vrr_log, the Databricks port of the
    Snowflake PATTERN_VRR_LOG). The agent explains THIS text, so "how is VRR
    calculated" is answered from source, never from memory. Point-in-time via run_id.
    """
    row = data.latest_transform_sql(grain, asset)
    if not row:
        return {"found": False, "grain": grain, "asset": asset,
                "note": "no logged transformation SQL for that asset/grain yet"}
    return {"found": True, "asset_name": row.get("asset_name"),
            "aggregation_type": row.get("aggregation_type"), "run_id": row.get("run_id"),
            "logged_at": str(row.get("log_ts")), "row_count": row.get("row_count"),
            "uom": row.get("uom"), "sql_text": row.get("sql_text")}


def vrr_lineage_graph(data: DataAccess, pattern: str, date: str,
                      grain: str = CURATED_MONTHLY, direction: str = "up") -> dict:
    """VRR_LINEAGE_GRAPH — persisted root-trace of a VRR output to its raw inputs.

    The stored, queryable counterpart of VRR_LINEAGE (which builds a tree per call).
    ``direction='up'`` traces a VRR back to the raw factor/volume/pressure/PVT roots.
    """
    pid = data.resolve_pattern(pattern)
    node = vrr_node_id(pid, grain, str(date))
    roots = data.trace(node)
    return {"ok": True, "vrr_node": node, "grain": grain, "direction": direction,
            "root_count": len(roots), "roots": roots}


# --------------------------------------------------------------------------- #
# Tool-calling interface (Databricks-native / OpenAI function-calling schema).
# TOOL_SPECS is the SINGLE source of truth for the tools the served agent exposes;
# call_tool() dispatches a model-issued tool call to the deterministic fn above.
# --------------------------------------------------------------------------- #
_GRAIN = {"type": "string", "enum": ["monthly", "daily"],
          "description": "aggregation grain (default monthly)"}
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "VRR_LIST_PATTERNS",
        "description": "List the patterns available in the system with their period "
                       "coverage (first/last date, count, latest VRR). Use this FIRST for "
                       "discovery questions like 'what patterns exist?' or when the user "
                       "hasn't named a pattern.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "VRR_OVERVIEW",
        "description": "Every pattern's VRR vs target for a period (or each pattern's "
                       "latest), ranked by drift from target. Use for 'which patterns are "
                       "over/under-replacing?' or a portfolio summary.",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string", "description": "optional period YYYY-MM-DD; omit for latest per pattern"},
            "grain": _GRAIN}}}},
    {"type": "function", "function": {
        "name": "VRR_GET",
        "description": "Stored VRR + cumulative VRR + the 'high vs what?' references "
                       "(target, prior period, peer average) for a pattern on a date.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "pattern id (e.g. PUNITY) or name (UNITY)"},
            "date": {"type": "string", "description": "period date YYYY-MM-DD (month-start for monthly)"},
            "grain": _GRAIN}, "required": ["pattern", "date"]}}},
    {"type": "function", "function": {
        "name": "VRR_DECOMPOSE",
        "description": "Exact attribution of a VRR CHANGE between two dates to its drivers "
                       "(injection vs production -> oil/water/free-gas) plus pressure/Bg/Rs "
                       "deltas and the top completions. Call VRR_GET first to get prior_date.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "date_a": {"type": "string", "description": "earlier period YYYY-MM-DD"},
            "date_b": {"type": "string", "description": "later period YYYY-MM-DD"},
            "grain": _GRAIN}, "required": ["pattern", "date_a", "date_b"]}}},
    {"type": "function", "function": {
        "name": "VRR_LINEAGE",
        "description": "Root-trace a VRR (or one field like free_gas_res) to the raw source "
                       "rows (volumes, factor, pressure, PVT) with per-node confidence.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "date": {"type": "string", "description": "period date YYYY-MM-DD"},
            "field": {"type": "string", "description": "optional field to focus, e.g. free_gas_res"},
            "grain": _GRAIN}, "required": ["pattern", "date"]}}},
    {"type": "function", "function": {
        "name": "VRR_IMPACT",
        "description": "Impact / what-if: which VRR outputs depend on a specific RAW INPUT? "
                       "Use for 'if this pressure/PVT/volume/factor changed, which VRRs move?'. "
                       "Forward-traverses the persisted lineage graph.",
        "parameters": {"type": "object", "properties": {
            "input_type": {"type": "string", "enum": ["pressure", "pvt", "volume", "factor"]},
            "pattern": {"type": "string", "description": "required for pressure/factor"},
            "completion": {"type": "string", "description": "required for pvt/volume/factor (a well/completion id)"},
            "date": {"type": "string", "description": "required for pressure/volume (YYYY-MM-DD)"}},
            "required": ["input_type"]}}},
    {"type": "function", "function": {
        "name": "VRR_LINEAGE_GRAPH",
        "description": "Persisted root-trace of a VRR output to its raw inputs (the stored, "
                       "queryable form of VRR_LINEAGE). Use for 'trace/prove this VRR'.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
            "grain": _GRAIN}, "required": ["pattern", "date"]}}},
    {"type": "function", "function": {
        "name": "VRR_EXPLAIN_CALC",
        "description": "Retrieve the ACTUAL transformation SQL that computes VRR (the latest "
                       "logged build SQL for the asset+grain). Use for 'how / explain how VRR "
                       "is calculated', 'what's the methodology', 'give me the SQL/pseudocode'. "
                       "Explain the RETURNED sql_text — never describe the calculation from memory.",
        "parameters": {"type": "object", "properties": {
            "grain": _GRAIN,
            "asset": {"type": "string", "description": "optional asset/reservoir name; omit for the default"}}}}},
]


def call_tool(data: DataAccess, name: str, args: dict) -> dict:
    """Dispatch a model-issued tool call to the deterministic tool. Every number
    returned traces to vrr_curated; the LLM never computes."""
    grain = CURATED_DAILY if str(args.get("grain", "")).startswith("da") else CURATED_MONTHLY
    if name == "VRR_LIST_PATTERNS":
        return vrr_list_patterns(data)
    if name == "VRR_OVERVIEW":
        return vrr_overview(data, args.get("date"), grain)
    if name == "VRR_GET":
        return vrr_get(data, args["pattern"], args["date"], grain)
    if name == "VRR_DECOMPOSE":
        return vrr_decompose(data, args["pattern"], args["date_a"], args["date_b"], grain)
    if name == "VRR_LINEAGE":
        return vrr_lineage(data, args["pattern"], args["date"], args.get("field"), grain)
    if name == "VRR_IMPACT":
        return vrr_impact(data, args["input_type"], date=args.get("date"),
                          pattern=args.get("pattern"), completion=args.get("completion"))
    if name == "VRR_LINEAGE_GRAPH":
        return vrr_lineage_graph(data, args["pattern"], args["date"], grain)
    if name == "VRR_EXPLAIN_CALC":
        return vrr_explain_calc(data, grain, args.get("asset"))
    return {"error": f"unknown tool {name}"}
