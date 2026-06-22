"""get_daily MCP 工具 —— _format_daily 列式紧凑输出(纯函数,不碰网络/LLM)。"""

from __future__ import annotations

import pandas as pd
from app.mcp_server.tools.get_daily import TOOL_DEF, _format_daily


def test_format_daily_columnar_and_sorted() -> None:
    df = pd.DataFrame(
        {
            "trade_date": ["20250103", "20250101", "20250102"],  # 乱序
            "open": [10.1, 9.9, 10.0],
            "high": [10.5, 10.0, 10.2],
            "low": [9.8, 9.6, 9.7],
            "close": [10.3, 9.95, 10.1],
            "vol": [1000, 900, 1100],
            "pct_chg": [1.98, 0.5, 1.51],
        }
    )
    out = _format_daily(df, "600519.SH")
    assert out["ts_code"] == "600519.SH"
    assert out["count"] == 3
    assert out["dates"] == ["20250101", "20250102", "20250103"]  # 升序
    assert out["close"] == [9.95, 10.1, 10.3]  # 跟随日期升序
    assert len(out["open"]) == 3 and len(out["vol"]) == 3


def test_format_daily_empty() -> None:
    out = _format_daily(pd.DataFrame(), "600519.SH")
    assert out["count"] == 0
    assert out["dates"] == []


def test_tool_def_shape() -> None:
    assert TOOL_DEF.name == "get_daily"
    req = TOOL_DEF.inputSchema["required"]
    # 新 schema: ts_code 是唯一必填;start/end/anchor/lookback 均可选
    assert req == ["ts_code"]
    props = TOOL_DEF.inputSchema["properties"]
    assert "anchor" in props and "lookback" in props


def test_format_daily_no_tail_returns_full_range() -> None:
    # 旧 _MAX_ROWS=260 会把 300 行 tail 到 260;去 cap 后应原样返回全部
    n = 300
    df = pd.DataFrame(
        {
            "trade_date": [f"2025{i:04d}" for i in range(1, n + 1)],  # 唯一且可排序即可
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.0 + i * 0.01 for i in range(n)],
            "vol": [1000] * n,
            "pct_chg": [0.1] * n,
        }
    )
    out = _format_daily(df, "600519.SH")
    assert out["count"] == n
    assert len(out["close"]) == n  # 不再被 tail 到 260


def test_format_daily_summary_fields() -> None:
    df = pd.DataFrame(
        {
            "trade_date": ["20250101", "20250102", "20250103"],
            "open": [10.0, 10.1, 10.2],
            "high": [10.5, 12.0, 10.3],
            "low": [9.5, 9.0, 9.8],
            "close": [10.0, 11.0, 10.5],
            "vol": [1, 2, 3],
            "pct_chg": [0.0, 10.0, -4.5],
        }
    )
    s = _format_daily(df, "600519.SH")["summary"]
    assert s["count"] == 3
    assert s["date_start"] == "20250101" and s["date_end"] == "20250103"
    assert s["first_close"] == 10.0 and s["last_close"] == 10.5
    assert "period_high" not in s and "period_low" not in s  # 刻意不放,避免错误回撤捷径


# ---------------------------------------------------------------------------
# _resolve_range 纯函数测试
# ---------------------------------------------------------------------------

import pytest
from app.mcp_server.tools.get_daily import _resolve_range


def test_resolve_range_explicit():
    assert _resolve_range({"start": "20250101", "end": "20251231"}) == ("20250101", "20251231")


def test_resolve_range_anchor_lookback():
    assert _resolve_range({"anchor": "20260616", "lookback": "1y"}) == ("20250616", "20260616")


def test_resolve_range_td_raises():
    with pytest.raises(ValueError, match="td"):
        _resolve_range({"anchor": "20260616", "lookback": "20td"})


def test_resolve_range_missing_raises():
    with pytest.raises(ValueError):
        _resolve_range({"ts_code": "600519.SH"})


def test_resolve_range_partial_start_raises():
    # 只给 start、没 end 也没 anchor+lookback → 落通用错误(提示需 start+end 或 anchor+lookback)
    with pytest.raises(ValueError):
        _resolve_range({"ts_code": "600519.SH", "start": "20250101"})
