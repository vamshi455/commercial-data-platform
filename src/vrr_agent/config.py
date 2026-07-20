"""Environment config for the ``vrr_agent`` module.

Same philosophy as ``src/contract_vector_search/config.py``: the SAME code runs
against ``cdp_dev`` / ``cdp_qa`` / ``cdp_prod`` and only the config differs. All
object names derive from ``catalog`` + the three schemas so there is a single
source of truth. Nothing here has side effects or imports Spark.

VRR is a distinct (oil & gas) domain from the commercial CDP, so it lives in its
own schemas (``vrr_raw`` / ``vrr_curated`` / ``vrr_agent``) inside the shared
``cdp_dev`` catalog rather than mixing into bronze/silver/gold — clean isolation,
trivially droppable.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CATALOG = "cdp_dev"
RAW_SCHEMA = "vrr_raw"
CURATED_SCHEMA = "vrr_curated"
AGENT_SCHEMA = "vrr_agent"

# The agent narrates; it never does arithmetic. This is the Databricks-served
# Foundation Model endpoint used across the CDP agents (stays in-workspace).
GEN_MODEL = "databricks-claude-sonnet-5"

# "High vs what?" — default target VRR when a pattern has no explicit target row.
DEFAULT_TARGET_VRR = 1.0
# Green "on target" band for the report verdict banner / trend chart.
TARGET_BAND = (0.9, 1.1)


@dataclass(frozen=True)
class Config:
    catalog: str = DEFAULT_CATALOG
    raw_schema: str = RAW_SCHEMA
    curated_schema: str = CURATED_SCHEMA
    agent_schema: str = AGENT_SCHEMA
    gen_model: str = GEN_MODEL
    default_target_vrr: float = DEFAULT_TARGET_VRR

    # ---- raw (source-shaped, ACTUAL pipeline names — drop-in for real data) ----
    @property
    def raw_volumes_daily(self) -> str:
        return f"{self.catalog}.{self.raw_schema}.production_volumes_daily_oilfield"

    @property
    def raw_pattern(self) -> str:
        return f"{self.catalog}.{self.raw_schema}.pattern"

    @property
    def raw_contribution_factor(self) -> str:
        return f"{self.catalog}.{self.raw_schema}.pattern_contribution_factor"

    @property
    def raw_pattern_pressure(self) -> str:
        return f"{self.catalog}.{self.raw_schema}.pattern_pressure"

    @property
    def raw_pvt(self) -> str:
        return f"{self.catalog}.{self.raw_schema}.completion_pvt_characteristics"

    # ---- curated (the lineage layer + the VRR aggregates) ------------------
    @property
    def completion_contrib(self) -> str:
        return f"{self.catalog}.{self.curated_schema}.completion_contrib"

    @property
    def pattern_vrr_daily(self) -> str:
        return f"{self.catalog}.{self.curated_schema}.pattern_vrr_daily"

    @property
    def pattern_vrr_monthly(self) -> str:
        return f"{self.catalog}.{self.curated_schema}.pattern_vrr_monthly"

    @property
    def pattern_target(self) -> str:
        return f"{self.catalog}.{self.curated_schema}.pattern_target"

    # ---- agent (audit only; the tools read curated) ------------------------
    @property
    def audit_log(self) -> str:
        return f"{self.catalog}.{self.agent_schema}.audit_log"


def load_config(params: dict | None = None) -> Config:
    """Pure builder from a plain dict (widgets, env, or a test)."""
    params = params or {}
    return Config(
        catalog=params.get("catalog") or DEFAULT_CATALOG,
        raw_schema=params.get("raw_schema") or RAW_SCHEMA,
        curated_schema=params.get("curated_schema") or CURATED_SCHEMA,
        agent_schema=params.get("agent_schema") or AGENT_SCHEMA,
        gen_model=params.get("gen_model") or GEN_MODEL,
        default_target_vrr=float(params.get("target_vrr") or DEFAULT_TARGET_VRR),
    )


def from_widgets(dbutils) -> Config:  # pragma: no cover - needs Databricks runtime
    """Notebook entry point: read task widgets set by the Job."""
    def w(name: str, default: str) -> str:
        try:
            dbutils.widgets.text(name, default)
        except Exception:
            pass
        return dbutils.widgets.get(name) or default

    return load_config(
        {
            "catalog": w("catalog", DEFAULT_CATALOG),
            "raw_schema": w("raw_schema", RAW_SCHEMA),
            "curated_schema": w("curated_schema", CURATED_SCHEMA),
            "agent_schema": w("agent_schema", AGENT_SCHEMA),
            "gen_model": w("gen_model", GEN_MODEL),
            "target_vrr": w("target_vrr", str(DEFAULT_TARGET_VRR)),
        }
    )
