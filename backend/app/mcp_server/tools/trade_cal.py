"""MCP tool — trade_cal(A 股交易日历:开市判断 / 最近交易日 / 区间交易日)。

六动作:is_open / latest / prev / next / count / list。
日期一律由参数显式传入,handle 内绝不读 datetime.now()(确定性,可 cassette / 可 RL)。
单日动作按 date 取 ±15 天窗口(覆盖最长节假日缺口)在日历上解析;区间动作用 start/end。

Exports:
  TOOL_DEF  — mcp.types.Tool metadata(server.py list_tools 聚合)
  handle()  — async dispatch(server.py call_tool 聚合)
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from mcp.types import TextContent, Tool

_SINGLE = {"is_open", "latest", "prev", "next"}
_RANGE = {"count", "list"}
_ACTIONS = sorted(_SINGLE | _RANGE)
_WINDOW_DAYS = 15  # 单日动作回看/前看窗口(覆盖最长节假日缺口)
_LIST_CAP = 260

TOOL_DEF = Tool(
    name="trade_cal",
    description=(
        "A-share trading calendar. action one of: is_open/latest/prev/next (need `date`), "
        "count/list (need `start`+`end`). Dates YYYYMMDD. Pass today explicitly for relative queries."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": _ACTIONS},
            "date": {"type": "string", "description": "YYYYMMDD (single-date actions)"},
            "start": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "end": {"type": "string", "description": "YYYYMMDD (range actions)"},
        },
        "required": ["action"],
    },
)


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}, ensure_ascii=False))]


def _ok(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]


def _shift(ymd: str, days: int) -> str:
    d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])) + timedelta(days=days)
    return d.strftime("%Y%m%d")


def _bad_ymd(s: Any) -> bool:
    """非 8 位纯数字 YYYYMMDD(含 None / 带分隔符 / 非串)→ True。"""
    return not (isinstance(s, str) and len(s) == 8 and s.isdigit())


def _open_dates(df: Any) -> list[str]:
    return sorted(str(r["cal_date"]) for r in df.to_dict("records") if int(r["is_open"]) == 1)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    action = args.get("action")
    if action not in _SINGLE and action not in _RANGE:
        return _err(f"[参数校验失败] action 必须是 {_ACTIONS} 之一")

    tushare = build_tushare_service()

    if action in _SINGLE:
        qdate = args.get("date")
        if _bad_ymd(qdate):
            return _err("[参数校验失败] is_open/latest/prev/next 需要 date(8 位 YYYYMMDD)")
        df = await tushare.get_trade_cal(
            start=_shift(qdate, -_WINDOW_DAYS), end=_shift(qdate, _WINDOW_DAYS)
        )
        opens = _open_dates(df)
        if action == "is_open":
            return _ok({"action": action, "date": qdate, "is_open": qdate in opens})
        if action == "latest":  # ≤ qdate 的最近交易日
            le = [d for d in opens if d <= qdate]
            return _ok(
                {
                    "action": action,
                    "query_date": qdate,
                    "result_date": max(le) if le else None,
                    "is_open_on_query": qdate in opens,
                }
            )
        if action == "prev":  # 严格早于 qdate
            lt = [d for d in opens if d < qdate]
            return _ok(
                {"action": action, "query_date": qdate, "result_date": max(lt) if lt else None}
            )
        gt = [d for d in opens if d > qdate]  # next:严格晚于 qdate
        return _ok({"action": action, "query_date": qdate, "result_date": min(gt) if gt else None})

    # range: count / list
    start, end = args.get("start"), args.get("end")
    if _bad_ymd(start) or _bad_ymd(end):
        return _err("[参数校验失败] count/list 需要 start 与 end(8 位 YYYYMMDD)")
    df = await tushare.get_trade_cal(start=start, end=end)
    opens = _open_dates(df)
    if action == "count":
        return _ok({"action": action, "start": start, "end": end, "count": len(opens)})
    truncated = len(opens) > _LIST_CAP
    dates = opens[-_LIST_CAP:] if truncated else opens
    return _ok(
        {
            "action": action,
            "start": start,
            "end": end,
            "count": len(opens),
            "dates": dates,
            "truncated": truncated,
        }
    )
