"""L0 — Analyst prompt construction + Insight list parsing."""

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
