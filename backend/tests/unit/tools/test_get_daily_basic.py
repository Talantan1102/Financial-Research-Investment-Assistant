"""Unit test for GetDailyBasicTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_daily_basic import DailyBasicArgs, GetDailyBasicTool
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_daily_basic_returns_valuation_snapshot() -> None:
    tool = GetDailyBasicTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(DailyBasicArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    for field in ("pe", "pb", "ps", "dv_ratio", "total_mv", "circ_mv", "turnover_rate"):
        assert field in result
    # Mock 给的 PE 是 64.19
    assert result["pe"] > 0


def test_get_daily_basic_args_optional_trade_date() -> None:
    args = DailyBasicArgs(ts_code="600519.SH")
    assert args.trade_date is None


def test_get_daily_basic_args_missing_ts_code_rejected() -> None:
    with pytest.raises(ValidationError):
        DailyBasicArgs()  # type: ignore[call-arg]
