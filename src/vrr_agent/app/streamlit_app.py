"""VRR report app (design §9.5) — verdict banner, hero chart, VRR trend, attribution,
plain summary, clickable lineage, and print-to-PDF. Streamlit + Plotly.

Layman-first: one colour-coded verdict up top; detail and base data are drill-downs.
Every number reads through the deterministic tools (tools.py) over vrr_curated, so
charts, narrative, and lineage all trace to root. Runs as a Databricks App /
Streamlit-in-Databricks (uses the ambient Spark session).

PDF: the browser's Print → Save as PDF; the print CSS below adds page breaks so the
banner+hero, attribution, and base-data appendix land on separate pages.
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from src.vrr_agent import config as cfg_mod
from src.vrr_agent import tools as T
from src.vrr_agent import agent as A

st.set_page_config(page_title="VRR — Reasoning & Lineage", layout="wide")

CFG = cfg_mod.load_config()
BAND_LO, BAND_HI = cfg_mod.TARGET_BAND


# --------------------------------------------------------------------------- #
# Data access (ambient Spark on Databricks). Cached for snappy interaction.
# --------------------------------------------------------------------------- #
@st.cache_resource
def _data():
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    return spark, T.SparkData(spark, CFG)


@st.cache_data(ttl=300)
def _patterns():
    spark, _ = _data()
    rows = spark.table(CFG.pattern_vrr_monthly).select(
        "pattern_id", "pattern_name").distinct().collect()
    return {r["pattern_name"]: r["pattern_id"] for r in rows}


@st.cache_data(ttl=300)
def _series(pattern_id, grain):
    spark, _ = _data()
    tbl = CFG.pattern_vrr_monthly if grain == T.CURATED_MONTHLY else CFG.pattern_vrr_daily
    return [r.asDict() for r in spark.sql(
        f"SELECT * FROM {tbl} WHERE pattern_id=:p ORDER BY vrr_date",
        args={"p": pattern_id}).collect()]


# --------------------------------------------------------------------------- #
# Print CSS (page breaks for the PDF export).
# --------------------------------------------------------------------------- #
st.markdown("""
<style>
@media print {
  section[data-testid="stSidebar"], .stButton, header, footer {display:none!important;}
  .page-break {break-before:page;}
  .block-container {max-width:100%!important;}
}
.verdict {padding:18px 22px;border-radius:12px;color:#fff;font-size:1.15rem;font-weight:600;}
.gauge-num {font-size:2.6rem;font-weight:800;line-height:1;}
</style>
""", unsafe_allow_html=True)


def _band_color(vrr):
    if vrr is None:
        return "#607d8b"
    if BAND_LO <= vrr <= BAND_HI:
        return "#2e7d32"          # green — on target
    return "#c62828" if vrr > BAND_HI else "#ef6c00"   # red over / amber under


# --------------------------------------------------------------------------- #
# Sidebar controls.
# --------------------------------------------------------------------------- #
st.sidebar.title("VRR report")
pats = _patterns()
pname = st.sidebar.selectbox("Pattern", sorted(pats))
grain = st.sidebar.radio("Grain", [T.CURATED_MONTHLY, T.CURATED_DAILY], horizontal=True)
pid = pats[pname]
series = _series(pid, grain)
if not series:
    st.warning("No VRR rows for this pattern/grain. Run 02–04 to build the tables.")
    st.stop()
dates = [str(r["vrr_date"]) for r in series]
date = st.sidebar.selectbox("Period", dates, index=len(dates) - 1)

_, data = _data()
got = T.vrr_get(data, pid, date, grain)
prior = got.get("prior_date")
dec = T.vrr_decompose(data, pid, prior, date, grain) if prior else {"ok": False}
lin = T.vrr_lineage(data, pid, date, field_name="free_gas_res", grain=grain)

# --------------------------------------------------------------------------- #
# 1 · Verdict banner (colour-coded gauge + one plain sentence).
# --------------------------------------------------------------------------- #
vrr = got.get("vrr")
target = got.get("target_vrr")
verdict = A.verdict(vrr, target)
c1, c2 = st.columns([1, 3])
with c1:
    st.markdown(f"<div class='verdict' style='background:{_band_color(vrr)}'>"
                f"<div class='gauge-num'>{vrr:.2f}</div>VRR · target {target:.2f}"
                f"{' (default)' if got.get('target_is_default') else ''}</div>",
                unsafe_allow_html=True)
with c2:
    st.subheader(f"Pattern {pname} · {date}")
    st.markdown(f"**{verdict.capitalize()}.**"
                + ("  ⚠️ contains extrapolated PVT (lower confidence)."
                   if got.get("any_extrapolated") else ""))
    if got.get("prior_vrr") is not None:
        st.caption(f"Prior period {prior}: VRR {got['prior_vrr']:.2f}"
                   + (f" · peer avg {got['peer_avg_vrr']:.2f}"
                      if got.get("peer_avg_vrr") is not None else ""))

# --------------------------------------------------------------------------- #
# 2 · Hero chart — injection vs production (reservoir bbl) over time.
# --------------------------------------------------------------------------- #
st.markdown("### Injection vs Production (reservoir bbl)")
fig = go.Figure()
fig.add_bar(x=dates, y=[r["prod_res_bbl"] for r in series], name="Production",
            marker_color="#5c6bc0")
fig.add_bar(x=dates, y=[r["inj_res_bbl"] for r in series], name="Injection",
            marker_color="#26a69a")
fig.update_layout(barmode="group", height=320, margin=dict(t=10, b=10),
                  legend=dict(orientation="h"))
st.plotly_chart(fig, use_container_width=True)

# --------------------------------------------------------------------------- #
# 3 · VRR trend with the green target band.
# --------------------------------------------------------------------------- #
st.markdown("### VRR trend")
tfig = go.Figure()
tfig.add_hrect(y0=BAND_LO, y1=BAND_HI, fillcolor="#2e7d32", opacity=0.12, line_width=0)
tfig.add_scatter(x=dates, y=[r["vrr"] for r in series], mode="lines+markers",
                 name="VRR", line=dict(color="#37474f", width=3))
tfig.add_scatter(x=dates, y=[target] * len(dates), mode="lines", name="target",
                 line=dict(color="#2e7d32", dash="dash"))
tfig.update_layout(height=300, margin=dict(t=10, b=10), legend=dict(orientation="h"))
st.plotly_chart(tfig, use_container_width=True)

# --------------------------------------------------------------------------- #
# 4 · Why — attribution bar + plain summary (page break for PDF).
# --------------------------------------------------------------------------- #
st.markdown("<div class='page-break'></div>", unsafe_allow_html=True)
st.markdown(f"### Why did VRR move? ({prior} → {date})")
if dec.get("ok"):
    drivers = dec["drivers"]
    afig = go.Figure(go.Bar(
        x=[d["abs_share"] for d in drivers],
        y=[f"{d['driver']} ({d['side']})" for d in drivers],
        orientation="h",
        marker_color=["#c62828" if d is drivers[0] else "#90a4ae" for d in drivers]))
    afig.update_layout(height=260, margin=dict(t=10, b=10),
                       xaxis_tickformat=".0%", xaxis_title="share of the move")
    st.plotly_chart(afig, use_container_width=True)
    dom = drivers[0]
    p = dec["pressure"]; bg = dec["bg"]
    bits = [f"Most of the change ({dom['abs_share']:.0%}) came from **{dom['driver']}** "
            f"on the {dom['side']} side."]
    if p.get("delta_psi") is not None:
        bits.append(f"Pattern pressure moved {p['delta_psi']:+.0f} psi")
        if bg.get("pct") is not None:
            bits.append(f", so Bg changed {bg['pct']:+.1%} (free-gas term).")
    st.info(" ".join(bits))
    if dec.get("top_completions"):
        st.caption("Top completions by |Δ free-gas|: "
                   + ", ".join(f"{c['completion_id']} ({c['d_free_gas_res']:+.1f})"
                               for c in dec["top_completions"]))
else:
    st.caption("No prior period to attribute the change against.")

# --------------------------------------------------------------------------- #
# 5 · Proof of data — clickable lineage to the source rows (page break for PDF).
# --------------------------------------------------------------------------- #
st.markdown("<div class='page-break'></div>", unsafe_allow_html=True)
st.markdown("### Proof of data — trace to source rows")
st.caption(f"VRR = INJ_RES / PROD_RES = {lin.get('INJ_RES', 0):,.1f} / "
           f"{lin.get('PROD_RES', 0):,.1f}. Expand a completion to see its roots.")
for node in lin.get("completions", []):
    conf = node["roots"]["pvt"]["confidence"]
    flag = "✅" if conf == "ok" else "⚠️"
    with st.expander(f"{flag} {node['completion_id']} · free_gas_res "
                     f"{node.get('free_gas_res') or 0:,.1f}"):
        r = node["roots"]
        st.write("**FACTOR**", r["factor"]["value"], "←",
                 r["factor"]["source"], r["factor"]["keys"])
        st.write("**Volumes**", r["volumes"], )
        st.write("**Pressure**", r["pressure"]["value"], "←", r["pressure"]["source"])
        st.write(f"**PVT** (method: {r['pvt']['method']}, confidence: {conf})", r["pvt"])
        if node.get("missing_input"):
            st.error(f"missing input: {node['missing_input']}")
        st.caption(f"run_id: {node.get('run_id')}")

st.sidebar.download_button  # noqa: B018 (hint) — PDF is via browser Print below
st.sidebar.markdown("---")
st.sidebar.button("🖨️ Export to PDF", help="Opens the browser print dialog → Save as PDF",
                  on_click=lambda: st.components.v1.html("<script>window.print()</script>",
                                                         height=0))
