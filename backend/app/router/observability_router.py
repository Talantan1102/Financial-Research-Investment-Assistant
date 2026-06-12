"""只读可观测性 API —— chatloop trace 聚合(内部观测端点,不带用户 PII)。

sync def 路由 → FastAPI 在 threadpool 跑同步 SQL,不阻塞事件循环。
只返回聚合数字,绝不返回 span inputs/outputs 原文(隐私边界,spec § 6)。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.database import SessionLocal
from app.services.trace_analytics import (
    ChatloopAggregates,
    ChatloopDaily,
    ChatloopTraceAnalytics,
)

router = APIRouter(prefix="/api/v0/observability", tags=["observability"])

# 测试缝:测试用 nullcontext(db_session) 覆盖,生产用 SessionLocal。
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
