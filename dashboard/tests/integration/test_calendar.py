"""build_calendar 纯函数 —— 网格 / 着色 / 两次点选 href 语义。"""

from __future__ import annotations

from datetime import date

from dashboard.derive.calendar import build_calendar


def _days(items):  # items: {iso: value}
    return [
        {"date": k, "cost_cny": v, "turns": v, "p95_ms": v, "cache_hit_rate": v}
        for k, v in items.items()
    ]


def test_grid_weeks_and_empty_cells() -> None:
    cal = build_calendar(
        days=_days({"2026-06-08": 10.0, "2026-06-10": 30.0}),
        cal_from=date(2026, 6, 8),
        cal_to=date(2026, 6, 14),
        metric="cost",
        sel_from=date(2026, 6, 10),
        sel_to=date(2026, 6, 10),
    )
    flat = [c for wk in cal.weeks for c in wk.cells]
    by = {c.date: c for c in flat if c.date}
    assert by[date(2026, 6, 8)].value == 10.0 and not by[date(2026, 6, 8)].empty
    assert by[date(2026, 6, 9)].empty  # 无数据 → 空格
    assert by[date(2026, 6, 10)].intensity == 4  # 最大值 → 满档(1..4)


def test_href_single_to_range_then_range_to_single() -> None:
    cal = build_calendar(
        days=_days({"2026-06-10": 1.0, "2026-06-12": 1.0}),
        cal_from=date(2026, 6, 8),
        cal_to=date(2026, 6, 14),
        metric="p95",
        sel_from=date(2026, 6, 10),
        sel_to=date(2026, 6, 10),  # 当前单天 6/10
    )
    by = {c.date: c for wk in cal.weeks for c in wk.cells if c.date}
    # 当前是单天 6/10 → 点 6/12 应得区间 [6/10, 6/12]
    assert "from=2026-06-10" in by[date(2026, 6, 12)].href
    assert "to=2026-06-12" in by[date(2026, 6, 12)].href
    assert "metric=p95" in by[date(2026, 6, 12)].href
    # 点回 6/10 自己 → 仍单天
    assert "from=2026-06-10" in by[date(2026, 6, 10)].href
    assert "to=2026-06-10" in by[date(2026, 6, 10)].href

    cal2 = build_calendar(
        days=_days({"2026-06-10": 1.0}),
        cal_from=date(2026, 6, 8),
        cal_to=date(2026, 6, 14),
        metric="cost",
        sel_from=date(2026, 6, 9),
        sel_to=date(2026, 6, 12),  # 当前是区间
    )
    by2 = {c.date: c for wk in cal2.weeks for c in wk.cells if c.date}
    # 当前是区间 → 点任一天 D 应重置为单天 [D, D]
    assert "from=2026-06-10" in by2[date(2026, 6, 10)].href
    assert "to=2026-06-10" in by2[date(2026, 6, 10)].href


def test_default_range_first_click_resets_to_single() -> None:
    # spec 真实入口:默认是 7 天「区间」→ 第一次点任一天应重置为「单天」(起点)
    cal = build_calendar(
        days=_days({"2026-06-10": 1.0}),
        cal_from=date(2026, 6, 1),
        cal_to=date(2026, 6, 14),
        metric="cost",
        sel_from=date(2026, 6, 8),
        sel_to=date(2026, 6, 14),  # 默认 7 天区间
    )
    by = {c.date: c for wk in cal.weeks for c in wk.cells if c.date}
    assert "from=2026-06-10" in by[date(2026, 6, 10)].href
    assert "to=2026-06-10" in by[date(2026, 6, 10)].href
