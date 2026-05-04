"""Unit tests for PriceAnomalyRule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from app.services.monitoring.signal_rules.base import MonitoringCustomer, SignalLevel
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule


@pytest.fixture
def customer() -> MonitoringCustomer:
    return MonitoringCustomer(id="x", ts_code="x.SH", name="x", industry="x")


def _ts(df: pd.DataFrame) -> MagicMock:
    fake = MagicMock()
    fake.get_daily = AsyncMock(return_value=df)
    return fake


def _build_daily(prices: list[float]) -> pd.DataFrame:
    from datetime import date, timedelta

    base = date(2024, 1, 1)
    return pd.DataFrame(
        [
            {
                "trade_date": (base + timedelta(days=i)).strftime("%Y%m%d"),
                "close": p,
                "pct_chg": 0.0,
            }
            for i, p in enumerate(prices)
        ]
    )


@pytest.mark.asyncio
async def test_green_stable(customer: MonitoringCustomer) -> None:
    df = _build_daily([100.0] * 60)
    r = await PriceAnomalyRule().evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["price_anomaly"]
    )
    assert r.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_yellow_single_day_drop(customer: MonitoringCustomer) -> None:
    df = _build_daily([100.0] * 59 + [93.0])  # -7%
    r = await PriceAnomalyRule().evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["price_anomaly"]
    )
    assert r.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_red_single_day_drop(customer: MonitoringCustomer) -> None:
    df = _build_daily([100.0] * 59 + [88.0])  # -12%
    r = await PriceAnomalyRule().evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["price_anomaly"]
    )
    assert r.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_yellow_60d_cumulative(customer: MonitoringCustomer) -> None:
    # first=100, rest=78 → cum_drop = 22% > yellow_60d_drop_pct=20%
    # single-day drop prev=78 curr=78 → 0%, so won't trigger single-day checks
    df = _build_daily([100.0] + [78.0] * 59)
    r = await PriceAnomalyRule().evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["price_anomaly"]
    )
    assert r.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_green_empty_data(customer: MonitoringCustomer) -> None:
    df = pd.DataFrame(columns=["trade_date", "close", "pct_chg"])
    r = await PriceAnomalyRule().evaluate(
        customer, _ts(df), MagicMock(), MagicMock(), DEFAULT_THRESHOLDS["price_anomaly"]
    )
    assert r.level == SignalLevel.GREEN
