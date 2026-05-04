"""Unit tests for FinancialRatioRule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_rules.base import (
    MonitoringCustomer,
    SignalLevel,
)
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule


@pytest.fixture
def customer() -> MonitoringCustomer:
    return MonitoringCustomer(id="x", ts_code="600519.SH", name="茅台", industry="消费")


def _fake_tushare(balance_df: pd.DataFrame, fina_df: pd.DataFrame) -> MagicMock:
    fake = MagicMock()
    fake.get_balance_sheet = AsyncMock(return_value=balance_df)
    fake.get_fina_indicator = AsyncMock(return_value=fina_df)
    return fake


@pytest.mark.asyncio
async def test_green_when_stable(customer: MonitoringCustomer) -> None:
    balance = pd.DataFrame(
        [
            {"end_date": "20240331", "debt_to_assets": 0.40},
            {"end_date": "20240630", "debt_to_assets": 0.41},
            {"end_date": "20240930", "debt_to_assets": 0.42},
            {"end_date": "20241231", "debt_to_assets": 0.43},
        ]
    )
    fina = pd.DataFrame(
        [
            {"end_date": "20240331", "netprofit_margin": 0.30},
            {"end_date": "20240630", "netprofit_margin": 0.31},
            {"end_date": "20240930", "netprofit_margin": 0.32},
            {"end_date": "20241231", "netprofit_margin": 0.33},
        ]
    )
    rule = FinancialRatioRule()
    result = await rule.evaluate(
        customer,
        _fake_tushare(balance, fina),
        MagicMock(),
        MagicMock(),
        DEFAULT_THRESHOLDS["financial_ratio"],
    )
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_yellow_on_debt_ratio_jump(customer: MonitoringCustomer) -> None:
    balance = pd.DataFrame(
        [
            {"end_date": "20240331", "debt_to_assets": 0.40},
            {"end_date": "20240630", "debt_to_assets": 0.42},
            {"end_date": "20240930", "debt_to_assets": 0.44},
            {"end_date": "20241231", "debt_to_assets": 0.50},  # +6 pp QoQ
        ]
    )
    fina = pd.DataFrame([{"end_date": "20241231", "netprofit_margin": 0.20}])
    rule = FinancialRatioRule()
    result = await rule.evaluate(
        customer,
        _fake_tushare(balance, fina),
        MagicMock(),
        MagicMock(),
        DEFAULT_THRESHOLDS["financial_ratio"],
    )
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_red_on_high_debt_ratio_abs(customer: MonitoringCustomer) -> None:
    balance = pd.DataFrame(
        [
            {"end_date": "20240331", "debt_to_assets": 0.78},
            {"end_date": "20240630", "debt_to_assets": 0.79},
            {"end_date": "20240930", "debt_to_assets": 0.80},
            {"end_date": "20241231", "debt_to_assets": 0.85},  # > 80%
        ]
    )
    fina = pd.DataFrame([{"end_date": "20241231", "netprofit_margin": 0.15}])
    rule = FinancialRatioRule()
    result = await rule.evaluate(
        customer,
        _fake_tushare(balance, fina),
        MagicMock(),
        MagicMock(),
        DEFAULT_THRESHOLDS["financial_ratio"],
    )
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_red_on_consecutive_loss(customer: MonitoringCustomer) -> None:
    balance = pd.DataFrame([{"end_date": "20241231", "debt_to_assets": 0.50}])
    fina = pd.DataFrame(
        [
            {"end_date": "20240930", "netprofit_margin": -0.05},
            {"end_date": "20241231", "netprofit_margin": -0.10},  # 连续 2 季亏损
        ]
    )
    rule = FinancialRatioRule()
    result = await rule.evaluate(
        customer,
        _fake_tushare(balance, fina),
        MagicMock(),
        MagicMock(),
        DEFAULT_THRESHOLDS["financial_ratio"],
    )
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_green_empty_data(customer: MonitoringCustomer) -> None:
    balance = pd.DataFrame(columns=["end_date", "debt_to_assets"])
    fina = pd.DataFrame(columns=["end_date", "netprofit_margin"])
    rule = FinancialRatioRule()
    result = await rule.evaluate(
        customer,
        _fake_tushare(balance, fina),
        MagicMock(),
        MagicMock(),
        DEFAULT_THRESHOLDS["financial_ratio"],
    )
    assert result.level == SignalLevel.GREEN
