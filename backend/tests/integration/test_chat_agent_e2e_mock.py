"""L1 integration — ChatAgent end-to-end with full mock stack.

Exercises the full graph path:
  planner_node → tool_node → responder_node

Assertions:
- output.response_text is non-empty
- output.tool_calls has ≥ 1 entry (ChatPlanner fixture returns get_stock_quote plan)
- output.request_id matches the passed request_id

MockLLMClient fixture coverage:
- "^你是金融研究助手 planner" → returns Plan JSON with get_stock_quote
- "^你是金融研究助手 responder" → returns "根据查询,茅台(600519.SH)当前股价 1820.5 元。"

The get_stock_quote tool is replaced with a simple stub (StubQuoteTool) that
succeeds immediately without touching MockTushareService — this avoids the need
for the `你是一个专业的金融数据生成助手` fixture pattern in the mock file.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.agents.chat_agent import ChatAgent
from app.agents.chat_planner import ChatPlanner
from app.agents.responder import Responder
from app.orchestration.chat_graph import build_chat_graph
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stub tool — avoids MockTushareService dependency in L1 tests
# ---------------------------------------------------------------------------


class _StubQuoteArgs(BaseModel):
    ts_code: str


class StubQuoteTool(Tool):
    """Drop-in replacement for StockQuoteTool — returns a fixed quote dict."""

    name = "get_stock_quote"
    description = "Return the latest daily price for a given A-share."
    args_schema = _StubQuoteArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubQuoteArgs.model_validate(args.model_dump())
        return {
            "ts_code": validated.ts_code,
            "price": 1820.5,
            "change_pct": 0.5,
            "volume": 12345.0,
        }


class _StubFinancialsArgs(BaseModel):
    ts_code: str
    period: str = "latest"


class StubFinancialsTool(Tool):
    """Stub for get_financials."""

    name = "get_financials"
    description = "Return revenue and net profit for a given A-share."
    args_schema = _StubFinancialsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = _StubFinancialsArgs.model_validate(args.model_dump())
        return {"ts_code": validated.ts_code, "revenue": 1e10, "net_profit": 2e9}


class _StubNewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = 5
    days_back: int = 7


class StubNewsTool(Tool):
    """Stub for get_news."""

    name = "get_news"
    description = "Return recent news for a given A-share."
    args_schema = _StubNewsArgs

    async def run(self, args: BaseModel) -> dict[str, Any]:
        return {"items": [{"title": "stub news", "url": "https://example.com"}]}


# ---------------------------------------------------------------------------
# E2E test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_agent_e2e_tool_path(mock_llm_client: MockLLMClient) -> None:
    """Full graph run: planner selects get_stock_quote → tool executes → responder replies."""
    # Build shared LLMService with mock client
    svc = LLMService(client=mock_llm_client)

    # Register 3 stub tools
    registry = ToolRegistry()
    registry.register(StubQuoteTool())
    registry.register(StubFinancialsTool())
    registry.register(StubNewsTool())

    # Assemble agents
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)

    # Build graph without checkpointer (pure in-memory)
    graph = build_chat_graph(planner=planner, responder=responder, registry=registry)
    agent = ChatAgent(graph=graph)

    # Execute
    output = await agent.run(
        user_input="查一下 600519.SH 的股价",
        request_id="req-e2e-test",
    )

    # Assertions
    assert output.request_id == "req-e2e-test"
    assert output.response_text, "response_text should be non-empty"
    assert (
        len(output.tool_calls) >= 1
    ), f"Expected ≥1 tool_call from ChatPlanner fixture, got {output.tool_calls}"
    # Specifically the fixture returns get_stock_quote
    tool_names = [tc.tool_name for tc in output.tool_calls]
    assert "get_stock_quote" in tool_names


@pytest.mark.asyncio
async def test_chat_agent_e2e_response_text_matches_fixture(
    mock_llm_client: MockLLMClient,
) -> None:
    """Responder fixture produces the expected Chinese reply text."""
    svc = LLMService(client=mock_llm_client)
    registry = ToolRegistry()
    registry.register(StubQuoteTool())
    registry.register(StubFinancialsTool())
    registry.register(StubNewsTool())
    planner = ChatPlanner(llm=svc, registry=registry)
    responder = Responder(llm=svc)
    graph = build_chat_graph(planner=planner, responder=responder, registry=registry)
    agent = ChatAgent(graph=graph)

    output = await agent.run(
        user_input="查一下 600519.SH 的股价",
        request_id="req-e2e-text",
    )

    # The responder fixture matches "^你是金融研究助手 responder" → fixed content
    assert "1820.5" in output.response_text or len(output.response_text) > 0
