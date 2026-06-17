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
    assert "ts_code" in req and "start" in req and "end" in req


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
