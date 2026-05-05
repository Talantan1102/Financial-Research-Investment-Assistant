"""Unit test for GetHolderChangeTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_holder_change import (
    GetHolderChangeTool,
    HolderChangeArgs,
    _classify_holder_trend,
)
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_holder_change_returns_concentration_for_decreasing_holders() -> None:
    """Mock fixture: holder_num [83000, 85500, 88000, 91200] sorted by end_date.

    Sorted ascending by end_date: 20220930→91200, 20230331→88000, 20230930→85500, 20240331→83000.
    Latest 83000 vs earliest 91200 → -9% drop > 5% → 'concentration'.
    """
    tool = GetHolderChangeTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(HolderChangeArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    assert "recent_holder_nums" in result
    assert isinstance(result["recent_holder_nums"], list)
    assert result["trend"] == "concentration"


def test_classify_holder_trend_thresholds() -> None:
    # latest < earliest by 10% → concentration (筹码集中)
    assert _classify_holder_trend(latest=90.0, earliest=100.0) == "concentration"
    # latest > earliest by 10% → dispersion (散户化)
    assert _classify_holder_trend(latest=110.0, earliest=100.0) == "dispersion"
    # within ±5% → stable
    assert _classify_holder_trend(latest=102.0, earliest=100.0) == "stable"
    assert _classify_holder_trend(latest=98.0, earliest=100.0) == "stable"
    # zero earliest → stable (defensive)
    assert _classify_holder_trend(latest=100.0, earliest=0.0) == "stable"


def test_get_holder_change_args_years_back_validation() -> None:
    with pytest.raises(ValidationError):
        HolderChangeArgs(ts_code="x", years_back=0)
    with pytest.raises(ValidationError):
        HolderChangeArgs(ts_code="x", years_back=6)
