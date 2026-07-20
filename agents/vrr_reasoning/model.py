"""Servable MLflow ChatAgent for the VRR Reasoning & Lineage agent.

Deployable form of src/vrr_agent/agent.py, wrapped as an `mlflow.pyfunc.ChatAgent`
so it can be logged, registered to Unity Catalog, and served (agents.deploy).

Model Serving has no Spark, so retrieval goes through a SQL warehouse via
databricks-sql-connector (tools.SqlWarehouseData) — same pattern as the CDP stub
agents. The VRR module code (physics/tools/agent/config) is shipped via `code_paths`
at log time (see notebooks/agents/deploy_vrr_agent.py). The LLM plans + narrates;
every number comes from the deterministic tools with provenance.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Generator, Optional

import mlflow
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import ChatAgentChunk, ChatAgentMessage, ChatAgentResponse

# The VRR package is shipped via `code_paths=[.../src/vrr_agent]` at log time, so at
# serving load it imports as top-level `vrr_agent`. Fall back to the repo layout
# (`src.vrr_agent`) when running from the repo (tests / local).
try:
    from vrr_agent import config as cfg_mod, tools as T, agent as A
except ImportError:  # pragma: no cover
    from src.vrr_agent import config as cfg_mod, tools as T, agent as A

CFG = cfg_mod.load_config({"catalog": os.environ.get("CDP_CATALOG", "cdp_dev")})
GEN_MODEL = os.environ.get("CDP_GEN_MODEL", cfg_mod.GEN_MODEL)
HTTP_PATH = os.environ.get("CDP_WAREHOUSE_HTTP_PATH", "")
MAX_TOOL_STEPS = 6

# Tool-calling system prompt = the trust rules (agent.SYSTEM_PROMPT) + how to plan
# the tool calls. The LLM ORCHESTRATES (chooses tools) but never computes: numbers
# come only from the deterministic tools, and check_faithfulness gates the answer.
SYSTEM_PROMPT = A.SYSTEM_PROMPT + """

TOOL PLAN — pick tools by question type (don't demand exact inputs the tools can find):
- DISCOVERY ("what patterns exist?", "what periods are loaded?", user names no pattern):
  call VRR_LIST_PATTERNS. Present the patterns + their date ranges, and offer to drill in.
- PORTFOLIO ("which patterns are over/under-replacing?", "give me a summary", "worst
  patterns"): call VRR_OVERVIEW (omit date for each pattern's latest) and rank by drift.
- SPECIFIC "what is the VRR" for a named pattern/period: VRR_GET.
- "WHY did it change": VRR_GET first (returns prior_date), then VRR_DECOMPOSE(date_a=
  prior_date, date_b=asked date), then optionally VRR_LINEAGE for proof.
- IMPACT / WHAT-IF ("if this pressure/PVT/volume/factor changed, which VRRs move?",
  "what depends on this input?"): VRR_IMPACT with the input_type + its keys.
- "TRACE / PROVE this VRR to its raw inputs": VRR_LINEAGE_GRAPH (persisted graph) or
  VRR_LINEAGE (on-the-fly tree with per-node values).
- "HOW is VRR calculated / methodology / show the SQL or pseudo-code": call
  VRR_EXPLAIN_CALC to fetch the ACTUAL logged build SQL, then explain THAT text in
  plain English + pseudo-code (optionally cite real numbers via VRR_GET/VRR_LINEAGE).
  NEVER describe the calculation from memory — only from the returned sql_text.
- Prefer to EXPLORE with VRR_LIST_PATTERNS / VRR_OVERVIEW rather than asking the user for
  an exact id. Only ask a clarifying question if discovery returns nothing usable. If the
  user gives just a pattern with no date, use its latest period (from VRR_LIST_PATTERNS).
"""


def _text(content) -> str:
    """Normalize a chat message's `content` (str, or Claude's list-of-blocks) to text."""
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""


def _connect():  # pragma: no cover - needs a warehouse
    # In Model Serving there are no SP client-id/secret env vars, so
    # oauth_service_principal() returns None (-> "'NoneType' object is not
    # callable"). Use the SDK's default auth chain, which resolves the serving
    # endpoint's auto-provisioned token (the SQL warehouse + curated tables must be
    # declared as model resources at deploy time so that token is scoped to them).
    from databricks import sql
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    host = (w.config.host or "").replace("https://", "").replace("http://", "")
    return sql.connect(server_hostname=host, http_path=HTTP_PATH,
                       credentials_provider=lambda: w.config.authenticate)


class VRRAgent(ChatAgent):
    def __init__(self):
        self._data: Optional[T.DataAccess] = None

    def _dl(self) -> T.DataAccess:
        if self._data is None:
            self._data = T.SqlWarehouseData(_connect, CFG)
        return self._data

    @mlflow.trace(span_type="TOOL")
    def _run_tool(self, name: str, args: dict) -> dict:
        """Execute one deterministic tool call (traced so the loop is visible)."""
        return T.call_tool(self._dl(), name, args)

    @mlflow.trace(span_type="LLM")
    def _llm(self, messages: list[dict], with_tools: bool = True) -> dict:
        from mlflow.deployments import get_deploy_client
        inputs = {"messages": messages, "max_tokens": 800}  # no temperature: sonnet-5 rejects it
        if with_tools:
            inputs["tools"] = T.TOOL_SPECS
        return get_deploy_client("databricks").predict(endpoint=GEN_MODEL, inputs=inputs)["choices"][0]["message"]

    def _answer(self, question: str) -> str:
        # Broad guard so a missing warehouse (e.g. mlflow's log-time validation call)
        # degrades to a message instead of erroring the endpoint.
        try:
            return self._turn(question)
        except Exception as e:  # pragma: no cover
            return f"Sorry — I couldn't complete the VRR analysis ({type(e).__name__})."

    @mlflow.trace(name="vrr_agent_turn")
    def _turn(self, question: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question}]
        last_decompose = None
        for _ in range(MAX_TOOL_STEPS):
            msg = self._llm(messages)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                answer = _text(msg.get("content"))
                return self._gate(answer, last_decompose, messages)
            # echo the assistant tool-call turn, then append each tool result
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self._run_tool(fn["name"], args)
                if fn["name"] == "VRR_DECOMPOSE" and result.get("ok"):
                    last_decompose = result
                messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                                 "content": json.dumps(result, default=str)})
        return "I couldn't complete the analysis within the tool budget — please narrow the question."

    @mlflow.trace(span_type="AGENT")
    def _gate(self, answer: str, decompose: Optional[dict], messages: list[dict]) -> str:
        """Attribution-faithfulness gate on the final narration (one bounded retry)."""
        if not decompose:
            return answer
        faith = A.check_faithfulness(answer, decompose, {})
        if faith["ok"]:
            return answer
        messages.append({"role": "user", "content":
                         "Revise: name the dominant driver the decomposition supports "
                         f"({faith.get('dominant')}). Issues: {faith['violations']}"})
        return _text(self._llm(messages, with_tools=False).get("content"))

    def predict(self, messages: list[ChatAgentMessage], context=None,
                custom_inputs=None) -> ChatAgentResponse:
        question = next((m.content for m in reversed(messages) if m.role == "user"), "")
        answer = self._answer(question)
        # ChatAgentMessage requires a unique id (mlflow ChatAgent contract).
        return ChatAgentResponse(
            messages=[ChatAgentMessage(role="assistant", content=answer, id=str(uuid.uuid4()))])

    def predict_stream(self, messages: list[ChatAgentMessage], context=None,
                       custom_inputs=None) -> Generator[ChatAgentChunk, None, None]:
        # The agent isn't token-streaming internally (tool loop), so emit the final
        # answer as a single chunk. Required or streaming clients (Review App) 500.
        resp = self.predict(messages, context, custom_inputs)
        for m in resp.messages:
            yield ChatAgentChunk(delta=m)


mlflow.models.set_model(VRRAgent())
