"""TushareBacktestAdapter unit tests — Phase 1 Task 1.4.

spec § 4.5 决策 5 time-travel 数据控制
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


def test_adapter_injects_cut_off_into_income_query() -> None:
    """fetch_income 自动加 end_date <= cut_off filter."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.income.return_value = [{"ts_code": "600519.SH", "ann_date": "20240315"}]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    adapter.fetch_income(ts_code="600519.SH")

    inner.income.assert_called_once()
    kwargs = inner.income.call_args.kwargs
    assert "end_date" in kwargs
    assert kwargs["end_date"] == "20240630"


def test_adapter_drops_rows_after_cut_off() -> None:
    """二次防御:即使 inner 返回 ann_date > cut_off 的行也丢."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.income.return_value = [
        {"ts_code": "600519.SH", "ann_date": "20240315"},
        {"ts_code": "600519.SH", "ann_date": "20240815"},  # > cut_off, 必须丢
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_income(ts_code="600519.SH")

    assert len(rows) == 1
    assert rows[0]["ann_date"] == "20240315"


def test_adapter_daily_kline_caps_trade_date() -> None:
    """fetch_daily_kline 按 cut_off 截止 + 二次过滤 trade_date."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.daily.return_value = [
        {"trade_date": "20240329", "close": 1700.0},
        {"trade_date": "20240801", "close": 1500.0},  # > cut_off
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_daily_kline(ts_code="600519.SH", start_date="20240101")

    assert len(rows) == 1
    assert rows[0]["trade_date"] == "20240329"


def test_adapter_cut_off_required() -> None:
    """cut_off 必填,不允许 None."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    with pytest.raises(TypeError):
        TushareBacktestAdapter(inner=MagicMock())  # type: ignore[call-arg]
