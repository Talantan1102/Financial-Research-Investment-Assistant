"""L0 — Writer prompt construction (v0.8.2 credit report rewrite)."""

from app.agents.schemas import Insight, ResearchPlan, ResearchState, Subtask
from app.agents.writer import build_credit_report_prompt


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
    prompt = build_credit_report_prompt(state)
    assert "银行公司金融部" in prompt
    assert "overview" in prompt
    assert "信贷调查报告" in prompt
    assert "CreditInvestigationReport" in prompt


def test_build_prompt_includes_user_message() -> None:
    state = _state_with_insights()
    prompt = build_credit_report_prompt(state)
    assert "m" in prompt
    assert "用户原始需求" in prompt
