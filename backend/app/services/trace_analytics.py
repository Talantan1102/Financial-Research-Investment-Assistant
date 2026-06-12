"""ChatloopTraceAnalytics —— 跨请求聚合 + 逐日分桶 over trace_spans(spec § 4)。

判据:模型 span name = 'LLMService.stream_step';工具 span name LIKE 'tool:%'。
时间下界用 [:start, :end) 绑定参数(防注入);窗口/起止解析见 _resolve_range。
只产出数字,绝不回 span inputs/outputs 原文。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

_WINDOW_DAYS: dict[str, int] = {"1d": 1, "7d": 7, "30d": 30}


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
    days = _WINDOW_DAYS.get(win)
    if days is None:
        raise ValueError(f"invalid window: {win!r} (allowed: {sorted(_WINDOW_DAYS)})")
    today = datetime.now(UTC).date()
    end_ts = datetime(today.year, today.month, today.day, tzinfo=UTC) + timedelta(days=1)
    return end_ts - timedelta(days=days), end_ts


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

_MVT_SQL = text("""
SELECT
  COALESCE(sum(CASE WHEN name = 'LLMService.stream_step'
                    THEN (metadata->>'latency_ms')::numeric ELSE 0 END), 0) AS model_ms,
  COALESCE(sum(CASE WHEN name LIKE 'tool:%'
                    THEN (metadata->>'latency_ms')::numeric ELSE 0 END), 0) AS tool_ms
FROM trace_spans
WHERE started_at >= :start AND started_at < :end
  AND (name = 'LLMService.stream_step' OR name LIKE 'tool:%')
  AND request_id NOT LIKE '%::sub::%'
""")

_CACHE_SQL = text("""
SELECT COALESCE(sum((metadata->>'cached_tokens')::numeric), 0) AS cached,
       COALESCE(sum((metadata->>'prompt_tokens')::numeric), 0) AS prompt
FROM trace_spans
WHERE name = 'LLMService.stream_step' AND started_at >= :start AND started_at < :end
  AND request_id NOT LIKE '%::sub::%'
""")

_TURN_SQL = text("""
WITH per_req AS (
  SELECT request_id,
         sum((metadata->>'cost_cny')::numeric) AS cost,
         extract(epoch from (max(ended_at) - min(started_at))) * 1000 AS wall_ms,
         count(*) FILTER (WHERE name = 'LLMService.stream_step') AS llm_calls,
         count(*) FILTER (WHERE name LIKE 'tool:%') AS tool_calls
  FROM trace_spans
  WHERE started_at >= :start AND started_at < :end
    AND (name = 'LLMService.stream_step' OR name LIKE 'tool:%')
    AND request_id NOT LIKE '%::sub::%'
  GROUP BY request_id
)
SELECT COALESCE(avg(cost), 0) AS avg_cost,
       COALESCE(avg(wall_ms), 0) AS avg_wall_ms,
       COALESCE(avg(llm_calls), 0) AS avg_llm_calls,
       COALESCE(avg(tool_calls), 0) AS avg_tool_calls,
       count(*) AS turn_count
FROM per_req
""")

# 逐日分桶:p95 用 CASE 子集(PG 的 ordered-set 聚合不支持 FILTER)。
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


class ToolLatencyStat(BaseModel):
    tool_name: str
    calls: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    success_rate: float
    cache_hit_rate: float


class ChatloopAggregates(BaseModel):
    window: str
    tool_latency: list[ToolLatencyStat]
    model_ms: float
    tool_ms: float
    model_share: float
    cache_hit_rate: float
    avg_cost_cny: float
    avg_wall_ms: float
    avg_llm_calls: float
    avg_tool_calls: float
    turn_count: int


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


class ChatloopTraceAnalytics:
    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]]) -> None:
        self._sf = session_factory

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

        model_ms = float(mvt["model_ms"] or 0)
        tool_ms = float(mvt["tool_ms"] or 0)
        total = model_ms + tool_ms
        prompt = float(cache["prompt"] or 0)
        cached = float(cache["cached"] or 0)
        label = window if window else f"{start}~{end}"
        return ChatloopAggregates(
            window=label,
            tool_latency=[
                ToolLatencyStat(
                    tool_name=r["tool_name"],
                    calls=int(r["calls"]),
                    p50_ms=float(r["p50_ms"] or 0),
                    p95_ms=float(r["p95_ms"] or 0),
                    max_ms=float(r["max_ms"] or 0),
                    success_rate=float(r["success_rate"] or 0),
                    cache_hit_rate=float(r["cache_hit_rate"] or 0),
                )
                for r in tool_rows
            ],
            model_ms=model_ms,
            tool_ms=tool_ms,
            model_share=(model_ms / total) if total else 0.0,
            cache_hit_rate=(cached / prompt) if prompt else 0.0,
            avg_cost_cny=float(turn["avg_cost"] or 0),
            avg_wall_ms=float(turn["avg_wall_ms"] or 0),
            avg_llm_calls=float(turn["avg_llm_calls"] or 0),
            avg_tool_calls=float(turn["avg_tool_calls"] or 0),
            turn_count=int(turn["turn_count"] or 0),
        )

    def daily(self, start: date, end: date) -> list[DayBucket]:
        start_ts, end_ts = _resolve_range(None, start, end)
        with self._sf() as s:
            rows = s.execute(_DAILY_SQL, {"start": start_ts, "end": end_ts}).mappings().all()
        out: list[DayBucket] = []
        for r in rows:
            prompt = float(r["prompt"] or 0)
            out.append(
                DayBucket(
                    date=r["day"],
                    cost_cny=float(r["cost_cny"] or 0),
                    turns=int(r["turns"] or 0),
                    model_calls=int(r["model_calls"] or 0),
                    tool_calls=int(r["tool_calls"] or 0),
                    p95_ms=(float(r["p95_ms"]) if r["p95_ms"] is not None else None),
                    cache_hit_rate=(float(r["cached"] or 0) / prompt if prompt else None),
                )
            )
        return out
