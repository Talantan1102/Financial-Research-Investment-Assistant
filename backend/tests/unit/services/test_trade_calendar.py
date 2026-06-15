"""确定性 A 股交易日历工具单测(纯历法,不碰网络/LLM)。"""

from __future__ import annotations

import pytest

from app.services.trade_calendar import build_calendar_df


def _row(df, cal_date):
    return df[df["cal_date"] == cal_date].iloc[0]


def test_weekend_closed():
    df = build_calendar_df("20260613", "20260615")  # 周六/周日/周一
    assert int(_row(df, "20260613")["is_open"]) == 0  # 周六
    assert int(_row(df, "20260614")["is_open"]) == 0  # 周日


def test_new_year_holiday_closed():
    df = build_calendar_df("20260101", "20260101")  # 元旦
    assert int(df.iloc[0]["is_open"]) == 0


def test_normal_weekday_open():
    df = build_calendar_df("20260310", "20260310")  # 周二,无节假日
    assert int(df.iloc[0]["is_open"]) == 1


def test_columns_and_pretrade_seed():
    # 区间起点前的最近交易日要被"种子化",元旦后第一个交易日 pretrade 指向 2025-12-31。
    df = build_calendar_df("20251231", "20260105")
    assert {"cal_date", "is_open", "pretrade_date"}.issubset(df.columns)
    assert int(_row(df, "20251231")["is_open"]) == 1  # 周三,开市
    assert int(_row(df, "20260101")["is_open"]) == 0  # 元旦休市
    jan5 = _row(df, "20260105")  # 周一,2026 第一个交易日
    assert int(jan5["is_open"]) == 1
    assert jan5["pretrade_date"] == "20251231"


@pytest.mark.asyncio
async def test_mock_adapter_get_trade_cal_deterministic():
    from app.services.tushare_mock_adapter import LegacyMockTushareAdapter

    adapter = LegacyMockTushareAdapter()
    df1 = await adapter.get_trade_cal(start="20260101", end="20260110")
    df2 = await adapter.get_trade_cal(start="20260101", end="20260110")
    assert df1.equals(df2)  # 确定性
    assert int(_row(df1, "20260101")["is_open"]) == 0  # 元旦休市,绝不走 LLM
