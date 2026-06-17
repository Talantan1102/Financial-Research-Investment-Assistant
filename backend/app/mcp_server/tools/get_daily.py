"""MCP tool adapter — get_daily(A股日线 OHLC 时序,解锁 K线/走势/相关性/回撤)。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata(server.py list_tools 聚合)
  handle()  — async dispatch(server.py call_tool 聚合)

返回**列式**紧凑结构(dates/open/high/low/close/vol/pct_chg 各一数组),可直接喂
plotly go.Candlestick(x=dates, open=..., ...) 或折线;比 list-of-dict 省 token。
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

TOOL_DEF = Tool(
    name="get_daily",
    description=(
        "Daily OHLC candlestick series for one A-share over a date range. "
        "Args: ts_code (e.g. '600519.SH'), start/end (YYYYMMDD). "
        "Returns columnar arrays: dates, open, high, low, close, vol, pct_chg."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "ts_code": {"type": "string", "description": "A-share code, e.g. '600519.SH'"},
            "start": {"type": "string", "description": "start date YYYYMMDD"},
            "end": {"type": "string", "description": "end date YYYYMMDD"},
        },
        "required": ["ts_code", "start", "end"],
    },
)

def _round_list(series: Any, ndigits: int = 2) -> list:
    out = []
    for v in series:
        try:
            out.append(round(float(v), ndigits))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _summary(df: Any, ts_code: str) -> dict[str, Any]:
    """从**完整** df 现算紧凑信息卡;超大截断后由 ToolLoop 保留(见 spec § 4.1/4.2)。

    去 cap 后长区间真取全量,完整序列过大会被换出上下文——这张卡是 agent 留在
    上下文里能核对范围/直接答简单问题的依据,体积小、廉价。
    """
    dates = [str(d) for d in df["trade_date"].tolist()]
    close = df["close"]
    return {
        "ts_code": ts_code,
        "count": int(len(df)),
        "date_start": dates[0],
        "date_end": dates[-1],
        "first_close": round(float(close.iloc[0]), 2),
        "last_close": round(float(close.iloc[-1]), 2),
        # 刻意不放 period_high/period_low:会诱导 agent 拿(最低-最高)/最高当最大回撤,
        # 但最大回撤是路径依赖的峰谷,须按完整收盘序列逐日算(见 system_prompt 纪律)。
    }


def _format_daily(df: Any, ts_code: str) -> dict[str, Any]:
    """DataFrame → 列式紧凑 dict(纯函数,可单测,不碰网络/LLM)。"""
    if df is None or getattr(df, "empty", True):
        return {"ts_code": ts_code, "count": 0, "dates": []}
    df = df.sort_values("trade_date")
    out: dict[str, Any] = {
        "ts_code": ts_code,
        "count": int(len(df)),
        "summary": _summary(df, ts_code),
        "dates": [str(d) for d in df["trade_date"].tolist()],
        "open": _round_list(df["open"]),
        "high": _round_list(df["high"]),
        "low": _round_list(df["low"]),
        "close": _round_list(df["close"]),
    }
    if "vol" in df.columns:
        out["vol"] = _round_list(df["vol"], 0)
    if "pct_chg" in df.columns:
        out["pct_chg"] = _round_list(df["pct_chg"])
    return out


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    ts_code = args["ts_code"]
    start = args["start"]
    end = args["end"]
    tushare = build_tushare_service()
    df = await tushare.get_daily(ts_code=ts_code, start=start, end=end)
    payload = _format_daily(df, ts_code)
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]
