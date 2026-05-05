"""Unit tests — ResearchPlanner 4 plan templates route by investment_objective.

Step 1: failing (build_planner_prompt does not yet accept state / templates don't exist)
Step 4: passing after implementation in research_planner.py.
"""

from __future__ import annotations

import pytest
from app.agents.research_planner import build_planner_prompt
from app.agents.schemas import ResearchState


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资尽调。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


def test_planner_uses_capital_preservation_template() -> None:
    """capital_preservation 模板必须 emphasize 风险 + 保本关键词。"""
    state = _make_state(
        investment_objective="capital_preservation",
        investment_horizon="long_term",
        risk_tolerance="conservative",
    )
    prompt = build_planner_prompt(state)
    # 模板头部必须引用 objective 类型
    assert "capital_preservation" in prompt or "保本" in prompt
    # capital_preservation 模板偏重风险数据
    assert "风险" in prompt


def test_planner_uses_stable_growth_template() -> None:
    """stable_growth 模板必须 emphasize 基本面 + 股息关键词。"""
    state = _make_state(
        investment_objective="stable_growth",
        investment_horizon="long_term",
        risk_tolerance="moderate",
    )
    prompt = build_planner_prompt(state)
    assert "stable_growth" in prompt or "稳健增长" in prompt or "稳健" in prompt
    # stable_growth 偏重稳健 / 股息 / 基本面
    assert "基本面" in prompt or "股息" in prompt or "分红" in prompt


def test_planner_uses_balanced_template() -> None:
    """balanced 模板必须 emphasize 均衡分析。"""
    state = _make_state(
        investment_objective="balanced",
        investment_horizon="medium_term",
        risk_tolerance="balanced",
    )
    prompt = build_planner_prompt(state)
    assert "balanced" in prompt or "均衡" in prompt


def test_planner_uses_aggressive_growth_template() -> None:
    """aggressive_growth 模板必须 emphasize 成长 + 估值关键词。"""
    state = _make_state(
        investment_objective="aggressive_growth",
        investment_horizon="short_term",
        risk_tolerance="aggressive",
    )
    prompt = build_planner_prompt(state)
    # aggressive_growth 模板必须 emphasize 成长 + 估值
    assert "成长" in prompt or "growth" in prompt
    assert "估值" in prompt or "valuation" in prompt


def test_planner_prompt_contains_horizon() -> None:
    """所有模板都应在 prompt 中明确引用 investment_horizon。"""
    for horizon in ("short_term", "medium_term", "long_term"):
        state = _make_state(investment_horizon=horizon)
        prompt = build_planner_prompt(state)
        assert horizon in prompt or "投资期限" in prompt, (
            f"Prompt missing horizon reference for {horizon}"
        )


def test_planner_prompt_contains_ts_code() -> None:
    """Prompt 应包含 target_ts_code(让 planner 知道目标标的)。"""
    state = _make_state(target_ts_code="600519.SH")
    prompt = build_planner_prompt(state)
    assert "600519.SH" in prompt


@pytest.mark.parametrize(
    "objective",
    ["capital_preservation", "stable_growth", "balanced", "aggressive_growth"],
)
def test_planner_all_objectives_return_string(objective: str) -> None:
    """所有 4 个 objective 值都应返回非空字符串 prompt。"""
    state = _make_state(investment_objective=objective)
    prompt = build_planner_prompt(state)
    assert isinstance(prompt, str)
    assert len(prompt) > 100
