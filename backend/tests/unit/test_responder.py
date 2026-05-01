"""L0 — Responder prompt construction + step integration."""

import pytest
from app.agents.responder import Responder, build_responder_prompt
from app.agents.schemas import GraphState, ToolResult
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state(msg: str, tool_results: list[ToolResult] | None = None) -> GraphState:
    return GraphState(
        user_id="u",
        session_id="s",
        user_message=msg,
        request_id="req-test-resp",
        tool_results=tool_results or [],
    )


def test_build_responder_prompt_includes_user_message_and_tool_results() -> None:
    """build_responder_prompt embeds user_message and tool result data."""
    tr = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=True,
        output={"price": 1820.5},
        latency_ms=42,
    )
    state = _state("茅台股价?", tool_results=[tr])
    prompt = build_responder_prompt(state=state)

    assert "茅台股价" in prompt
    assert "get_stock_quote" in prompt
    assert "1820.5" in prompt


def test_build_responder_prompt_handles_tool_failure() -> None:
    """build_responder_prompt mentions failure when a ToolResult has success=False."""
    tr = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "INVALID"},
        success=False,
        error="symbol not found",
        latency_ms=10,
    )
    state = _state("无效股票?", tool_results=[tr])
    prompt = build_responder_prompt(state=state)

    # The prompt should surface the failure info
    assert "get_stock_quote" in prompt
    assert "symbol not found" in prompt or "失败" in prompt or "error" in prompt.lower()


def test_responder_step_returns_final_response(
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_client: MockLLMClient,
) -> None:
    """step() returns StepResult with final_response populated from mock fixture."""
    monkeypatch.setenv("LLM_MODE", "mock")

    svc = LLMService(client=mock_llm_client)
    responder = Responder(llm=svc)

    tr = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=True,
        output={"price": 1820.5},
        latency_ms=50,
    )
    state = _state("茅台股价?", tool_results=[tr])
    result = responder.step(state)

    assert "final_response" in result.state_update
    final = result.state_update["final_response"]
    assert isinstance(final, str) and len(final) > 0
    assert result.span_metadata["agent"] == "Responder"
    assert "cost_cny" in result.span_metadata
