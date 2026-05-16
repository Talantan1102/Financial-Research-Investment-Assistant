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


def test_adapter_drops_rows_with_missing_ann_date() -> None:
    """I-1 契约守护: 缺 ann_date 字段的行被 '99999999' 哨兵丢掉(silent drop, 非 raise).

    backtest 下 silent leak 比 silent drop 更危险, 所以契约是丢。本 test 显式
    守护该契约, 防止未来改 fallback 时无声破坏 backtest 正确性。
    """
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.income.return_value = [
        {"ts_code": "600519.SH", "ann_date": "20240315"},  # 正常 — 保留
        {"ts_code": "600519.SH"},  # 缺 ann_date — 必须丢
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_income(ts_code="600519.SH")

    assert len(rows) == 1
    assert rows[0]["ann_date"] == "20240315"


def test_adapter_announcements_filters_by_ann_date() -> None:
    """M-3 fetch_announcements 也按 ann_date 二次过滤 (anns 接口主键是 ann_date)."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.anns.return_value = [
        {"ann_date": "20240501", "title": "Q1 财报"},
        {"ann_date": "20240920", "title": "Q3 财报"},  # > cut_off, 必须丢
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_announcements(ts_code="600519.SH")

    assert len(rows) == 1
    assert rows[0]["ann_date"] == "20240501"
    # Layer 1 也要验证 — inner.anns 被注入 end_date
    kwargs = inner.anns.call_args.kwargs
    assert kwargs.get("end_date") == "20240630"
