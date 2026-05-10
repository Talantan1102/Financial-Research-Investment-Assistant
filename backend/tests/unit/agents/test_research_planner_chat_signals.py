"""L0 — ResearchPlanner honors chat_known_tool_results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock

from app.agents.escalation_protocol import ToolResultRef
from app.agents.research_planner import ResearchPlanner
from app.agents.schemas import PlanId, ResearchPlan, ResearchState
from app.services.llm_response import LLMResponse


def _make_planner_with_llm(plan_id: PlanId = "balanced") -> ResearchPlanner:
    """Build a ResearchPlanner with a MagicMock LLM returning a fixed plan."""
    plan = ResearchPlan(plan_id=plan_id, rationale="test rationale")
    response = MagicMock(spec=LLMResponse)
    response.parsed = plan
    response.content = plan.model_dump_json()
    response.model = "qwen-plus"
    response.cost_cny = 0.001

    llm = MagicMock()
    llm.chat.return_value = response
    return ResearchPlanner(llm=llm)


def _get_prompt(planner: ResearchPlanner) -> str:
    """Extract the prompt string passed to LLM.chat from last call."""
    call_args = cast(MagicMock, planner._llm.chat).call_args
    return call_args.kwargs.get("prompt") or call_args.args[0]


def test_planner_prompt_lists_chat_known_tools() -> None:
    """When chat_known_tool_results is non-empty, prompt mentions them."""
    planner = _make_planner_with_llm()
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调 ICBC",
        request_id="r",
        chat_known_tool_results=[
            ToolResultRef(
                tool_name="get_stock_quote",
                tool_args={"ts_code": "601398.SH"},
                result_summary="6.45 元",
                cached_at=datetime.now(UTC),
                cache_id="c1",
            ),
        ],
    )
    planner.step(state)

    prompt = _get_prompt(planner)
    assert "get_stock_quote" in prompt
    assert "601398.SH" in prompt
    assert "6.45" in prompt
    # Some indication that LLM should skip cached results
    assert (
        "已查" in prompt
        or "跳过" in prompt
        or "no need" in prompt.lower()
        or "skip" in prompt.lower()
    )


def test_planner_prompt_omits_chat_block_when_empty() -> None:
    """When chat_known_tool_results is empty, prompt doesn't add empty section."""
    planner = _make_planner_with_llm()
    state = ResearchState(
        user_id="u",
        session_id="s",
        user_message="尽调 ICBC",
        request_id="r",
        chat_known_tool_results=[],
    )
    planner.step(state)

    prompt = _get_prompt(planner)
    # User message should still appear in prompt
    assert "尽调 ICBC" in prompt
    # Empty chat_known should not produce an "已查" section marker
    assert "已查过的工具结果" not in prompt
