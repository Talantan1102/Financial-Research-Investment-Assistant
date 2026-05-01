"""L0 — ChatPlanner prompt construction + Plan parsing."""

import pytest
from app.agents.chat_planner import ChatPlanner, _parse_plan, build_planner_prompt
from app.agents.schemas import GraphState, Plan, ToolCall
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.tools.get_stock_quote import StockQuoteTool
from app.tools.registry import ToolRegistry


def _state(msg: str) -> GraphState:
    return GraphState(user_id="u", session_id="s", user_message=msg, request_id="req-test1234")


def test_build_prompt_includes_tools() -> None:
    """build_planner_prompt injects tool name + schema hint + user message."""
    reg = ToolRegistry()
    reg.register(StockQuoteTool(mock_tushare=None))
    prompt = build_planner_prompt(state=_state("茅台股价?"), registry=reg)
    assert "茅台股价" in prompt
    assert "get_stock_quote" in prompt
    assert "tool_calls" in prompt  # JSON output schema mentioned


def test_build_prompt_includes_system_role() -> None:
    """build_planner_prompt includes the Chinese system role prefix."""
    reg = ToolRegistry()
    prompt = build_planner_prompt(state=_state("test"), registry=reg)
    assert "金融研究助手 planner" in prompt


def test_parse_plan_plain_json() -> None:
    """_parse_plan handles plain JSON without code fences."""
    content = '{"tool_calls":[{"tool_name":"get_stock_quote","args":{"ts_code":"600519.SH"},"rationale":"user asked"}],"direct_response":false,"reasoning":"single tool"}'
    plan = _parse_plan(content)
    assert isinstance(plan, Plan)
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].tool_name == "get_stock_quote"
    assert plan.direct_response is False


def test_parse_plan_with_code_fences() -> None:
    """_parse_plan strips ```json...``` fences before validating."""
    content = (
        "```json\n"
        '{"tool_calls":[{"tool_name":"get_stock_quote","args":{"ts_code":"000001.SZ"},"rationale":"test"}],'
        '"direct_response":false,"reasoning":"fenced"}\n'
        "```"
    )
    plan = _parse_plan(content)
    assert isinstance(plan, Plan)
    assert plan.tool_calls[0].args["ts_code"] == "000001.SZ"


def test_parse_plan_direct_response() -> None:
    """_parse_plan accepts direct_response=true with no tool_calls."""
    content = '{"tool_calls":[],"direct_response":true,"reasoning":"no tool needed"}'
    plan = _parse_plan(content)
    assert plan.direct_response is True
    assert plan.tool_calls == []


def test_parse_plan_invalid_json_raises() -> None:
    """_parse_plan raises ValueError (JSONDecodeError) on malformed input."""
    with pytest.raises((ValueError, Exception)):
        _parse_plan("not json at all")


def test_chat_planner_step_returns_plan(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: MockLLMClient,
) -> None:
    """step() returns StepResult with a valid Plan populated from mock fixture."""
    monkeypatch.setenv("LLM_MODE", "mock")

    svc = LLMService(client=mock_llm_client)
    reg = ToolRegistry()
    reg.register(StockQuoteTool(mock_tushare=None))

    planner = ChatPlanner(llm=svc, registry=reg)
    result = planner.step(_state("茅台股价?"))

    plan = result.state_update["plan"]
    assert isinstance(plan, Plan)
    assert len(plan.tool_calls) == 1
    tc: ToolCall = plan.tool_calls[0]
    assert tc.tool_name == "get_stock_quote"
    assert tc.args == {"ts_code": "600519.SH"}
    assert plan.direct_response is False
    assert result.span_metadata["agent"] == "ChatPlanner"
    assert "cost_cny" in result.span_metadata
