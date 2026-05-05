"""Unit test for GetForecastTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_forecast import (
    ForecastArgs,
    GetForecastTool,
    _classify_forecast_signal,
)
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_forecast_returns_signal_positive_for_yu_zeng() -> None:
    tool = GetForecastTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(ForecastArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    # Mock 数据 type='预增' → positive
    assert result["type"] == "预增"
    assert result["signal"] == "positive"


def test_classify_forecast_signal_keywords() -> None:
    assert _classify_forecast_signal("预增") == "positive"
    assert _classify_forecast_signal("扭亏") == "positive"
    assert _classify_forecast_signal("略增") == "positive"
    assert _classify_forecast_signal("预减") == "negative"
    assert _classify_forecast_signal("首亏") == "negative"
    assert _classify_forecast_signal("续亏") == "negative"
    assert _classify_forecast_signal("不确定") == "neutral"
    assert _classify_forecast_signal("") == "neutral"


def test_get_forecast_args_missing_ts_code_rejected() -> None:
    with pytest.raises(ValidationError):
        ForecastArgs()  # type: ignore[call-arg]
