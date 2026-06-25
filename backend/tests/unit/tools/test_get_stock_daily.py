"""GetStockDailyTool 单测:按区间取个股日线收盘序列(让模型自己算涨幅/回撤)。

填 app/tools 缺口:get_stock_quote 只给最新值,区间收盘序列原本无 Tool 暴露。
注入假 TushareService(返回 DataFrame),不连真 tushare。
"""

import pandas as pd
import pytest

from app.tools.base import ToolError
from app.tools.get_stock_daily import GetStockDailyArgs, GetStockDailyTool


class _FakeTushare:
    def __init__(self, df):
        self._df = df
        self.calls = []

    async def get_daily(self, *, ts_code, start, end):
        self.calls.append((ts_code, start, end))
        return self._df


@pytest.mark.asyncio
async def test_returns_close_series_sorted():
    df = pd.DataFrame(
        [
            {"trade_date": "20260612", "close": 28.45},
            {"trade_date": "20260312", "close": 30.00},
        ]
    )
    tushare = _FakeTushare(df)
    tool = GetStockDailyTool(tushare=tushare)
    out = await tool.run(GetStockDailyArgs(ts_code="000938.SZ", start_date="20260312", end_date="20260612"))
    # 传参透传给服务
    assert tushare.calls == [("000938.SZ", "20260312", "20260612")]
    # 返回按日期升序的收盘序列(让模型算 end/start-1)
    assert out["ts_code"] == "000938.SZ"
    assert out["closes"] == [
        {"trade_date": "20260312", "close": 30.00},
        {"trade_date": "20260612", "close": 28.45},
    ]


@pytest.mark.asyncio
async def test_empty_raises_toolerror():
    tool = GetStockDailyTool(tushare=_FakeTushare(pd.DataFrame()))
    with pytest.raises(ToolError):
        await tool.run(GetStockDailyArgs(ts_code="X", start_date="20260101", end_date="20260102"))


@pytest.mark.asyncio
async def test_no_tushare_raises():
    tool = GetStockDailyTool(tushare=None)
    with pytest.raises(ToolError):
        await tool.run(GetStockDailyArgs(ts_code="X", start_date="20260101", end_date="20260102"))
