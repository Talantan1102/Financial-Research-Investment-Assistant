"""price_anomaly rule — symmetric ±5/±10% (spec § 4.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pandas as pd
import pytest

from app.services.monitoring.scope import MonitoringSubject
from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule
from app.services.monitoring.signal_rules.base import SignalLevel


@pytest.fixture
def subject() -> MonitoringSubject:
    return MonitoringSubject(user_id="u1", ts_code="600519.SH", name="贵州茅台")


@pytest.fixture
def thresholds() -> dict[str, float]:
    return {
        "red_single_day_change_pct": 10.0,
        "yellow_single_day_change_pct": 5.0,
        "yellow_60d_change_pct": 20.0,
    }


def _mock_tushare_with_closes(closes: list[float]) -> Mock:
    """Build mock tushare with given close sequence (most recent last).

    NOTE: Plan used `f"2026050{i+1}"` which produces variable-length strings
    that mis-sort lexicographically (e.g. "202605010" < "20260502"). We pad
    via sequential YYYYMMDD via timedelta to keep trade_date sortable —
    behaviour is otherwise identical to the plan.
    """
    from datetime import date, timedelta

    n = len(closes)
    base = date(2026, 1, 1)
    df = pd.DataFrame({
        "trade_date": [(base + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)],
        "close": closes,
    })
    tushare = Mock()
    tushare.get_daily = AsyncMock(return_value=df)
    return tushare


@pytest.mark.asyncio
async def test_single_day_drop_10pct_returns_red(subject, thresholds):
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0, 89.0])  # -11%
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.RED
    assert "11" in result.explanation or "-11" in result.explanation


@pytest.mark.asyncio
async def test_single_day_rise_10pct_returns_red(subject, thresholds):
    """对称化:涨 ≥10% 也触发 RED(spec § 5.1)."""
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0, 111.0])  # +11%
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.RED


@pytest.mark.asyncio
async def test_single_day_drop_6pct_returns_yellow(subject, thresholds):
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0, 94.0])  # -6%
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_single_day_rise_6pct_returns_yellow(subject, thresholds):
    """对称化:涨 ≥5% 也触发 YELLOW."""
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0, 106.0])  # +6%
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.YELLOW


@pytest.mark.asyncio
async def test_single_day_change_3pct_returns_green(subject, thresholds):
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0, 103.0])  # +3%
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.GREEN


@pytest.mark.asyncio
async def test_60d_drop_25pct_returns_yellow(subject, thresholds):
    """60 日累计跌 ≥20% 仍保留 YELLOW(spec § 4.4 长趋势警示)."""
    rule = PriceAnomalyRule()
    closes = [100.0] * 60  # baseline
    closes[-1] = 75.0  # -25% cumulative,但 single-day 跟 closes[-2]=100 是 -25% 也 RED
    # 改为更细的 path:让最后两天单日变化 < 5%(GREEN) 但 60d 累计 -25%
    closes = [100.0]
    for i in range(58):
        closes.append(closes[-1] * 0.995)  # 每天 -0.5%,累计 ~25%
    closes.append(closes[-1])  # 最后一天和倒数第二天相同
    tushare = _mock_tushare_with_closes(closes)
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.YELLOW
    assert "60" in result.explanation


@pytest.mark.asyncio
async def test_insufficient_data_returns_green(subject, thresholds):
    rule = PriceAnomalyRule()
    tushare = _mock_tushare_with_closes([100.0])  # 只 1 天
    result = await rule.evaluate(subject, tushare, Mock(), Mock(), thresholds)
    assert result.level == SignalLevel.GREEN
    assert "数据不足" in result.explanation
