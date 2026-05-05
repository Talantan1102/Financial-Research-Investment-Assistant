"""Unit tests — Writer calc_recommended_position_size_pct + 6-field prompt conditioning.

spec ref: docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md § 5.3
"""

from __future__ import annotations

import pytest
from app.agents.schemas import ResearchState
from app.agents.writer import build_investment_dd_prompt, calc_recommended_position_size_pct


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


# ---------------------------------------------------------------------------
# Tests for calc_recommended_position_size_pct
# ---------------------------------------------------------------------------


def test_position_size_for_conservative_long_term() -> None:
    """保守 + 长期 + 买入建议 = 仓位上限较低(≤ 10%)。"""
    pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="conservative",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert 0 < pct <= 10.0, f"Expected conservative position ≤ 10%, got {pct}"


def test_position_size_for_aggressive_short_term() -> None:
    """激进 + 买入建议 = 仓位上限较高(10% < pct ≤ 30%)。"""
    pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="very_aggressive",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert 10.0 < pct <= 30.0, f"Expected aggressive position 10-30%, got {pct}"


def test_position_size_for_moderate_balanced() -> None:
    """moderate / balanced 仓位应在 conservative 和 aggressive 之间。"""
    conservative_pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="conservative",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    moderate_pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    aggressive_pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="very_aggressive",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert conservative_pct <= moderate_pct <= aggressive_pct, (
        f"Expected conservative({conservative_pct}) ≤ moderate({moderate_pct}) "
        f"≤ aggressive({aggressive_pct})"
    )


def test_position_size_sell_recommendation_is_zero_or_small() -> None:
    """卖出建议时仓位应为 0。"""
    pct = calc_recommended_position_size_pct(
        recommendation="recommend_sell",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert pct == 0.0, f"Sell recommendation should yield 0% position, got {pct}"


def test_position_size_hold_is_between_buy_and_sell() -> None:
    """持有建议仓位应低于买入。"""
    buy_pct = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    hold_pct = calc_recommended_position_size_pct(
        recommendation="recommend_hold",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert hold_pct <= buy_pct, f"Hold({hold_pct}) should be ≤ buy({buy_pct})"


def test_position_size_deterministic() -> None:
    """同 input 必须同 output(deterministic 计算,非随机)。"""
    pct1 = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=500_000_000_000.0,
    )
    pct2 = calc_recommended_position_size_pct(
        recommendation="recommend_buy",
        risk_tolerance="moderate",
        client_total_aum=10_000_000.0,
        target_market_cap=500_000_000_000.0,
    )
    assert pct1 == pct2, "calc_recommended_position_size_pct must be deterministic"


def test_position_size_is_float() -> None:
    """返回值必须是 float。"""
    pct = calc_recommended_position_size_pct(
        recommendation="recommend_overweight",
        risk_tolerance="aggressive",
        client_total_aum=10_000_000.0,
        target_market_cap=1_000_000_000_000.0,
    )
    assert isinstance(pct, float)


# ---------------------------------------------------------------------------
# Tests for build_investment_dd_prompt — 6-field conditioning
# ---------------------------------------------------------------------------


def test_writer_prompt_contains_investment_objective() -> None:
    """Writer prompt 必须包含 investment_objective 字段。"""
    state = _make_state(investment_objective="capital_preservation")
    prompt = build_investment_dd_prompt(state)
    assert "capital_preservation" in prompt or "保本" in prompt


def test_writer_prompt_contains_risk_tolerance() -> None:
    """Writer prompt 必须包含 risk_tolerance 字段。"""
    state = _make_state(risk_tolerance="very_aggressive")
    prompt = build_investment_dd_prompt(state)
    assert "very_aggressive" in prompt or "激进" in prompt


def test_writer_prompt_contains_investment_horizon() -> None:
    """Writer prompt 必须包含 investment_horizon 字段。"""
    state = _make_state(investment_horizon="long_term")
    prompt = build_investment_dd_prompt(state)
    assert "long_term" in prompt or "长期" in prompt


def test_writer_prompt_contains_aum() -> None:
    """Writer prompt 必须包含 client_total_aum 数字(用于仓位计算说明)。"""
    state = _make_state(client_total_aum=50_000_000.0)
    prompt = build_investment_dd_prompt(state)
    # AUM 应以某种形式出现在 prompt 中
    assert "50000000" in prompt or "5000" in prompt or "AUM" in prompt or "总资产" in prompt


def test_writer_prompt_contains_position_size_constraint() -> None:
    """Writer prompt 必须包含 § 6 仓位约束引导词。"""
    state = _make_state(risk_tolerance="conservative")
    prompt = build_investment_dd_prompt(state)
    # prompt 应提及仓位 / position_size / § 6 相关
    assert (
        "仓位" in prompt or "position_size" in prompt or "recommended_position_size_pct" in prompt
    )


@pytest.mark.parametrize(
    "objective", ["capital_preservation", "stable_growth", "balanced", "aggressive_growth"]
)
def test_writer_prompt_all_objectives_nonempty(objective: str) -> None:
    """所有 investment_objective 值都应产生非空 prompt。"""
    state = _make_state(investment_objective=objective)
    prompt = build_investment_dd_prompt(state)
    assert isinstance(prompt, str) and len(prompt) > 500
