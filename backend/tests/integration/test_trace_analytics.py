"""ChatloopTraceAnalytics —— seed 模型/工具 span,断言聚合正确。"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta

from app.services.trace_analytics import ChatloopTraceAnalytics
from app.services.trace_models import TraceSpanRow


def _span(db_session, *, span_id, request_id, name, metadata, secs_ago=10, dur_ms=100):
    end = datetime.now(UTC) - timedelta(seconds=secs_ago)
    start = end - timedelta(milliseconds=dur_ms)
    db_session.add(
        TraceSpanRow(
            span_id=span_id,
            request_id=request_id,
            parent_id=None,
            name=name,
            inputs={},
            outputs={},
            attrs_json=metadata,
            started_at=start,
            ended_at=end,
            error=None,
        )
    )


def test_aggregate_tool_and_model(db_session) -> None:
    # 两条 model span(同一 request),两条 tool span(get_quote 慢、search 快+缓存)
    _span(
        db_session,
        span_id="s1",
        request_id="r1",
        name="LLMService.stream_step",
        metadata={
            "prompt_tokens": 1000,
            "completion_tokens": 50,
            "cached_tokens": 800,
            "cost_cny": 0.04,
            "latency_ms": 3000,
        },
    )
    _span(
        db_session,
        span_id="s2",
        request_id="r1",
        name="tool:get_quote",
        metadata={"kind": "tool", "latency_ms": 8000, "cached": False, "success": True},
    )
    _span(
        db_session,
        span_id="s3",
        request_id="r1",
        name="tool:search_kb",
        metadata={"kind": "tool", "latency_ms": 200, "cached": True, "success": True},
    )
    db_session.flush()

    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    agg = analytics.aggregate("7d")

    tools = {t.tool_name: t for t in agg.tool_latency}
    assert tools["get_quote"].p95_ms >= 8000 - 1
    assert tools["search_kb"].cache_hit_rate == 1.0
    # 模型 vs 工具:model=3000, tool=8200
    assert round(agg.model_ms) == 3000
    assert round(agg.tool_ms) == 8200
    assert 0 < agg.model_share < 1
    # KV-cache 命中率 = 800/1000
    assert abs(agg.cache_hit_rate - 0.8) < 1e-6
    assert agg.turn_count == 1
    assert agg.avg_llm_calls == 1
    assert agg.avg_tool_calls == 2


def test_invalid_window_raises(db_session) -> None:
    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    try:
        analytics.aggregate("99y")
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_subagent_spans_excluded_from_turn_aggregates(db_session) -> None:
    # 一个主 turn(r1)+ 一个子循环(r1::sub::sub-0)的模型 span。
    _span(
        db_session,
        span_id="m1",
        request_id="r1",
        name="LLMService.stream_step",
        metadata={"prompt_tokens": 100, "cached_tokens": 0, "cost_cny": 0.01, "latency_ms": 2000},
    )
    _span(
        db_session,
        span_id="m2",
        request_id="r1::sub::sub-0",
        name="LLMService.stream_step",
        metadata={"prompt_tokens": 50, "cached_tokens": 0, "cost_cny": 0.005, "latency_ms": 500},
    )
    db_session.flush()

    agg = ChatloopTraceAnalytics(lambda: nullcontext(db_session)).aggregate("7d")

    # 子循环不算独立 turn,也不并入模型耗时聚合。
    assert agg.turn_count == 1
    assert round(agg.model_ms) == 2000


def test_aggregate_explicit_range(db_session) -> None:
    # 范围内一条(~2 天前),范围外一条(~9 天前,大延迟)
    _span(
        db_session,
        span_id="r-in",
        request_id="rr1",
        name="tool:get_quote",
        metadata={"kind": "tool", "latency_ms": 800, "cached": False, "success": True},
        secs_ago=2 * 86400 + 100,
    )
    _span(
        db_session,
        span_id="r-out",
        request_id="rr2",
        name="tool:get_quote",
        metadata={"kind": "tool", "latency_ms": 9000, "cached": False, "success": True},
        secs_ago=9 * 86400,
    )
    db_session.flush()

    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    today = date.today()
    agg = analytics.aggregate(start=today - timedelta(days=4), end=today)

    tools = {t.tool_name: t for t in agg.tool_latency}
    assert "get_quote" in tools
    assert tools["get_quote"].calls == 1
    assert tools["get_quote"].max_ms < 1000


def test_aggregate_from_gt_to_raises(db_session) -> None:
    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    today = date.today()
    try:
        analytics.aggregate(start=today, end=today - timedelta(days=1))
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_daily_buckets(db_session) -> None:
    # 今天:1 模型 + 1 工具;昨天:1 模型(无工具);子循环一条(应排除)
    _span(
        db_session,
        span_id="d1",
        request_id="t-today",
        name="LLMService.stream_step",
        metadata={
            "prompt_tokens": 1000,
            "cached_tokens": 700,
            "cost_cny": 0.02,
            "latency_ms": 2000,
        },
        secs_ago=120,
    )
    _span(
        db_session,
        span_id="d2",
        request_id="t-today",
        name="tool:kb_search",
        metadata={"kind": "tool", "latency_ms": 3000, "cached": False, "success": True},
        secs_ago=120,
    )
    _span(
        db_session,
        span_id="d3",
        request_id="t-yday",
        name="LLMService.stream_step",
        metadata={"prompt_tokens": 500, "cached_tokens": 250, "cost_cny": 0.01, "latency_ms": 1500},
        secs_ago=86400 + 120,
    )
    _span(
        db_session,
        span_id="d4",
        request_id="t-today::sub::sub-0",
        name="LLMService.stream_step",
        metadata={"prompt_tokens": 9999, "cached_tokens": 0, "cost_cny": 9.0, "latency_ms": 9},
        secs_ago=120,
    )
    db_session.flush()

    analytics = ChatloopTraceAnalytics(lambda: nullcontext(db_session))
    today = datetime.now(UTC).date()  # 日桶按 UTC 切,断言也用 UTC 当天
    days = analytics.daily(today - timedelta(days=3), today)
    by = {d.date: d for d in days}

    yday = today - timedelta(days=1)
    assert today in by and yday in by
    d_today = by[today]
    assert d_today.turns == 1  # 子循环不算 turn
    assert d_today.tool_calls == 1
    assert d_today.p95_ms is not None and d_today.p95_ms >= 3000 - 1
    assert d_today.cache_hit_rate is not None and abs(d_today.cache_hit_rate - 0.7) < 1e-6
    assert by[yday].p95_ms is None  # 昨天无工具 span
    assert d_today.cost_cny < 1.0  # 子循环 9.0 被排除
