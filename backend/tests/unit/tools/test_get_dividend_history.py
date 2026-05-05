"""Unit test for GetDividendHistoryTool (v0.8.5)."""

from __future__ import annotations

from typing import cast

import pandas as pd
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter
from app.services.tushare_service import TushareService
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


@pytest.mark.asyncio
async def test_dividend_consistency_partial() -> None:
    """5 年 cash_div=[10, 0, 12, 0, 8] (3 非零) → consistency = 0.6."""

    class _StubTushare:
        def __init__(self, df: pd.DataFrame) -> None:
            self._df = df

        async def get_dividend_history(self, *, ts_code: str, years_back: int = 5) -> pd.DataFrame:
            return self._df

    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"] * 5,
            "ann_date": ["20240515", "20230515", "20220515", "20210515", "20200515"],
            "cash_div": [10.0, 0.0, 12.0, 0.0, 8.0],
        }
    )
    tool = GetDividendHistoryTool(tushare=cast(TushareService, _StubTushare(df)))
    result = await tool.run(DividendHistoryArgs(ts_code="600519.SH"))
    assert abs(result["dividend_consistency"] - 0.6) < 0.01
