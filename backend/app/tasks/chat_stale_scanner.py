"""Stale scanner — Celery Beat task that detects stuck `running` chat_tasks。

Spec § 6.6:每分钟扫,扫到 status='running' + started_at 5min 前 → mark error
+ XADD `{type:error_done,reason:stale}` 让在线 SSE handler 即时收到 → 前端 UI
看到 error badge + retry 按钮。

Worker crash / Redis chaos / 任意原因卡 running 的 task 都会被 1 分钟内自愈。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def scan_stale_chat_tasks_async(
    *,
    session_factory: Callable[[], Any],
    redis: Any,
    stale_minutes: int = 5,
) -> int:
    """Find + mark + emit stale events. Returns count of tasks marked.

    DI-friendly:tests inject fakeredis + sqlite session_factory + 控制 stale_minutes。
    """
    task_repo = ChatTaskRepo(session_factory)
    bus = ChatEventBus(redis=redis)

    stale_tasks = await task_repo.find_stale_running_tasks(min_age_minutes=stale_minutes)
    if not stale_tasks:
        return 0

    marked = 0
    for task in stale_tasks:
        try:
            await task_repo.mark_error(
                task.id,  # type: ignore[arg-type]
                error_message=(
                    f"stale: no heartbeat for {stale_minutes}+ minutes (worker likely crashed)"
                ),
            )
            try:
                await bus.xadd_event(
                    task.session_id,  # type: ignore[arg-type]
                    task.id,  # type: ignore[arg-type]
                    {
                        "type": "error_done",
                        "reason": "stale",
                        "message": "task timed out (stale scanner)",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("stale scanner xadd failed for %s: %s", task.id, exc)
            marked += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("stale scanner mark_error failed for %s: %s", task.id, exc)
    logger.info("Stale scanner: marked %d/%d tasks", marked, len(stale_tasks))
    return marked


@celery_app.task(name="app.tasks.chat_stale_scanner.scan_stale_chat_tasks")
def scan_stale_chat_tasks() -> int:
    """Celery Beat entry. Runs every minute(configured in celery_beat_schedule.py)。"""
    import asyncio

    import redis.asyncio as redis_async
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.app_main import _sqlalchemy_async_pg_url

    async def _run() -> int:
        engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis_async.Redis.from_url(redis_url, decode_responses=False)
            try:
                return await scan_stale_chat_tasks_async(
                    session_factory=factory,
                    redis=redis_client,
                    stale_minutes=5,
                )
            finally:
                await redis_client.aclose()
        finally:
            await engine.dispose()

    return asyncio.run(_run())
