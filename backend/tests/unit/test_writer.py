"""L0 — Writer prompt construction + markdown + chart_specs parsing."""

import pytest
from app.agents.schemas import Insight, ResearchPlan, ResearchState, Subtask
from app.agents.writer import Writer, build_writer_prompt
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state_with_insights() -> ResearchState:
    plan = ResearchPlan(
        subtasks=[
            Subtask(subtask_id="overview", description="d", required_tools=[], rationale="r")
        ],
        target_entity="600519.SH",
        research_style="comprehensive",
        reasoning="r",
    )
    insights = [Insight(subtask_id="overview", finding="x", supporting_data=[], confidence="high")]
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message="m",
        request_id="req-test1234",
        plan=plan,
        insights=insights,
    )


def test_build_prompt_includes_insights() -> None:
    state = _state_with_insights()
    prompt = build_writer_prompt(state)
    assert "你是金融研究助手 writer" in prompt
    assert "overview" in prompt
    assert "chart_id" in prompt
    assert "chart://" in prompt


def test_writer_step_returns_markdown(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    writer = Writer(llm=svc)

    state = _state_with_insights()
    sr = writer.step(state)

    md = sr.state_update["report_markdown"]
    assert isinstance(md, str)
    n = len(md)
    assert n > 50, f"report markdown too short ({n} chars)"
    chart_specs = sr.state_update.get("chart_specs", [])
    assert isinstance(chart_specs, list)
