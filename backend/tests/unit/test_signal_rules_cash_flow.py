"""Unit tests for CashFlowRule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_rules.base import MonitoringCustomer, SignalLevel
from app.services.monitoring.signal_rules.cash_flow import CashFlowRule
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS


@pytest.fixture
def customer() -> MonitoringCustomer:
    return MonitoringCustomer(id="x", ts_code="x.SH", name="x", industry="x")


def _ts(df: pd.DataFrame) -> MagicMock:
    fake = MagicMock()
    fake.get_cashflow = AsyncMock(return_value=df)
    return fake


@pytest.mark.asyncio
async def test_green_when_stable(customer: MonitoringCustomer) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "n_cashflow_act": v}
            for ed, v in [
                ("20240331", 5e8),
                ("20240630", 5.1e8),
                ("20240930", 5.2e8),
                ("20241231", 5.3e8),
            ]
        ]
    )
    rule = CashFlowRule()
    result = await rule.evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["cash_flow"]
    )
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_yellow_on_qoq_drop(customer: MonitoringCustomer) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "n_cashflow_act": v}
            for ed, v in [
                ("20240930", 5e8),
                ("20241231", 3e8),  # -40% QoQ
            ]
        ]
    )
    rule = CashFlowRule()
    result = await rule.evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["cash_flow"]
    )
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_red_on_consecutive_negative(customer: MonitoringCustomer) -> None:
    df = pd.DataFrame(
        [
            {"end_date": ed, "n_cashflow_act": v}
            for ed, v in [
                ("20240930", -1e8),
                ("20241231", -2e8),
            ]
        ]
    )
    rule = CashFlowRule()
    result = await rule.evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["cash_flow"]
    )
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_green_empty_data(customer: MonitoringCustomer) -> None:
    df = pd.DataFrame(columns=["end_date", "n_cashflow_act"])
    rule = CashFlowRule()
    result = await rule.evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["cash_flow"]
    )
    assert result.level == SignalLevel.GREEN
