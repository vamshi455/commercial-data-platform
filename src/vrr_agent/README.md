# vrr_agent — VRR Reasoning & Lineage agent

Explains **why** a waterflood pattern's Voidage Replacement Ratio (VRR) is high or
low, and traces every value to its root inputs so an engineer can **trust the
number**. Read-only; it answers *why*, it never changes wells.

> Implements [`documentation/vrr_agent_master_design.md`](https://github.com/vamshi455/Voidage-Replacement-Ratio)
> (private repo) inside this platform's `cdp_dev` catalog.

## Governing principle
**The LLM never does arithmetic.** Every number comes from a deterministic tool
([`physics.py`](physics.py) / [`tools.py`](tools.py)) carrying provenance (source
table + row keys + `run_id`). The agent ([`agent.py`](agent.py)) only plans tool
calls and narrates — and a deterministic faithfulness gate rejects any narration
that names a driver the decomposition doesn't support.

## Domain isolation
VRR is oil & gas — a different domain from the commercial CDP — so it lives in its
own schemas inside `cdp_dev`, never mixing with `bronze/silver/gold`:

```
cdp_dev
  vrr_raw       source-shaped tables (ACTUAL pipeline names — real data is drop-in)
  vrr_curated   completion_contrib (lineage layer) + pattern_vrr_daily/_monthly
  vrr_agent     audit_log (tools read curated; agent only writes audit)
```

## Data flow
```
vrr_raw (volumes · factors · pressure · PVT)
   │  03_build_contrib.py  — physics.py: PVT interp @ pressure + reservoir volumes
   ▼
vrr_curated.completion_contrib     ← the lineage layer (every input + result per completion/date)
   │  04_build_vrr.py  — pure aggregation
   ▼
vrr_curated.pattern_vrr_daily / _monthly   ← VRR = INJ_RES / PROD_RES
   │  tools.py (VRR_GET / VRR_DECOMPOSE / VRR_LINEAGE)
   ▼
agent.py  — LLM narrates the tool numbers (no math) + faithfulness gate
```

## Files
| File | Role |
|---|---|
| `config.py` | catalog/schema/object names, per-env widgets (cdp_dev/qa/prod) |
| `physics.py` | **deterministic** PVT interpolation + reservoir-volume math (pure) |
| `01_setup_schemas.sql` | schemas + raw/curated/agent table DDL |
| `02_seed_raw.py` | synthetic raw data incl. the design's UNITY worked example |
| **`vrr_build.sql`** | **faithful Databricks port of the production `vrr_sql_builder.sql`** (11 CHECKPOINTS): raw → `completion_contrib` → `pattern_vrr_daily/_monthly`. The canonical, production-aligned transformation. |
| `03_build_contrib.py` | pure-Python mirror of the build (uses `physics.py`); `04_build_vrr.py` aggregates. Kept for off-cluster testing; `vrr_build.sql` is authoritative. |
| `tools.py` | the 3 tools over an **injectable** data layer (Spark or in-memory) |
| `agent.py` | reasoning agent (`databricks-claude-sonnet-5`) + faithfulness verifier |
| `tests/` | off-cluster unit tests (physics + tools + decomposition exactness) |

## Run order
```bash
# 1. schemas + tables
databricks --profile cdp-dev sql --file src/vrr_agent/01_setup_schemas.sql --param catalog=cdp_dev
# 2-4. seed + build (notebook/job tasks; widgets: catalog, run_id)
#   02_seed_raw.py → 03_build_contrib.py → 04_build_vrr.py
# tests (no cluster needed)
python -m pytest src/vrr_agent/tests/ -q
```

## Key design choices (open questions resolved)
- **PVT**: full production ladder (aligned to `vrr_sql_builder` CHECKPOINT 8) —
  exact → interpolate → **2-point linear extrapolation** → closest → NULL; method
  = confidence flag. `Bg` rounded to 5 dp (RMDE storage). Free gas gated on
  `Amount_Type='Production' AND OIL_VOL>0` (NULL otherwise), negative allowed.
  `physics.py` mirrors this exactly so the Python build and the SQL builder agree.
- **Decomposition**: exact **log-mean (LMDI)** attribution — additive and correct
  even when the free-gas term is negative. Contributions sum exactly to Δln(VRR).
- **"High vs what?"**: per-pattern target from `pattern_target`, default **1.0**.
- **Grain**: `completion_contrib` is daily; monthly tools aggregate daily→monthly
  per completion (worst-case PVT confidence) so lineage/decompose match the VRR grain.

## ⚠️ Open item flagged to resolve (design inconsistency)
The design's §1 physics (`Bg ≈ 1/P`) says a **pressure decline swells** the free-gas
term → **larger denominator → VRR falls**. But the §8/§6 worked narrative has the
same pressure decline **raising** VRR to 1.31 ("denominator shrank", "Bg dropped").
These directions contradict. This implementation follows **§1 (standard reservoir
physics)**: the seeded UNITY example shows VRR *easing* as pressure falls and free
gas grows, with free gas the dominant driver. If the intended story is §8's, the
`Bg` vs pressure relationship in the PVT seed (and the narrative) need reconciling.

## Not yet built (next)
- The **report app** (§9.5): verdict banner + injection-vs-production hero chart +
  VRR trend + attribution bar + clickable lineage + PDF export (Streamlit/Plotly).
- Registering the tools as **UC functions** (currently Python tools over the data
  layer) and the Mosaic AI agent deployment notebook.
