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
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from mcp.types import TextContent, Tool

_SINGLE = {"is_open", "latest", "prev", "next"}
_RANGE = {"count", "list"}
_WINDOW = {"window"}
_ACTIONS = sorted(_SINGLE | _RANGE | _WINDOW)
_WINDOW_DAYS = 15  # 单日动作回看/前看窗口(覆盖最长节假日缺口)
_LIST_CAP = 260

_LOOKBACK_RE = re.compile(r"^(\d+)(y|m|d|td)$")


def _parse_lookback(code: Any) -> tuple[str, int]:
    """周期码 → (kind, n)。'ytd' 返回 ('ytd', 0);Ny/Nm/Nd/Ntd 返回 (单位, N)。非法抛 ValueError。"""
    if code == "ytd":
        return ("ytd", 0)
    m = _LOOKBACK_RE.match(code if isinstance(code, str) else "")
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"非法 lookback: {code!r}(形如 1y/6m/30d/20td/ytd)")
    return (m.group(2), int(m.group(1)))


def _minus_months(ymd: str, n: int) -> str:
    """anchor 减 N 个月;日溢出夹到目标月末(如 3/31 −1 月 → 2/28)。"""
    y, mo, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    total = y * 12 + (mo - 1) - n
    ny, nm = divmod(total, 12)
    nm += 1
    last = monthrange(ny, nm)[1]
    return date(ny, nm, min(d, last)).strftime("%Y%m%d")


def _minus_years(ymd: str, n: int) -> str:
    """anchor 减 N 年(复用月回退,闰日 2/29 自动夹到 2/28)。"""
    return _minus_months(ymd, n * 12)


TOOL_DEF = Tool(
    name="trade_cal",
    description=(
        "A-share trading calendar. action one of: is_open/latest/prev/next (need `date`), "
        "count/list (need `start`+`end`), window (need `anchor`+`lookback`, resolves a "
        "relative window in one call). Dates YYYYMMDD. Pass today explicitly for relative queries."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": _ACTIONS},
            "date": {"type": "string", "description": "YYYYMMDD (single-date actions)"},
            "start": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "end": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "anchor": {"type": "string", "description": "YYYYMMDD (window action: today/as-of)"},
            "lookback": {"type": "string", "description": "window action: 1y/6m/30d/20td/ytd"},
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


def _resolve_raw_start(anchor: str, kind: str, n: int) -> str:
    """日历型周期(y/m/d/ytd)的 raw_start(尚未顺延到交易日)。td 不走此函数。"""
    if kind == "ytd":
        return anchor[:4] + "0101"
    if kind == "y":
        return _minus_years(anchor, n)
    if kind == "m":
        return _minus_months(anchor, n)
    if kind == "d":
        return _shift(anchor, -n)
    raise ValueError(f"unexpected calendar kind: {kind}")


async def _handle_window(tushare: Any, args: dict[str, Any]) -> list[TextContent]:
    anchor = args.get("anchor")
    if _bad_ymd(anchor):
        return _err("[参数校验失败] window 需要 anchor(8 位 YYYYMMDD)")
    try:
        kind, n = _parse_lookback(args.get("lookback"))
    except ValueError:
        return _err("[参数校验失败] lookback 形如 1y/6m/30d/20td/ytd")

    if kind == "td":  # 计数型:从 end 倒数 N 个交易日
        df = await tushare.get_trade_cal(start=_shift(anchor, -(n * 2 + 30)), end=anchor)
        opens = _open_dates(df)
        le = [d for d in opens if d <= anchor]
        if not le:
            return _err("[数据为空] 该区间无交易日")
        window = le[-n:]
        start, end, trading_days = window[0], le[-1], len(window)
    else:  # 日历型:raw_start 顺延到首个交易日
        raw_start = _resolve_raw_start(anchor, kind, n)
        df = await tushare.get_trade_cal(start=raw_start, end=anchor)
        opens = _open_dates(df)
        if not opens:
            return _err("[数据为空] 该区间无交易日")
        start, end, trading_days = opens[0], opens[-1], len(opens)

    return _ok(
        {
            "action": "window",
            "anchor": anchor,
            "lookback": args.get("lookback"),
            "start": start,
            "end": end,
            "trading_days": trading_days,
            "anchor_is_open": anchor in opens,
        }
    )


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    action = args.get("action")
    if action not in _ACTIONS:
        return _err(f"[参数校验失败] action 必须是 {_ACTIONS} 之一")

    tushare = build_tushare_service()

    if action in _WINDOW:
        return await _handle_window(tushare, args)

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
