"""Unit tests for classify_recommendation (YAML-rules engine)."""

from __future__ import annotations

import importlib

import pytest
from app.skills.financial_research.scripts.classify_recommendation import (
    classify_recommendation,
)

classify_module = importlib.import_module(
    "app.skills.financial_research.scripts.classify_recommendation"
)


def test_sell_when_pe_above_90th_percentile() -> None:
    metrics = {
        "pe_percentile": 0.95,
        "roe": 0.18,
        "revenue_yoy": 0.10,
        "net_profit_yoy": 0.08,
        "forecast_signal": "neutral",
        "pledge_ratio": 0.10,
        "asset_liability_warning": False,
    }
    assert classify_recommendation(metrics) == "recommend_sell"


def test_buy_when_low_pe_high_roe_dual_growth() -> None:
    metrics = {
        "pe_percentile": 0.20,
        "roe": 0.20,
        "revenue_yoy": 0.15,
        "net_profit_yoy": 0.18,
        "forecast_signal": "neutral",
        "pledge_ratio": 0.05,
        "asset_liability_warning": False,
    }
    assert classify_recommendation(metrics) == "recommend_buy"


def test_overweight_with_positive_forecast() -> None:
    # pe percentile 0.55 — not buy (need <0.30) and not underweight (need >0.70)
    # forecast_signal=positive → overweight any_of fires
    metrics = {
        "pe_percentile": 0.55,
        "roe": 0.10,
        "revenue_yoy": 0.05,
        "net_profit_yoy": 0.05,
        "forecast_signal": "positive",
        "pledge_ratio": 0.05,
        "asset_liability_warning": False,
    }
    assert classify_recommendation(metrics) == "recommend_overweight"


def test_underweight_when_high_pe_negative_growth() -> None:
    # pe_percentile 0.75 (>0.70) → underweight; pe_percentile NOT >0.90 so not sell
    metrics = {
        "pe_percentile": 0.75,
        "roe": 0.08,
        "revenue_yoy": -0.05,
        "net_profit_yoy": -0.10,
        "forecast_signal": "neutral",
        "pledge_ratio": 0.05,
        "asset_liability_warning": False,
    }
    assert classify_recommendation(metrics) == "recommend_underweight"


def test_hold_as_fallback() -> None:
    # Neutral mid-range metrics — no rule fires until fallback hold.
    metrics = {
        "pe_percentile": 0.50,
        "roe": 0.10,
        "revenue_yoy": 0.03,
        "net_profit_yoy": 0.02,
        "forecast_signal": "neutral",
        "pledge_ratio": 0.05,
        "asset_liability_warning": False,
    }
    assert classify_recommendation(metrics) == "recommend_hold"


def test_deterministic_across_repeated_calls() -> None:
    metrics = {
        "pe_percentile": 0.20,
        "roe": 0.20,
        "revenue_yoy": 0.15,
        "net_profit_yoy": 0.18,
        "forecast_signal": "neutral",
        "pledge_ratio": 0.05,
        "asset_liability_warning": False,
    }
    results = [classify_recommendation(metrics) for _ in range(5)]
    assert len(set(results)) == 1
    assert results[0] == "recommend_buy"


def test_classify_with_none_value_returns_hold_fallback() -> None:
    """metrics 值为 None 时 _eval_condition 应 graceful skip, 最终落 hold."""
    # 仅 pe_percentile=None — 所有规则的条件涉及该字段时都视为 not-match.
    # 其他字段缺失 → metrics.get() 返 None → 同样 not-match. 兜底 hold.
    assert classify_recommendation({"pe_percentile": None}) == "recommend_hold"


def test_classify_with_type_mismatch_returns_hold_fallback() -> None:
    """metrics 值类型不可与 float 比较 (e.g. str) 应 graceful, 不抛 exception."""
    assert classify_recommendation({"pe_percentile": "high"}) == "recommend_hold"


def test_unrecognized_rule_envelope_raises() -> None:
    """yaml typo 或不支持的 envelope (e.g. not_of) 应 raise ValueError 而非 silent."""
    with pytest.raises(ValueError, match="unrecognized rule envelope"):
        classify_module._eval_rule({"conditions": {"not_of": []}}, {})


def test_overweight_when_exactly_3_metrics_pass_count_threshold() -> None:
    """count_at_least_3 边界 — 4 候选条件中恰好 3 个满足应触发 overweight."""
    metrics = {
        "pe_percentile": 0.45,  # < 0.50 ✓
        "roe": 0.13,  # > 0.12 ✓
        "revenue_yoy": 0.05,  # > 0 ✓
        "net_profit_yoy": -0.02,  # > 0 ✗ (4-th 不满足)
        "forecast_signal": "neutral",  # 不触发 forecast positive any_of
    }
    assert classify_recommendation(metrics) == "recommend_overweight"


def test_priority_sell_wins_over_underweight_overlap() -> None:
    """metrics 同时触发 sell + underweight 时, _PRIORITY 应让 sell 赢."""
    metrics = {
        "pe_percentile": 0.95,  # > 0.90 → sell trigger
        "revenue_yoy": -0.1,  # < 0 → underweight trigger
    }
    assert classify_recommendation(metrics) == "recommend_sell"
