"""Unit tests for StockQuoteTool — regression for C54 (5-day window fix).

C54: get_stock_quote previously passed start=today,end=today (zero-width window),
     causing ToolError on weekends/holidays (~30% of calendar days).  Fix expands
     the window to 5 days; sort_values+iloc[0] picks the most recent trading day.
"""

from __future__ import annotations

from typing import cast

import pandas as pd
import pytest
from app.services.tushare_service import TushareService
from app.tools.base import ToolError
from app.tools.get_stock_quote import StockQuoteArgs, StockQuoteTool

# ---------------------------------------------------------------------------
# Stub TushareService
# ---------------------------------------------------------------------------


class _StubTushare:
    """Minimal TushareService stub that returns a caller-supplied DataFrame."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self._last_start: str | None = None
        self._last_end: str | None = None

    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        self._last_start = start
        self._last_end = end
        return self._df

    async def aclose(self) -> None:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Helper: multi-day fixture (simulates a period with multiple trading days)
# ---------------------------------------------------------------------------


def _multi_day_df(ts_code: str = "600519.SH") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": [ts_code, ts_code, ts_code],
            "trade_date": ["20241227", "20241228", "20241229"],  # three consecutive rows
            "close": [1800.0, 1810.0, 1820.0],
            "pct_chg": [0.5, 0.55, 0.61],
            "vol": [12000.0, 13000.0, 11500.0],
        }
    )


# ---------------------------------------------------------------------------
# C54 regression: tool returns the most recent row from a multi-day frame
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_most_recent_trading_day() -> None:
    """C54: tool picks the latest trade_date row even when df has multiple rows."""
    stub = _StubTushare(_multi_day_df())
    tool = StockQuoteTool(tushare=cast(TushareService, stub))
    result = await tool.run(StockQuoteArgs(ts_code="600519.SH"))

    assert result["ts_code"] == "600519.SH"
    assert result["price"] == pytest.approx(1820.0)  # most recent (20241229)
    assert result["change_pct"] == pytest.approx(0.61)
    assert result["volume"] == pytest.approx(11500.0)


@pytest.mark.asyncio
async def test_window_is_5_days_wide() -> None:
    """C54: the start date passed to get_daily is today-5days (not today)."""
    from datetime import datetime

    stub = _StubTushare(_multi_day_df())
    tool = StockQuoteTool(tushare=cast(TushareService, stub))
    await tool.run(StockQuoteArgs(ts_code="600519.SH"))

    assert stub._last_start is not None
    assert stub._last_end is not None

    # start must be strictly before end (at least 4 days gap)
    start_dt = datetime.strptime(stub._last_start, "%Y%m%d")
    end_dt = datetime.strptime(stub._last_end, "%Y%m%d")
    assert (end_dt - start_dt).days >= 4, (
        f"Expected >=4 day window; got start={stub._last_start} end={stub._last_end}"
    )


@pytest.mark.asyncio
async def test_weekend_case_returns_prior_friday_row() -> None:
    """C54: when only a prior-day row is available (e.g. queried on weekend),
    the tool should return it instead of raising ToolError."""
    # Simulate: today is Saturday 20241228, Tushare returns only Friday 20241227.
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"],
            "trade_date": ["20241227"],  # Friday before the weekend
            "close": [1800.0],
            "pct_chg": [0.3],
            "vol": [10000.0],
        }
    )
    stub = _StubTushare(df)
    tool = StockQuoteTool(tushare=cast(TushareService, stub))

    # Before the fix: only passing today would return empty df → ToolError
    # After the fix: 5-day window includes the prior Friday → no error
    result = await tool.run(StockQuoteArgs(ts_code="600519.SH"))
    assert result["price"] == pytest.approx(1800.0)
    assert result["ts_code"] == "600519.SH"


@pytest.mark.asyncio
async def test_empty_dataframe_raises_tool_error() -> None:
    """An empty response still raises ToolError (happy-path guard preserved)."""
    stub = _StubTushare(pd.DataFrame())
    tool = StockQuoteTool(tushare=cast(TushareService, stub))

    with pytest.raises(ToolError, match="No daily data returned"):
        await tool.run(StockQuoteArgs(ts_code="600519.SH"))


@pytest.mark.asyncio
async def test_tushare_none_raises_tool_error() -> None:
    """No tushare configured → ToolError immediately."""
    tool = StockQuoteTool(tushare=None)
    with pytest.raises(ToolError, match="tushare not configured"):
        await tool.run(StockQuoteArgs(ts_code="600519.SH"))
