"""L2 cassette — ChatAgent end-to-end with real DashScope LLM, recorded via VCR.

This test exercises the full ChatAgent path with a REAL LLM:
1. ChatPlanner LLM call (returns Plan JSON for tool selection)
2. MockTushareService LLM call inside the tool (mock data generation)
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
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.agents.chat_agent import ChatAgent
from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.orchestration.chat_graph import build_chat_graph
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.get_financials import GetFinancialsTool
from app.tools.get_stock_quote import StockQuoteTool
from app.tools.registry import ToolRegistry
from openai import OpenAI
from pydantic import BaseModel, Field

# NOTE: MockTushareService is imported lazily inside the test function.
# ``app.service.__init__`` chains into legacy modules that require llama_index
# (not installed).  A top-level import triggers __init__ and breaks collection.
# Lazy import avoids the __init__ execution path entirely.

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


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_chat_agent_stock_quote_end_to_end(real_adapter: _Adapter) -> None:
    """Full ChatAgent graph: planner → tool (MockTushare LLM call) → responder.

    Validates the complete v0 chat path:
    - ChatPlanner parses Plan JSON with at least one tool_call
    - ToolRegistry executes get_stock_quote (which calls MockTushare LLM)
    - Responder synthesizes a Chinese reply mentioning the stock
    """
    # Direct module load: avoids app.service.__init__ import chain.
    # ``importlib.util.spec_from_file_location`` loads the module file
    # directly without executing app/service/__init__.py (which pulls in
    # legacy llama_index / embedding_service not installed in this venv).
    import importlib.util
    from pathlib import Path

    _spec = importlib.util.spec_from_file_location(
        "app.service.mock_tushare_service",
        Path(__file__).parent.parent.parent / "app" / "service" / "mock_tushare_service.py",
    )
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    MockTushareService = _mod.MockTushareService

    llm = LLMService(client=real_adapter)
    mock_tushare = MockTushareService(llm=llm)

    registry = ToolRegistry()
    registry.register(StockQuoteTool(mock_tushare=mock_tushare))
    registry.register(GetFinancialsTool(mock_tushare=mock_tushare))
    registry.register(_StubNewsTool())

    planner = ChatPlanner(llm=llm, registry=registry)
    responder = Responder(llm=llm)

    graph = build_chat_graph(planner=planner, responder=responder, registry=registry)
    agent = ChatAgent(graph=graph)

    output = await agent.run(
        user_input="查一下 600519.SH 的股价",
        request_id="cassette-test-1",
    )

    assert output.response_text, "Responder must return a non-empty reply"
    assert len(output.tool_calls) >= 1, "ChatPlanner must have called at least one tool"
    tool_names = [tc.tool_name for tc in output.tool_calls]
    assert "get_stock_quote" in tool_names, f"tool_calls={tool_names!r}"
