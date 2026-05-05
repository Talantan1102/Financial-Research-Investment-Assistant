"""Unit tests for classify_recommendation (YAML-rules engine)."""

from __future__ import annotations

from app.skills.financial_research.scripts.classify_recommendation import (
    classify_recommendation,
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
