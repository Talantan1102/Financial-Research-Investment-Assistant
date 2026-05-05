"""L0 — ResearchPlanner prompt construction + ResearchPlan parsing."""

import pytest
from app.agents.research_planner import ResearchPlanner, build_planner_prompt
from app.agents.schemas import ResearchPlan, ResearchState
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def _state(target: str, msg: str) -> ResearchState:
    return ResearchState(
        user_id="u",
        session_id="s",
        user_message=msg,
        request_id="req-test1234",
        target_ts_code=target,
    )


def test_build_prompt_includes_target_and_message() -> None:
    state = _state("600519.SH", "深度分析茅台基本面")
    prompt = build_planner_prompt(state)
    assert "你是金融研究助手 research_planner" in prompt
    assert "600519.SH" in prompt
    assert "深度分析茅台基本面" in prompt
    assert "subtasks" in prompt  # JSON schema mentioned


def test_planner_step_returns_plan(
    mock_llm_client: MockLLMClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = LLMService(client=mock_llm_client)
    planner = ResearchPlanner(llm=svc)

    state = _state("600519.SH", "深度分析茅台基本面")
    sr = planner.step(state)

    assert "plan" in sr.state_update
    plan = sr.state_update["plan"]
    assert isinstance(plan, ResearchPlan)
    n = len(plan.subtasks)
    assert n >= 1
