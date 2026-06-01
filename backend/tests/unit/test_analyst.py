"""L0 — Analyst prompt construction + Insight list parsing."""

from unittest.mock import MagicMock

import pytest
from app.agents.analyst import Analyst, build_analyst_prompt
from app.agents.schemas import (
    Insight,
    ResearchPlan,
    ResearchState,
    Subtask,
    ToolResult,
)
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state_with_data() -> ResearchState:
    plan = ResearchPlan(
        rationale="default test plan",
        subtasks=[
            Subtask(
                subtask_id="overview",
                description="d",
                required_tools=["get_stock_quote"],
                rationale="r",
            )
        ],
    )
    tr = ToolResult(
        tool_name="get_stock_quote",
        args={"ts_code": "600519.SH"},
        success=True,
        output={"price": 1820.5},
        latency_ms=300,
    )
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="req-test1234",
        plan=plan,
        tool_results=[tr],
    )


def test_build_prompt_includes_subtasks_and_data() -> None:
    state = _state_with_data()
    prompt = build_analyst_prompt(state)
    assert "你是金融研究助手 analyst" in prompt
    assert "overview" in prompt
    has_data = ("1820.5" in prompt) or ("get_stock_quote" in prompt)
    assert has_data
    assert "insights" in prompt


def test_analyst_step_returns_insights(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    analyst = Analyst(llm=svc)

    state = _state_with_data()
    sr = analyst.step(state)

    assert "insights" in sr.state_update
    insights = sr.state_update["insights"]
    n = len(insights)
    assert n >= 1
    all_insights = all(isinstance(i, Insight) for i in insights)
    assert all_insights


# ---------------------------------------------------------------------------
# C19 regression: _maybe_run_debate error handling
# ---------------------------------------------------------------------------


def _make_analyst_with_fake_llm() -> Analyst:
    """Build an Analyst with a stub LLM that requires no real service."""
    fake_llm = MagicMock()
    a = object.__new__(Analyst)
    a._llm = fake_llm
    return a


def test_maybe_run_debate_returns_none_on_llm_error() -> None:
    """C19: expected LLM/data failures (non-programming errors) → graceful None.

    Uses ValueError which is a plain Exception but not any of the re-raised
    programming-error types (TypeError / AttributeError / RuntimeError / ImportError).
    """
    analyst = _make_analyst_with_fake_llm()
    state = _state_with_data()

    # Simulate DebateOrchestrator.run raising a plain data/LLM error
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.agents.debate_orchestrator.DebateOrchestrator.run",
            MagicMock(side_effect=ValueError("LLM returned unexpected format")),
        )
        result = analyst._maybe_run_debate(state)

    assert result is None, "C19: ValueError (data error) must be swallowed gracefully"


def test_maybe_run_debate_propagates_type_error() -> None:
    """C19: TypeError (programming error) must NOT be swallowed — must propagate."""
    analyst = _make_analyst_with_fake_llm()
    state = _state_with_data()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.agents.debate_orchestrator.DebateOrchestrator.run",
            MagicMock(side_effect=TypeError("bad args")),
        )
        with pytest.raises(TypeError):
            analyst._maybe_run_debate(state)


def test_maybe_run_debate_propagates_attribute_error() -> None:
    """C19: AttributeError (programming error) must NOT be swallowed — must propagate."""
    analyst = _make_analyst_with_fake_llm()
    state = _state_with_data()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.agents.debate_orchestrator.DebateOrchestrator.run",
            MagicMock(side_effect=AttributeError("missing attr")),
        )
        with pytest.raises(AttributeError):
            analyst._maybe_run_debate(state)


def test_maybe_run_debate_propagates_runtime_error() -> None:
    """C19: RuntimeError (asyncio / infra error) must NOT be swallowed — must propagate."""
    analyst = _make_analyst_with_fake_llm()
    state = _state_with_data()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.agents.debate_orchestrator.DebateOrchestrator.run",
            MagicMock(side_effect=RuntimeError("event loop already running")),
        )
        with pytest.raises(RuntimeError):
            analyst._maybe_run_debate(state)
