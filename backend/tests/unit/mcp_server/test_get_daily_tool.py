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
