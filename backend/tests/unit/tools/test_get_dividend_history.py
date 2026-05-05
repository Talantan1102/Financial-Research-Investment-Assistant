"""Unit test for GetDividendHistoryTool (v0.8.5)."""

from __future__ import annotations

import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.tools.get_dividend_history import (
    DividendHistoryArgs,
    GetDividendHistoryTool,
)
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_get_dividend_history_returns_consistency() -> None:
    tool = GetDividendHistoryTool(tushare=LegacyMockTushareAdapter())
    result = await tool.run(DividendHistoryArgs(ts_code="600519.SH"))
    assert result["ts_code"] == "600519.SH"
    assert "recent_dividends" in result
    assert isinstance(result["recent_dividends"], list)
    assert len(result["recent_dividends"]) == 5
    # Mock 数据 5 年都非零 → consistency 1.0
    assert result["dividend_consistency"] == 1.0
    # avg_dv_ratio_5y > 0
    assert result["avg_dv_ratio_5y"] > 0


def test_get_dividend_history_args_years_back_validation() -> None:
    with pytest.raises(ValidationError):
        DividendHistoryArgs(ts_code="x", years_back=0)
    with pytest.raises(ValidationError):
        DividendHistoryArgs(ts_code="x", years_back=11)
