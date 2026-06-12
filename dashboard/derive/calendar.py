"""日历热力图网格构造 —— 纯函数,服务端渲染(每格 href 编码下一步选择)。

两次点选语义:当前是单天(sel_from==sel_to)且点了不同天 → 选区间;否则 → 单天。
状态全在 URL(?from&to&metric),无客户端 JS。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

_METRIC_KEY = {"cost": "cost_cny", "turns": "turns", "p95": "p95_ms", "cache": "cache_hit_rate"}


@dataclass
class Cell:
    date: date | None
    value: float | None = None
    intensity: int = 0  # 0=无数据/空;1..4=深浅
    empty: bool = True
    in_sel: bool = False
    href: str = ""


@dataclass
class Week:
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Calendar:
    weeks: list[Week]
    metric: str


def _next_href(d: date, metric: str, sel_from: date, sel_to: date) -> str:
    """两次点选:当前单天且点了不同天 → 区间;否则 → 单天 [d,d]。"""
    if sel_from == sel_to and d != sel_from:
        lo, hi = (sel_from, d) if sel_from < d else (d, sel_from)
    else:
        lo, hi = d, d
    return f"?from={lo.isoformat()}&to={hi.isoformat()}&metric={metric}"


def build_calendar(
    days: list[dict],
    cal_from: date,
    cal_to: date,
    metric: str,
    sel_from: date,
    sel_to: date,
) -> Calendar:
    key = _METRIC_KEY.get(metric, "cost_cny")
    val_by: dict[date, float | None] = {}
    for d in days:
        di = d["date"]
        di = di if isinstance(di, date) else date.fromisoformat(di)
        val_by[di] = d.get(key)
    vals = [v for v in val_by.values() if v is not None]
    vmax = max(vals) if vals else 0.0

    # 网格从 cal_from 所在周的周一起,到 cal_to 所在周的周日止
    start = cal_from - timedelta(days=cal_from.weekday())
    end = cal_to + timedelta(days=(6 - cal_to.weekday()))
    weeks: list[Week] = []
    cur = start
    while cur <= end:
        wk = Week()
        for _ in range(7):
            if cur < cal_from or cur > cal_to:
                wk.cells.append(Cell(date=None))
            else:
                v = val_by.get(cur)
                intensity = 0
                if v is not None and vmax > 0:
                    intensity = max(1, min(4, round(v / vmax * 4)))
                wk.cells.append(
                    Cell(
                        date=cur,
                        value=v,
                        intensity=intensity,
                        empty=(v is None),
                        in_sel=(sel_from <= cur <= sel_to),
                        href=_next_href(cur, metric, sel_from, sel_to),
                    )
                )
            cur += timedelta(days=1)
        weeks.append(wk)
    return Calendar(weeks=weeks, metric=metric)
