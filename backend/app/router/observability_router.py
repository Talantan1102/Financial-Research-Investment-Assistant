"""只读可观测性 API —— chatloop trace 聚合(内部观测端点,不带用户 PII)。

sync def 路由 → FastAPI 在 threadpool 跑同步 SQL,不阻塞事件循环。
只返回聚合数字,绝不返回 span inputs/outputs 原文(隐私边界,spec § 6)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.database import SessionLocal
from app.services.trace_analytics import ChatloopAggregates, ChatloopTraceAnalytics

router = APIRouter(prefix="/api/v0/observability", tags=["observability"])

# 测试缝:测试用 nullcontext(db_session) 覆盖,生产用 SessionLocal。
_SESSION_FACTORY = SessionLocal


@router.get("/chatloop/aggregates", response_model=ChatloopAggregates)
def chatloop_aggregates(window: str = Query("7d")) -> ChatloopAggregates:
    analytics = ChatloopTraceAnalytics(_SESSION_FACTORY)
    try:
        return analytics.aggregate(window)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
