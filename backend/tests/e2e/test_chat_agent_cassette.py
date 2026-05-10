"""L2 cassette — ChatAgent end-to-end with real DashScope LLM, recorded via VCR.

This test exercises the full ChatAgent path with a REAL LLM:
1. ChatPlanner LLM call (returns Plan JSON for tool selection)
2. LegacyMockTushareAdapter (delegates to MockTushareService LLM call) inside the tool
3. Responder LLM call (synthesizes final reply)

Total: ~3 real LLM round-trips per cassette playback. Recorded once, replayed
offline in CI for ~< 1s, no real cost after the first record.

Design note — get_news uses a stub (not MockBochaService):
    ``app.service.__init__`` re-exports legacy modules that import
    ``llama_index`` (not installed in venv). A direct
    ``from app.service.mock_bocha_service import ...`` triggers that
    ``__init__``.  Since the planner is called with "查股价", it should
    pick ``get_stock_quote`` (not ``get_news``), so a stub news tool that
    returns an empty list satisfies both the registry contract and the test
    assertion without pulling in the legacy import chain.

Cassette note (v0.8.3 Task 4 Protocol migration):
    The cassette was recorded with LegacyMockTushareAdapter, which internally
    calls MockTushareService.generate_daily_data (an LLM round-trip). This
    test is skipped pending Task 19 e2e cassette refresh because
    LegacyMockTushareAdapter._ensure_inner() triggers build_llm_service_from_env()
    on first method call, making additional HTTP calls that don't match the
    old 3-call cassette. The previous cassette was silently green because tool
    execution failures (AttributeError on Protocol method names) were swallowed
    into ToolResult(success=False), and the assertion only inspected the planner's
    plan (not execution success).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.orchestration.chat_graph import build_chat_graph
from app.services.llm_service import LLMService
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.base import Tool
from app.tools.get_financials import GetFinancialsTool
from app.tools.get_stock_quote import StockQuoteTool
from app.tools.registry import ToolRegistry
from openai import OpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Stub news tool — avoids MockBochaService / llama_index import chain
# ---------------------------------------------------------------------------


class _NewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = Field(default=5, ge=1)
    days_back: int = Field(default=7, ge=1)


class _StubNewsTool(Tool):
    """Stub for get_news: returns an empty list without any I/O.

    Prevents the app.service.__init__ legacy import chain from triggering
    llama_index at collection time.  The planner should not select get_news
    for a "查股价" query, so this stub is never actually invoked.
    """

    name = "get_news"
    description = (
        "Return recent news items for a given A-share (ts_code) or "
        "general market news when ts_code is omitted. n: number of items (default 5)."
    )
    args_schema = _NewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"items": []}


# ---------------------------------------------------------------------------
# VCR config (module-scoped)
# ---------------------------------------------------------------------------


def _strip_dashscope_response_headers(response: dict[str, Any]) -> dict[str, Any]:
    """Remove DashScope-specific response headers before recording."""
    headers = response.get("headers", {})
    response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
    return response


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """Override module-level VCR config: drop body from match criteria.

    The tool prompts contain dynamic values (dates from datetime.now()) that
    change between recording and replay.  Per feedback_cassette_dynamic_prompt_values
    lesson, match only on method+scheme+host+port+path — requests are matched
    in serial recording order which is deterministic for this 3-call pipeline.
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path"],
        "before_record_response": _strip_dashscope_response_headers,
    }


# ---------------------------------------------------------------------------
# Real OpenAI adapter
# ---------------------------------------------------------------------------


class _Raw:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Adapter:
    """OpenAI-compatible adapter with capped max_tokens to control cost."""

    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt: str, model: str, schema: object) -> _Raw:
        r = self._c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )


@pytest.fixture
def real_adapter() -> _Adapter:
    """Real OpenAI client adapter. HTTP intercepted by pytest-recording under
    cassette mode; live only under VCR_RECORD_MODE=once.
    """
    return _Adapter(
        OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "fake-for-replay"),
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )


# ---------------------------------------------------------------------------
# Cassette test
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "needs re-record after v0.8.3 Task 4 Protocol migration; "
        "previous cassette was silently green because tools called Protocol method names "
        "(get_daily etc.) on MockTushareService directly — which has generate_daily_data "
        "etc. instead — raising AttributeError swallowed into ToolResult(success=False). "
        "Cassette refresh deferred to Task 19 e2e refresh."
    )
)
@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chat_agent_stock_quote_end_to_end(real_adapter: _Adapter) -> None:
    """Full ChatAgent graph: planner → tool (LegacyMockTushareAdapter) → responder.

    Validates the complete v0 chat path:
    - ChatPlanner parses Plan JSON with at least one tool_call
    - ToolRegistry executes get_stock_quote via LegacyMockTushareAdapter
    - All tool executions succeed (no ToolResult with success=False)
    - Responder synthesizes a Chinese reply mentioning the stock
    """
    from app.agents.schemas import GraphState, ToolResult

    llm = LLMService(client=real_adapter)
    # Use LegacyMockTushareAdapter — satisfies TushareService Protocol and
    # delegates to MockTushareService.generate_daily_data etc. on first call.
    tushare = LegacyMockTushareAdapter()

    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare))
    registry.register(GetFinancialsTool(tushare=tushare))
    registry.register(_StubNewsTool())

    planner = ChatPlanner(llm=llm, registry=registry)
    responder = Responder(llm=llm)

    from app.agents.in_session_memory import InSessionMemory
    from app.services.tool_result_cache import ToolResultCache

    graph = build_chat_graph(
        planner=planner,
        responder=responder,
        registry=registry,
        memory=InSessionMemory(),
        cache=ToolResultCache(),
    )

    # Run the full graph directly to capture tool_results from GraphState.
    # (ChatAgent.run() returns SUTOutput with tool_calls from the plan, not
    # tool_results — so we use graph.ainvoke directly here to get both.)
    from langchain_core.runnables import RunnableConfig

    config: RunnableConfig = {"configurable": {"thread_id": "eval:cassette-test-1"}}
    initial = GraphState(
        user_id="eval",
        session_id="cassette-test-1",
        user_message="查一下 600519.SH 的股价",
        request_id="cassette-test-1",
        trace_request_id="cassette-test-1",
    )
    final = await graph.ainvoke(initial.model_dump(), config=config)

    assert final.get("final_response"), "Responder must return a non-empty reply"

    plan = final.get("plan")
    assert plan is not None, "ChatPlanner must produce a plan"
    assert len(plan.tool_calls) >= 1, "ChatPlanner must have called at least one tool"
    tool_names = [tc.tool_name for tc in plan.tool_calls]
    assert "get_stock_quote" in tool_names, f"tool_calls={tool_names!r}"

    # Assert tool execution actually succeeded — guards against silent swallow of
    # AttributeError into ToolResult(success=False) when Protocol method names
    # don't match the underlying mock's method names.
    tool_results: list[ToolResult] = final.get("tool_results", [])
    assert tool_results, "tool_node must have populated tool_results"
    failed = [r for r in tool_results if not r.success]
    assert not failed, (
        f"Some tools failed execution: {[(r.tool_name, r.error) for r in failed]}. "
        "This indicates the tushare adapter does not implement TushareService Protocol "
        "methods correctly (e.g. get_daily vs generate_daily_data name mismatch)."
    )
