"""Unit tests — Analyst prompt condition on investment_horizon + investment_objective.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 5.3
"""

from __future__ import annotations

import pytest
from app.agents.analyst import build_analyst_prompt
from app.agents.schemas import Insight, ResearchPlan, ResearchState, Subtask


def _make_state(**kwargs: object) -> ResearchState:
    defaults: dict[str, object] = {
        "user_id": "test",
        "session_id": "sess-1",
        "user_message": "请对贵州茅台进行投资分析。",
        "request_id": "req-1",
        "target_ts_code": "600519.SH",
        "client_total_aum": 10_000_000.0,
        "investment_objective": "balanced",
        "investment_horizon": "medium_term",
        "risk_tolerance": "moderate",
        "plan": ResearchPlan(
            plan_id="balanced",
            rationale="default test plan",
            subtasks=[
                Subtask(
                    subtask_id="sub-1",
                    description="行情分析",
                    required_tools=["get_stock_quote"],
                    rationale="获取最新行情",
                )
            ],
            target_entity="600519.SH",
            research_style="comprehensive",
            reasoning="基础分析",
        ),
        "insights": [
            Insight(
                subtask_id="sub-1",
                finding="茅台2024营收1782亿元,净利857亿元",
                supporting_data=[{"key": "revenue", "value": "1782亿"}],
                confidence="high",
            )
        ],
    }
    defaults.update(kwargs)
    return ResearchState(**defaults)  # type: ignore[arg-type]


def test_analyst_short_term_emphasizes_technical() -> None:
    """short_term 时 analyst prompt 应强调技术指标 / 资金流 / 短期动量。"""
    state = _make_state(
        investment_horizon="short_term",
        investment_objective="aggressive_growth",
    )
    prompt = build_analyst_prompt(state)
    # short_term 需包含技术/资金流相关词
    assert "技术" in prompt or "资金流" in prompt or "short_term" in prompt


def test_analyst_long_term_emphasizes_fundamentals() -> None:
    """long_term 时 analyst prompt 应强调基本面 / 行业地位 / 长期估值。"""
    state = _make_state(
        investment_horizon="long_term",
        investment_objective="stable_growth",
    )
    prompt = build_analyst_prompt(state)
    # long_term 需包含基本面/行业/长期相关词
    assert "基本面" in prompt or "行业" in prompt or "long_term" in prompt


def test_analyst_medium_term_balanced() -> None:
    """medium_term 时 analyst prompt 应包含均衡分析引导词。"""
    state = _make_state(
        investment_horizon="medium_term",
        investment_objective="balanced",
    )
    prompt = build_analyst_prompt(state)
    assert "medium_term" in prompt or "中期" in prompt or "均衡" in prompt


def test_analyst_capital_preservation_weights_risk() -> None:
    """capital_preservation 时 prompt 应加权风险维度。"""
    state = _make_state(
        investment_objective="capital_preservation",
        risk_tolerance="conservative",
    )
    prompt = build_analyst_prompt(state)
    assert "风险" in prompt or "capital_preservation" in prompt


def test_analyst_aggressive_growth_weights_growth() -> None:
    """aggressive_growth 时 prompt 应加权成长维度。"""
    state = _make_state(
        investment_objective="aggressive_growth",
        risk_tolerance="very_aggressive",
    )
    prompt = build_analyst_prompt(state)
    assert "成长" in prompt or "aggressive_growth" in prompt


def test_analyst_prompt_contains_subtask_info() -> None:
    """Analyst prompt 必须包含 plan subtask 描述。"""
    state = _make_state()
    prompt = build_analyst_prompt(state)
    # Plan subtask description "行情分析" should appear in prompt
    assert "行情分析" in prompt or "sub-1" in prompt


@pytest.mark.parametrize("horizon", ["short_term", "medium_term", "long_term"])
def test_analyst_all_horizons_return_nonempty_prompt(horizon: str) -> None:
    """所有 horizon 值都应返回非空 prompt。"""
    state = _make_state(investment_horizon=horizon)
    prompt = build_analyst_prompt(state)
    assert isinstance(prompt, str)
    assert len(prompt) > 100
