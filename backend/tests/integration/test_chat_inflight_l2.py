# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence(同 plan 2
# 其他 chat 测试 pattern,参见 test_chat_runner.py / test_chat_inflight_plan2.py)。
"""Plan 2 Task 8 L2 sanity — 真 Celery worker subprocess + 真 Redis 端到端冒烟测试。

测试约定:
- 跑前要求 REDIS_URL env 指向 production-grade Redis(industry_redis docker 或
  CI broker),没有则跳过(testcontainers 也算)
- 用 conftest_celery 的 redis_url + celery_worker_subprocess fixture
- PG 要 reachable(env POSTGRES_*) — L2 不 mock,跟 production wiring 一致

测试 case:1 个 sanity end-to-end,只 verify:
  enqueue → Celery worker subprocess 实际 pick up → run_chat wrapper 被调用
  → task.status 离开 'queued'(running / done / partial / error 都算)

Plan 2 Task 8 scope 不验:
- assistant 落库完整性(那需要 LLM 真跑出 token, 走 LLM HTTP call)
- 客户端断开守护(Plan 3 Task 9)
- chaos(杀 worker / 杀 redis, Plan 3)

本 test 只守护「production wiring 通 — wrapper 不再 raise NotImplementedError」。
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — registers users table
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_runner import enqueue_run_chat
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

pytestmark = [
    pytest.mark.skipif(
        "REDIS_URL" not in os.environ and "CELERY_BROKER_URL" not in os.environ,
        reason="L2 needs REDIS_URL or CELERY_BROKER_URL (production redis reachable)",
    ),
    pytest.mark.skipif(
        "POSTGRES_HOST" not in os.environ and not os.path.exists("/var/run/postgresql"),
        reason="L2 needs PG reachable (POSTGRES_HOST env or local socket)",
    ),
]


_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks", "chat_messages")

# Test PG (industry_assistant_test) may have schema drift from prior CI runs —
# 真 PG schema 可能旧于当前 model(message_count / last_msg_preview 是 v0.9 chat 加的列,
# 旧 CI fixture create_all 出来的表不含).  create_all 对已存在的表是 no-op,所以这里
# 显式 ALTER TABLE ADD COLUMN IF NOT EXISTS 同步缺失的列.
_ADDITIVE_SCHEMA_PATCHES = (
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS last_msg_preview TEXT",
)


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)


@pytest_asyncio.fixture
async def pg_engine() -> AsyncEngine:
    """Build real PG async engine using same URL helper as worker."""
    from app.app_main import _sqlalchemy_async_pg_url
    from sqlalchemy import text as _sql_text

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
        # Patch additive schema drift on test PG (idempotent ALTER TABLE)
        for patch_sql in _ADDITIVE_SCHEMA_PATCHES:
            await conn.execute(_sql_text(patch_sql))
    return engine


@pytest.fixture(scope="module")
def use_celery_worker(redis_url: str, celery_worker_subprocess: None) -> str:
    """Compose redis_url + celery_worker_subprocess from conftest_celery.

    Ensures env vars (REDIS_URL + Celery broker) are set so that both
    the in-test enqueue path AND the worker subprocess see the same Redis.
    """
    os.environ["REDIS_URL"] = redis_url
    os.environ["CELERY_BROKER_URL"] = redis_url
    os.environ["CELERY_RESULT_BACKEND"] = redis_url
    return redis_url


@pytest.mark.asyncio
async def test_celery_worker_picks_up_run_chat_task(
    use_celery_worker: str,
    pg_engine: AsyncEngine,
) -> None:
    """Sanity:enqueue → worker subprocess pick up → wrapper 被调用(task.status 离开 queued)。

    NOTE:本 test 不 assert assistant message 真落库或 graph 真完成 — 那会触发
    真 LLM HTTP call。最弱可接受信号是 task.status != 'queued'(说明 Celery
    worker 真起来 + wrapper 真被 invoke + asyncio.run(run_chat_async(...)) 进入,
    然后无论后续 LLM 成功/失败,status 都会从 queued → running → done/error)。
    """
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    sid = uuid.uuid4()
    async with factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="L2 sanity"))
        await sess.commit()

    task_repo = ChatTaskRepo(factory)
    # ChatTask.user_id 是 nullable (anonymous pre-auth pattern; 见 app.models.chat.ChatTask).
    # 用 None 避免 FK 校验失败 — 真 user 行不存在.
    # 但 worker 入参 user_id 仍需是 UUID string(run_chat 用它构 thread_id), 这里
    # generate 一个本地 uuid 仅用作 worker 入参 token, 不写库.
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"anon:{sid}",
        initial_prompt_message_id=None,
    )
    worker_uid = uuid.uuid4()  # placeholder for run_chat signature; not persisted

    # Enqueue → worker should pick up via Celery broker
    enqueue_run_chat(
        task_id=str(task.id),
        session_id=str(sid),
        user_id=str(worker_uid),
        user_message="ping",
    )

    # Wait up to 60s for task to leave 'queued' state
    import asyncio

    deadline = time.time() + 60
    refreshed = None
    while time.time() < deadline:
        refreshed = await task_repo.get_by_id(task.id)
        if refreshed is not None and refreshed.status != "queued":
            break
        await asyncio.sleep(2)

    await pg_engine.dispose()

    assert refreshed is not None, "task disappeared from DB"
    assert refreshed.status != "queued", (
        f"Celery worker never picked up task in 60s — wrapper wiring broken? "
        f"task.status still 'queued', task_id={task.id}"
    )
    # wrapper wiring 通了:status 应该从 queued → running → done|partial|error 之一
    assert refreshed.status in ("running", "done", "partial", "error"), (
        f"Unexpected status: {refreshed.status}"
    )
