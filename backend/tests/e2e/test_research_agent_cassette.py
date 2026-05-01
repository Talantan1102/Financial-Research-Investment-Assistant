"""L2 cassette — ResearchAgent end-to-end with real DashScope LLM, recorded via VCR.

Records ~8-12 real LLM round-trips per playback:
- 1 ResearchPlanner call
- 0 DataCollector (calls tools, not LLM directly — stub tools return hardcoded data,
  no LLM hops inside tools)
- 1 Analyst call
- 1 Writer call
- 5 Critic sub-agent calls (parallel via LangGraph Send API, each a separate LLM call)

Total: ~8 real LLM round-trips. Recorded once (~¥0.05-0.10); replays offline in <2s.

Design note — stub tools:
    StubQuoteTool / StubFinancialsTool / StubNewsTool / StubWebSearchTool /
    StubKbSearchTool return hardcoded data without calling LLM. This keeps the
    cassette focused on agent LLM calls only and avoids extra MockTushare /
    MockBocha LLM hops that would bloat the cassette and add ¥ cost.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.agents.analyst import Analyst
from app.agents.base import Agent
from app.agents.critic import Critic
from app.agents.critic_subagents.conciseness import ConcisenessScorer
from app.agents.critic_subagents.coverage import CoverageScorer
from app.agents.critic_subagents.factuality import FactualityScorer
from app.agents.critic_subagents.insight import InsightScorer
from app.agents.critic_subagents.structure import StructureScorer
from app.agents.data_collector import DataCollector
from app.agents.research_agent import ResearchAgent
from app.agents.research_planner import ResearchPlanner
from app.agents.writer import Writer
from app.orchestration.research_graph import build_research_graph
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from openai import OpenAI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Stub tools — return hardcoded data without LLM I/O
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class _StubQuoteTool(Tool):
    """Stub for get_stock_quote — no LLM I/O."""

    name = "get_stock_quote"
    description = "Return the latest daily price for a given A-share."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubQuoteArgs.model_validate(args.model_dump())
        return {
            "ts_code": validated.ts_code,
            "price": 1820.5,
            "change_pct": 0.52,
            "volume": 12345.0,
        }


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class _StubFinancialsTool(Tool):
    """Stub for get_financials — no LLM I/O."""

    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {
            "ts_code": validated.ts_code,
            "revenue": 1.5e11,
            "net_profit": 7.47e10,
            "roe": 0.32,
            "gross_margin": 0.92,
        }


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = Field(default=5, ge=1)
    days_back: int = Field(default=7, ge=1)


class _StubNewsTool(Tool):
    """Stub for get_news — no LLM I/O."""

    name = "get_news"
    description = "Return recent news items for a given A-share."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "title": "贵州茅台2024年营收同比增长15%",
                    "summary": "贵州茅台2024年年报显示营收稳健增长",
                    "date": "2025-04-01",
                }
            ]
        }


class _StubWebSearchArgs(BaseModel):
    query: str
    search_type: str = "news"
    count: int = Field(default=5, ge=1, le=20)


class _StubWebSearchTool(Tool):
    """Stub for mock_web_search — no LLM I/O."""

    name = "mock_web_search"
    description = "搜索网络获取最新资讯(stub)。"
    args_schema = _StubWebSearchArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "title": "茅台酱香系列酒销售持续放量",
                    "url": "https://example.com/news/1",
                    "snippet": "2025年茅台系列酒销售持续增长",
                }
            ]
        }


class _StubKbSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class _StubKbSearchTool(Tool):
    """Stub for mock_kb_search — no LLM I/O."""

    name = "mock_kb_search"
    description = "搜索内部知识库(stub)。"
    args_schema = _StubKbSearchArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {
            "items": [
                {
                    "title": "茅台基本面分析报告2024",
                    "content": "茅台具有强大的品牌护城河和定价权",
                    "score": 0.92,
                }
            ]
        }


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

    Agent prompts contain dynamic values (tool results with timestamps, costs,
    request_ids). Per feedback_cassette_dynamic_prompt_values lesson, match
    only on method+scheme+host+port+path — requests are matched in serial
    recording order which is deterministic for this sequential pipeline.
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
# Real OpenAI adapter (DashScope-compatible endpoint)
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
            max_tokens=1024,
        )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )


@pytest.fixture
def real_adapter() -> _Adapter:
    """Real OpenAI client adapter. HTTP intercepted by pytest-recording under
    cassette mode; live only under VCR_RECORD_MODE=once."""
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
async def test_research_agent_maotai_fundamental(real_adapter: _Adapter) -> None:
    """Full ResearchAgent graph: planner → collector (stubs) → analyst → writer → critic (x5).

    Validates the complete v0.5 research path:
    - ResearchPlanner decomposes the query into 2-5 subtasks
    - DataCollector executes stub tools (no extra LLM calls; cassette stays small)
    - Analyst synthesizes insights from tool results
    - Writer produces Markdown report
    - 5 Critic scorers run in parallel (via LangGraph Send API)
    """
    llm = LLMService(client=real_adapter)

    # Register all stub tools (no LLM I/O; keeps cassette focused on agent calls)
    registry = ToolRegistry()
    registry.register(_StubQuoteTool())
    registry.register(_StubFinancialsTool())
    registry.register(_StubNewsTool())
    registry.register(_StubWebSearchTool())
    registry.register(_StubKbSearchTool())

    # Assemble agents
    planner = ResearchPlanner(llm=llm)
    collector = DataCollector(llm=llm, registry=registry)
    analyst = Analyst(llm=llm)
    writer = Writer(llm=llm)
    scorers: list[Agent] = [
        FactualityScorer(llm=llm),
        CoverageScorer(llm=llm),
        InsightScorer(llm=llm),
        StructureScorer(llm=llm),
        ConcisenessScorer(llm=llm),
    ]
    critic = Critic(llm=llm, scorers=scorers)

    # Build stateless in-memory graph (no checkpointer for eval / cassette)
    graph = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=writer,
        critic=critic,
        db_path=None,
    )
    agent = ResearchAgent(graph=graph)

    output = await agent.run(
        user_input="深度分析贵州茅台(600519.SH)基本面",
        request_id="cassette-research-1",
    )

    assert output.response_text, "Writer must return a non-empty Markdown report"
    n_tool_calls = len(output.tool_calls)
    assert (
        n_tool_calls >= 1
    ), f"DataCollector must have executed at least 1 tool, got {output.tool_calls!r}"
    assert output.request_id == "cassette-research-1"
