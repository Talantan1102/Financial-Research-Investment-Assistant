"""get_index_daily MCP 工具 —— _format_index_daily 格式化函数 + TOOL_DEF 形状(纯函数,不碰网络/LLM)。"""

from __future__ import annotations

import pandas as pd
from app.mcp_server.tools.get_index_daily import TOOL_DEF
from app.tools.get_index_daily import _format_index_daily


def test_format_index_daily_computes_pct_change() -> None:
    df = pd.DataFrame(
        {
            "trade_date": ["20261113", "20261114"],
            "close": [4000.0, 3968.0],
            "pre_close": [4010.0, 4000.0],
            "pct_chg": [-0.25, -0.80],
        }
    )
    out = _format_index_daily(df, "000300.SH")
    assert out["ts_code"] == "000300.SH"
    assert out["latest"]["trade_date"] == "20261114"
    assert out["latest"]["pct_chg"] == -0.80  # 当日涨跌幅(%)


def test_format_index_daily_empty() -> None:
    out = _format_index_daily(pd.DataFrame(), "000300.SH")
    assert out["ts_code"] == "000300.SH"
    assert out["count"] == 0
    assert out["latest"] is None


def test_tool_def_shape() -> None:
    assert TOOL_DEF.name == "get_index_daily"
    assert "ts_code" in TOOL_DEF.inputSchema["required"]
