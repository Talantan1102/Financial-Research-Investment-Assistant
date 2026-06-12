# Chatloop 可观测性日历热力图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把可观测性页从「1d/7d/30d 固定窗口」升级为「日历热力图(按天 / 4 指标可切上色)+ 点起止两次选任意范围」,落 spec `2026-06-12-chatloop-observability-calendar-design.md`。

**Architecture:** 后端把聚合 SQL 的时间下界改成通用 `:start/:end`、加「逐日分桶」查询与新 `/daily` 端点;前端纯服务端渲染(每个日期格子的链接由当前 from/to 算出下一步选择,无客户端 JS),日历网格由一个纯函数 `build_calendar` 构造、可单测。

**Tech Stack:** Python / SQLAlchemy raw SQL(`percentile_cont` + `FILTER` + `CASE`)/ FastAPI / Pydantic / Starlette + Jinja2 / PostgreSQL JSONB。

---

## 文件结构

- 改 `backend/app/services/trace_analytics.py` — 4 条聚合 SQL 改 `:start/:end`;加 `_resolve_range`;`aggregate` 加 `start/end`;加 `DayBucket`/`ChatloopDaily` + `daily()`。
- 改 `backend/app/router/observability_router.py` — `/aggregates` 收 `from/to`(兼容 `window`);加 `/daily`。
- 建 `dashboard/derive/calendar.py` — 纯函数 `build_calendar(...)` 造网格 + 每格 href。
- 改 `dashboard/derive/observability.py` — `load_aggregates` 支持 `from/to`;加 `load_daily`。
- 改 `dashboard/server.py` — `chatloop_observability_view` 解析 `metric/from/to`、拉两份、`build_calendar`、渲染。
- 改 `dashboard/templates/chatloop_observability.html` — 加日历区(指标下拉 + 快捷 + 网格)。

**测试**
- `backend/tests/integration/test_trace_analytics.py`(范围聚合 + 逐日分桶)
- `backend/tests/integration/test_observability_api.py`(from/to + /daily + 隐私)
- `dashboard/tests/integration/test_calendar.py`(网格 + href 两次点选语义,纯函数)
- `dashboard/tests/integration/test_chatloop_observability_page.py`(日历渲染 + 降级)

## 已知接口事实(直接用)

- `ChatloopTraceAnalytics(session_factory)`、`aggregate(window="7d")`、4 个 SQL 常量、`ToolLatencyStat`/`ChatloopAggregates`(`backend/app/services/trace_analytics.py`,当前用 `started_at >= now() - (:interval)::interval`,params `{"interval": interval}`;`_MVT/_CACHE/_TURN` 带 `request_id NOT LIKE '%::sub::%'`,`_TOOL` 不带)。
- PG 限制:`percentile_cont(...) WITHIN GROUP` **不支持 `FILTER`**;按指定子集求分位用 `ORDER BY CASE WHEN <cond> THEN <expr> END`(非该子集 → NULL,被 `percentile_cont` 忽略)。`sum/count` 的 `FILTER` 可用。
- 路由 `router = APIRouter(prefix="/api/v0/observability")`,`_SESSION_FACTORY = SessionLocal`,`/chatloop/aggregates` 是 `def`(threadpool)。
- `dashboard/derive/observability.py`:`load_aggregates(backend_url, window="7d")` 用 `urllib`。
- `dashboard/server.py`:`chatloop_observability_view(request)` async,`os.getenv("BACKEND_BASE_URL", "http://localhost:8000")`,`templates.get_template(...).render(...)`。模板已 `extends base.html`,用 `.report-*` + 设计 token(`--accent` indigo / `--hair` / `--surface` / `--mono`)。

---

### Task 1: 后端 — 任意范围聚合(SQL 改 `:start/:end` + 范围解析)

**Files:**
- Modify: `backend/app/services/trace_analytics.py`
- Test: `backend/tests/integration/test_trace_analytics.py`

- [ ] **Step 1: 写失败测试**

在 `test_trace_analytics.py` 末尾追加:

```python
from datetime import date


def test_aggregate_explicit_range(db_session) -> None:
    # 6/10 一条工具 span,6/05 一条(范围外)
    _span(db_session, span_id="r-in", request_id="rr1", name="tool:get_quote",
          metadata={"kind": "tool", "latency_ms": 800, "cached": False, "success": True},
          secs_ago=2 * 86400 + 100)   # ~2 天前(落在 6/10 那侧)
    _span(db_session, span_id="r-out", request_id="rr2", name="tool:get_quote",
          metadata={"kind": "tool", "latency_ms": 9000, "cached": False, "success": True},
          secs_ago=9 * 86400)         # ~9 天前(范围外)
    db_session.flush()

    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    today = date.today()
    agg = analytics.aggregate(start=today - timedelta(days=4), end=today)

    tools = {t.tool_name: t for t in agg.tool_latency}
    assert "get_quote" in tools
    assert tools["get_quote"].calls == 1          # 只数范围内那条
    assert tools["get_quote"].max_ms < 1000        # 9000ms 那条被排除


def test_aggregate_from_gt_to_raises(db_session) -> None:
    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    today = date.today()
    try:
        analytics.aggregate(start=today, end=today - timedelta(days=1))
        raise AssertionError("should raise")
    except ValueError:
        pass
```

(注:`_span` 已有 `secs_ago` 参数;`timedelta` 已 import。)

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/integration/test_trace_analytics.py -k "explicit_range or from_gt_to" -v`
Expected: FAIL —— `aggregate() got an unexpected keyword argument 'start'`

- [ ] **Step 3: 实现 — 4 条 SQL 改 `:start/:end` + 范围解析 + aggregate 签名**

把 `trace_analytics.py` 顶部 import 加 `date`/`datetime`/`timedelta`/`UTC`:

```python
from datetime import UTC, date, datetime, timedelta
```

4 个 SQL 常量:把每处 `started_at >= now() - (:interval)::interval` 替换为
`started_at >= :start AND started_at < :end`(其余不变)。例如 `_TOOL_SQL`:

```python
_TOOL_SQL = text("""
SELECT replace(name, 'tool:', '') AS tool_name,
       count(*) AS calls,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (metadata->>'latency_ms')::numeric) AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY (metadata->>'latency_ms')::numeric) AS p95_ms,
       max((metadata->>'latency_ms')::numeric) AS max_ms,
       avg(CASE WHEN (metadata->>'success')::boolean THEN 1.0 ELSE 0.0 END) AS success_rate,
       avg(CASE WHEN (metadata->>'cached')::boolean THEN 1.0 ELSE 0.0 END) AS cache_hit_rate
FROM trace_spans
WHERE name LIKE 'tool:%' AND started_at >= :start AND started_at < :end
GROUP BY tool_name ORDER BY p95_ms DESC
""")
```

`_MVT_SQL` / `_CACHE_SQL` / `_TURN_SQL` 同样把 `started_at >= now() - (:interval)::interval`
换成 `started_at >= :start AND started_at < :end`,保留它们各自的 `AND request_id NOT LIKE '%::sub::%'`。

加范围解析(放在类外或类内 staticmethod,这里给模块级函数):

```python
def _resolve_range(
    window: str | None, start: date | None, end: date | None
) -> tuple[datetime, datetime]:
    """解析成 [start_ts, end_ts)(UTC)。end 含「止日当天」→ end_ts = (end+1天) 0 点。"""
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("start 与 end 必须同时给")
        if start > end:
            raise ValueError(f"start({start}) 不能晚于 end({end})")
        start_ts = datetime(start.year, start.month, start.day, tzinfo=UTC)
        end_ts = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
        return start_ts, end_ts
    win = window or "7d"
    days = {"1d": 1, "7d": 7, "30d": 30}.get(win)
    if days is None:
        raise ValueError(f"invalid window: {win!r} (allowed: ['1d', '30d', '7d'])")
    today = datetime.now(UTC).date()
    end_ts = datetime(today.year, today.month, today.day, tzinfo=UTC) + timedelta(days=1)
    return end_ts - timedelta(days=days), end_ts
```

`aggregate` 改签名(`window` 仍兼容):

```python
    def aggregate(
        self, window: str | None = None, *, start: date | None = None, end: date | None = None
    ) -> ChatloopAggregates:
        start_ts, end_ts = _resolve_range(window, start, end)
        params = {"start": start_ts, "end": end_ts}
        with self._sf() as s:
            tool_rows = s.execute(_TOOL_SQL, params).mappings().all()
            mvt = s.execute(_MVT_SQL, params).mappings().one()
            cache = s.execute(_CACHE_SQL, params).mappings().one()
            turn = s.execute(_TURN_SQL, params).mappings().one()
        # ... 其余(组装 ChatloopAggregates)不变,删掉旧的 window 字段来源:
        return ChatloopAggregates(window=window or f"{start}~{end}", ...)
```

(`ChatloopAggregates.window` 字段保留;无 window 时填 `"{start}~{end}"` 字样。其余组装逻辑原样。)
旧 `aggregate(window="7d")` 默认值删掉(改默认 `None`),`test_invalid_window_raises` 仍过(`aggregate("99y")` → `_resolve_range` 抛 ValueError)。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/integration/test_trace_analytics.py -v`
Expected: PASS(原有 + 新 2 个)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trace_analytics.py backend/tests/integration/test_trace_analytics.py
git commit -m "feat(chatloop): 聚合支持任意起止范围(SQL 改 start/end + 范围解析)"
```

---

### Task 2: 后端 — 逐日分桶

**Files:**
- Modify: `backend/app/services/trace_analytics.py`
- Test: `backend/tests/integration/test_trace_analytics.py`

- [ ] **Step 1: 写失败测试**

追加(用已有 `_span` 的 `secs_ago` 把 span 放到不同天):

```python
def test_daily_buckets(db_session) -> None:
    # 今天:1 模型 + 1 工具;昨天:1 模型(无工具);子循环一条(应排除)
    _span(db_session, span_id="d1", request_id="t-today", name="LLMService.stream_step",
          metadata={"prompt_tokens": 1000, "cached_tokens": 700, "cost_cny": 0.02, "latency_ms": 2000},
          secs_ago=120)
    _span(db_session, span_id="d2", request_id="t-today", name="tool:kb_search",
          metadata={"kind": "tool", "latency_ms": 3000, "cached": False, "success": True},
          secs_ago=120)
    _span(db_session, span_id="d3", request_id="t-yday", name="LLMService.stream_step",
          metadata={"prompt_tokens": 500, "cached_tokens": 250, "cost_cny": 0.01, "latency_ms": 1500},
          secs_ago=86400 + 120)
    _span(db_session, span_id="d4", request_id="t-today::sub::sub-0", name="LLMService.stream_step",
          metadata={"prompt_tokens": 9999, "cached_tokens": 0, "cost_cny": 9.0, "latency_ms": 9},
          secs_ago=120)
    db_session.flush()

    from datetime import date
    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    days = analytics.daily(date.today() - timedelta(days=3), date.today())
    by = {d.date: d for d in days}

    today = date.today()
    assert today in by and (today - timedelta(days=1)) in by
    assert by[today].turns == 1                       # 子循环不算 turn
    assert by[today].tool_calls == 1
    assert by[today].p95_ms is not None and by[today].p95_ms >= 3000 - 1
    assert abs(by[today].cache_hit_rate - 0.7) < 1e-6
    assert by[today - timedelta(days=1)].p95_ms is None  # 昨天无工具 span
    assert by[today].cost_cny < 1.0                   # 子循环 9.0 被排除
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/integration/test_trace_analytics.py::test_daily_buckets -v`
Expected: FAIL —— `'ChatloopTraceAnalytics' object has no attribute 'daily'`

- [ ] **Step 3: 实现 — DayBucket / ChatloopDaily + daily() + SQL**

加 SQL 常量(p95 用 CASE 子集,不用 FILTER):

```python
_DAILY_SQL = text("""
SELECT (started_at AT TIME ZONE 'UTC')::date AS day,
       COALESCE(sum((metadata->>'cost_cny')::numeric)
                FILTER (WHERE name = 'LLMService.stream_step'), 0) AS cost_cny,
       count(DISTINCT request_id) AS turns,
       count(*) FILTER (WHERE name = 'LLMService.stream_step') AS model_calls,
       count(*) FILTER (WHERE name LIKE 'tool:%') AS tool_calls,
       percentile_cont(0.95) WITHIN GROUP (
         ORDER BY CASE WHEN name LIKE 'tool:%' THEN (metadata->>'latency_ms')::numeric END
       ) AS p95_ms,
       sum((metadata->>'cached_tokens')::numeric)
         FILTER (WHERE name = 'LLMService.stream_step') AS cached,
       sum((metadata->>'prompt_tokens')::numeric)
         FILTER (WHERE name = 'LLMService.stream_step') AS prompt
FROM trace_spans
WHERE started_at >= :start AND started_at < :end
  AND (name = 'LLMService.stream_step' OR name LIKE 'tool:%')
  AND request_id NOT LIKE '%::sub::%'
GROUP BY day ORDER BY day
""")
```

模型 + 方法:

```python
class DayBucket(BaseModel):
    date: date
    cost_cny: float
    turns: int
    model_calls: int
    tool_calls: int
    p95_ms: float | None
    cache_hit_rate: float | None


class ChatloopDaily(BaseModel):
    days: list[DayBucket]
```

```python
    def daily(self, start: date, end: date) -> list[DayBucket]:
        start_ts, end_ts = _resolve_range(None, start, end)
        with self._sf() as s:
            rows = s.execute(_DAILY_SQL, {"start": start_ts, "end": end_ts}).mappings().all()
        out: list[DayBucket] = []
        for r in rows:
            prompt = float(r["prompt"] or 0)
            out.append(DayBucket(
                date=r["day"],
                cost_cny=float(r["cost_cny"] or 0),
                turns=int(r["turns"] or 0),
                model_calls=int(r["model_calls"] or 0),
                tool_calls=int(r["tool_calls"] or 0),
                p95_ms=(float(r["p95_ms"]) if r["p95_ms"] is not None else None),
                cache_hit_rate=(float(r["cached"] or 0) / prompt if prompt else None),
            ))
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/integration/test_trace_analytics.py::test_daily_buckets -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trace_analytics.py backend/tests/integration/test_trace_analytics.py
git commit -m "feat(chatloop): trace 逐日分桶(每天 花费/轮数/p95/命中率)"
```

---

### Task 3: 后端 — 路由(aggregates 加 from/to + 新 /daily)

**Files:**
- Modify: `backend/app/router/observability_router.py`
- Test: `backend/tests/integration/test_observability_api.py`

- [ ] **Step 1: 写失败测试**

追加:

```python
def test_aggregates_accepts_from_to(db_session) -> None:
    _seed(db_session)  # 已有:5s 前一条 tool:get_quote
    from datetime import date
    today = date.today().isoformat()
    resp = _client(db_session).get(
        f"/api/v0/observability/chatloop/aggregates?from={today}&to={today}"
    )
    assert resp.status_code == 200
    assert any(t["tool_name"] == "get_quote" for t in resp.json()["tool_latency"])


def test_daily_endpoint(db_session) -> None:
    _seed(db_session)
    from datetime import date, timedelta
    frm = (date.today() - timedelta(days=3)).isoformat()
    to = date.today().isoformat()
    resp = _client(db_session).get(
        f"/api/v0/observability/chatloop/daily?from={frm}&to={to}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "days" in body and isinstance(body["days"], list)
    assert "secret_arg" not in resp.text and "茅台" not in resp.text  # 隐私
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest backend/tests/integration/test_observability_api.py -k "from_to or daily" -v`
Expected: FAIL(daily 端点 404 / aggregates 不认 from)

- [ ] **Step 3: 实现路由**

`observability_router.py` 改 import + 两个端点:

```python
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.database import SessionLocal
from app.services.trace_analytics import (
    ChatloopAggregates,
    ChatloopDaily,
    ChatloopTraceAnalytics,
)

router = APIRouter(prefix="/api/v0/observability", tags=["observability"])
_SESSION_FACTORY = SessionLocal


@router.get("/chatloop/aggregates", response_model=ChatloopAggregates)
def chatloop_aggregates(
    window: str | None = Query(None),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
) -> ChatloopAggregates:
    analytics = ChatloopTraceAnalytics(_SESSION_FACTORY)
    try:
        return analytics.aggregate(window=window, start=from_, end=to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/chatloop/daily", response_model=ChatloopDaily)
def chatloop_daily(
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
) -> ChatloopDaily:
    analytics = ChatloopTraceAnalytics(_SESSION_FACTORY)
    try:
        return ChatloopDaily(days=analytics.daily(from_, to))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

(默认 `aggregate(window=None,...)` → `_resolve_range` 回退 `7d`,保持无参时近 7 天。)

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest backend/tests/integration/test_observability_api.py -v`
Expected: PASS(原有 + 新 2 个)

- [ ] **Step 5: Commit**

```bash
git add backend/app/router/observability_router.py backend/tests/integration/test_observability_api.py
git commit -m "feat(chatloop): 可观测性 API 加 from/to 范围 + /daily 逐日端点"
```

---

### Task 4: 前端 — 日历网格构造(纯函数 + 两次点选 href 语义)

**Files:**
- Create: `dashboard/derive/calendar.py`
- Test: `dashboard/tests/integration/test_calendar.py`

- [ ] **Step 1: 写失败测试**

```python
"""build_calendar 纯函数 —— 网格 / 着色 / 两次点选 href 语义。"""
from __future__ import annotations

from datetime import date

from dashboard.derive.calendar import build_calendar


def _days(items):  # items: {iso: value}
    return [{"date": k, "cost_cny": v, "turns": v, "p95_ms": v, "cache_hit_rate": v}
            for k, v in items.items()]


def test_grid_weeks_and_empty_cells() -> None:
    cal = build_calendar(
        days=_days({"2026-06-08": 10.0, "2026-06-10": 30.0}),
        cal_from=date(2026, 6, 8), cal_to=date(2026, 6, 14),
        metric="cost", sel_from=date(2026, 6, 10), sel_to=date(2026, 6, 10),
    )
    flat = [c for wk in cal.weeks for c in wk.cells]
    by = {c.date: c for c in flat if c.date}
    assert by[date(2026, 6, 8)].value == 10.0 and not by[date(2026, 6, 8)].empty
    assert by[date(2026, 6, 9)].empty            # 无数据 → 空格
    assert by[date(2026, 6, 10)].intensity == 4  # 最大值 → 满档(1..4)


def test_href_single_to_range_then_range_to_single() -> None:
    cal = build_calendar(
        days=_days({"2026-06-10": 1.0, "2026-06-12": 1.0}),
        cal_from=date(2026, 6, 8), cal_to=date(2026, 6, 14),
        metric="p95", sel_from=date(2026, 6, 10), sel_to=date(2026, 6, 10),  # 当前单天 6/10
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
        cal_from=date(2026, 6, 8), cal_to=date(2026, 6, 14),
        metric="cost", sel_from=date(2026, 6, 9), sel_to=date(2026, 6, 12),  # 当前是区间
    )
    by2 = {c.date: c for wk in cal2.weeks for c in wk.cells if c.date}
    # 当前是区间 → 点任一天 D 应重置为单天 [D, D]
    assert "from=2026-06-10" in by2[date(2026, 6, 10)].href
    assert "to=2026-06-10" in by2[date(2026, 6, 10)].href
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest dashboard/tests/integration/test_calendar.py -v`
Expected: FAIL —— `ModuleNotFoundError: dashboard.derive.calendar`

- [ ] **Step 3: 实现 build_calendar**

```python
"""日历热力图网格构造 —— 纯函数,服务端渲染(每格 href 编码下一步选择)。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

_METRIC_KEY = {"cost": "cost_cny", "turns": "turns", "p95": "p95_ms", "cache": "cache_hit_rate"}


@dataclass
class Cell:
    date: date | None
    value: float | None = None
    intensity: int = 0       # 0=无数据/空;1..4=深浅
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
    days: list[dict], cal_from: date, cal_to: date, metric: str,
    sel_from: date, sel_to: date,
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
                wk.cells.append(Cell(
                    date=cur, value=v, intensity=intensity, empty=(v is None),
                    in_sel=(sel_from <= cur <= sel_to),
                    href=_next_href(cur, metric, sel_from, sel_to),
                ))
            cur += timedelta(days=1)
        weeks.append(wk)
    return Calendar(weeks=weeks, metric=metric)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest dashboard/tests/integration/test_calendar.py -v`
Expected: PASS(2)

- [ ] **Step 5: Commit**

```bash
git add dashboard/derive/calendar.py dashboard/tests/integration/test_calendar.py
git commit -m "feat(dashboard): 日历网格纯函数(着色 + 两次点选 href 语义)"
```

---

### Task 5: 前端 — derive + handler + 模板接通

**Files:**
- Modify: `dashboard/derive/observability.py`
- Modify: `dashboard/server.py`
- Modify: `dashboard/templates/chatloop_observability.html`
- Test: `dashboard/tests/integration/test_chatloop_observability_page.py`

- [ ] **Step 1: 写失败测试**

在 `test_chatloop_observability_page.py` 追加(stub 两个 loader):

```python
_DAILY = {"days": [
    {"date": "2026-06-10", "cost_cny": 0.04, "turns": 5, "model_calls": 12,
     "tool_calls": 8, "p95_ms": 4200, "cache_hit_rate": 0.7},
]}


def test_calendar_renders(monkeypatch) -> None:
    monkeypatch.setattr(obs, "load_aggregates", lambda *a, **k: _FAKE)
    monkeypatch.setattr(obs, "load_daily", lambda *a, **k: _DAILY)
    resp = TestClient(app).get("/eval/chatloop-observability?metric=cost")
    assert resp.status_code == 200
    assert "obs-cal" in resp.text            # 日历容器
    assert "?from=" in resp.text             # 某格的选择链接
    assert "metric=cost" in resp.text


def test_calendar_degrades_when_daily_down(monkeypatch) -> None:
    monkeypatch.setattr(obs, "load_aggregates", lambda *a, **k: _FAKE)
    def _boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(obs, "load_daily", _boom)
    resp = TestClient(app).get("/eval/chatloop-observability")
    assert resp.status_code == 200           # 日历挂了也不崩
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest dashboard/tests/integration/test_chatloop_observability_page.py -k calendar -v`
Expected: FAIL（`load_daily` 不存在 / 模板无 `obs-cal`）

- [ ] **Step 3: derive 加 load_daily + load_aggregates 支持 from/to**

`dashboard/derive/observability.py`:

```python
def load_aggregates(backend_url: str, window: str | None = None,
                    frm: str | None = None, to: str | None = None) -> dict:
    base = f"{backend_url.rstrip('/')}/api/v0/observability/chatloop/aggregates"
    if frm and to:
        url = f"{base}?from={frm}&to={to}"
    else:
        url = f"{base}?window={window or '7d'}"
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def load_daily(backend_url: str, frm: str, to: str) -> dict:
    url = (f"{backend_url.rstrip('/')}/api/v0/observability/chatloop/daily"
           f"?from={frm}&to={to}")
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 4: handler 解析参数 + 拉两份 + build_calendar**

`dashboard/server.py` 的 `chatloop_observability_view` 改为:

```python
async def chatloop_observability_view(request: Request) -> HTMLResponse:
    from datetime import date, timedelta

    from dashboard.derive.calendar import build_calendar
    from dashboard.derive.observability import load_aggregates, load_daily

    backend = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")
    qp = request.query_params
    metric = qp.get("metric", "cost")
    if metric not in ("cost", "turns", "p95", "cache"):
        metric = "cost"
    today = date.today()

    def _parse(s, default):
        try:
            return date.fromisoformat(s) if s else default
        except ValueError:
            return default

    sel_to = _parse(qp.get("to"), today)
    sel_from = _parse(qp.get("from"), today - timedelta(days=6))
    if sel_from > sel_to:
        sel_from, sel_to = sel_to, sel_from
    cal_from, cal_to = today - timedelta(days=90), today

    try:
        agg = load_aggregates(backend, frm=sel_from.isoformat(), to=sel_to.isoformat())
    except Exception as e:  # noqa: BLE001
        logger.warning("observability aggregates fetch failed: %s", e)
        agg = None
    try:
        daily = load_daily(backend, cal_from.isoformat(), cal_to.isoformat())
        cal = build_calendar(daily["days"], cal_from, cal_to, metric, sel_from, sel_to)
    except Exception as e:  # noqa: BLE001
        logger.warning("observability daily fetch failed: %s", e)
        cal = None

    template = templates.get_template("chatloop_observability.html")
    return HTMLResponse(template.render(
        agg=agg, cal=cal, metric=metric, sel_from=sel_from, sel_to=sel_to,
        active_nav="eval",
    ))
```

- [ ] **Step 5: 模板加日历区**

`dashboard/templates/chatloop_observability.html`:把原来的 `.obs-windows`(1d/7d/30d pill)那段**替换**为「指标下拉 + 快捷 + 日历」;卡片+表区不动(仍 `{% if agg is none %}`)。新增样式与结构:

```html
  <style>
    /* ...保留原有 .obs-* 样式... 追加: */
    .obs-cal { display: flex; flex-direction: column; gap: 3px; margin-top: 6px; }
    .obs-cal-row { display: flex; gap: 3px; }
    .obs-cell { width: 15px; height: 15px; border-radius: 3px; background: var(--hair-2); }
    .obs-cell.l1 { background: var(--accent-soft); }
    .obs-cell.l2 { background: rgba(94,92,230,0.32); }
    .obs-cell.l3 { background: rgba(94,92,230,0.60); }
    .obs-cell.l4 { background: var(--accent); }
    .obs-cell.sel { outline: 2px solid var(--accent-deep); outline-offset: 1px; }
    .obs-cell.pad { background: transparent; }
    .obs-metric a { font-family: var(--mono); font-size: 11px; padding: 3px 10px;
      border-radius: var(--radius-pill); text-decoration: none; color: var(--fg-mute);
      border: 1px solid var(--hair); }
    .obs-metric a.on { background: var(--accent-soft); color: var(--accent-deep);
      border-color: var(--accent-deep); }
    .obs-quick a { font-family: var(--mono); font-size: 11px; color: var(--fg-mute);
      text-decoration: none; margin-right: 10px; }
    .obs-quick a:hover { color: var(--accent); }
  </style>
```

在 `.report-head` 内,把 `.obs-windows` 那段替换为:

```html
    <div class="obs-metric" style="display:flex;gap:6px;margin-top:4px;">
      {% set labels = {'cost':'花费','turns':'调用量','p95':'p95 耗时','cache':'命中率'} %}
      {% for m, lab in labels.items() %}
        <a class="{{ 'on' if m == metric else '' }}"
           href="?from={{ sel_from }}&to={{ sel_to }}&metric={{ m }}">{{ lab }}</a>
      {% endfor %}
    </div>
    <div class="obs-quick" style="margin-top:8px;">
      <span style="color:var(--fg-faint);font-size:11px;">快捷:</span>
      <a href="?from={{ sel_to }}&to={{ sel_to }}&metric={{ metric }}">今天</a>
      <a href="?metric={{ metric }}">近 7 天</a>
    </div>
    {% if cal %}
    <div class="obs-cal" data-testid="obs-cal" style="margin-top:10px;">
      {% for wk in cal.weeks %}
      <div class="obs-cal-row">
        {% for c in wk.cells %}
          {% if c.date is none %}
            <span class="obs-cell pad"></span>
          {% else %}
            <a class="obs-cell l{{ c.intensity }} {{ 'sel' if c.in_sel else '' }}"
               href="{{ c.href }}" title="{{ c.date }}{% if not c.empty %} · {{ '%.2f' % c.value }}{% endif %}"></a>
          {% endif %}
        {% endfor %}
      </div>
      {% endfor %}
    </div>
    {% else %}
      <p class="report-body" style="margin-top:8px;">日历数据暂不可用。</p>
    {% endif %}
    <p class="report-subtitle" style="margin-top:8px;font-size:13px;">
      已选 <code>{{ sel_from }}</code> — <code>{{ sel_to }}</code>(点起点、再点止选一段)
    </p>
```

(注:`obs-cal` 出现在 class 与 data-testid;测试断言 `"obs-cal"` 命中。`?from=&to=` 也命中。)

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest dashboard/tests/integration/test_chatloop_observability_page.py -v`
Expected: PASS(原有 3 + 新 2)

- [ ] **Step 7: Commit**

```bash
git add dashboard/derive/observability.py dashboard/server.py dashboard/templates/chatloop_observability.html dashboard/tests/integration/test_chatloop_observability_page.py
git commit -m "feat(dashboard): 日历热力图 + 指标下拉 + 两次点选范围接通"
```

---

## 收尾(执行 pipeline)

- [ ] 全量回归(repo root)`pytest backend/tests -m "not slow and not live_only" -q` + `ruff format --check` + `ruff check` + `mypy`(都绿;Milvus/sandbox 本地 env 失败无关)。
- [ ] dashboard 测试 `pytest dashboard/tests/integration/test_calendar.py dashboard/tests/integration/test_chatloop_observability_page.py`(Windows .venv)。
- [ ] 浏览器实拍:起真后端(seed 跨多天 span)+ 看板,验证日历着色、点起止选段、指标下拉。
- [ ] 提 PR base main,CI 绿。

## Self-Review 记录

- **Spec 覆盖**:任意范围聚合(Task 1)/ 逐日分桶(Task 2)/ from-to + /daily 端点(Task 3)/ 日历网格 + 两次点选 href(Task 4)/ 指标下拉 + 快捷 + 接通 + 降级(Task 5)—— spec §4.1/4.2/4.3 全覆盖。非目标(小时级 / 拖拽 / 图表库 / 新表 / 客户端 JS)均未触碰。
- **Placeholder 扫描**:每个 code step 有完整代码与命令。
- **类型一致**:`DayBucket`/`ChatloopDaily`(Task 2)→ 路由 response_model(Task 3)→ derive `load_daily`(Task 5);`build_calendar` 返回 `Calendar.weeks[].cells[]`(Task 4)→ 模板按 `wk.cells` / `c.date/intensity/in_sel/href` 渲染(Task 5),字段名一致;`_resolve_range`(Task 1)被 `aggregate` 与 `daily` 共用。
