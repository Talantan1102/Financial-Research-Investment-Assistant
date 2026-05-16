# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence(参见
# test_chat_task_repo.py / Plan 1 Task 6)。
"""chat_runner L0 unit — eager-style 异步入口测试。

测试策略:
- 不真起 Celery worker;直接 `await run_chat_async(...)`
- in-memory sqlite session_factory + fakeredis Redis
- 用 fake graph stub yield 固定 event 序列

覆盖:
- 正常路径:graph 跑出 token + done → Redis 有 entries + chat_messages 落 assistant
  + chat_tasks=done
- 异常路径:graph raise → Redis 有 error event + chat_tasks=error + error_message 截断
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_runner import run_chat_async
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# chat_messages 模型用 JSONB().with_variant(JSON, "sqlite") 所以 sqlite 也能建。
_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_running_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=uid,
        langgraph_thread_id=f"{uid}:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    return {"session_id": sid, "user_id": uid, "task_id": task.id}


def _build_fake_graph(token_texts: list[str]) -> Any:
    """Stub Graph: astream_events yields tokens + LangGraph done; aget_state returns ckpt."""

    class _FakeGraph:
        async def astream_events(
            self,
            _initial: Any,
            config: Any = None,
            version: str = "v2",
        ) -> AsyncIterator[dict[str, Any]]:
            for t in token_texts:
                yield {
                    "event": "on_chat_model_stream",
                    "name": "model",
                    "data": {"chunk": MagicMock(content=t)},
                }
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_response": "".join(token_texts)}},
            }

        async def aget_state(self, _config: Any) -> Any:
            return MagicMock(config={"configurable": {"checkpoint_id": "ckpt-fake"}})

    return _FakeGraph()


def _build_fake_graph_that_raises(exc: Exception) -> Any:
    class _FakeGraph:
        async def astream_events(
            self,
            _initial: Any,
            config: Any = None,
            version: str = "v2",
        ) -> AsyncIterator[dict[str, Any]]:
            raise exc
            yield  # unreachable; makes mypy/asyncgen happy

        async def aget_state(self, _config: Any) -> Any:
            # error 路径里 finalize_task_persistence 不会调 aget_state
            # (graph_error 非空走 error 分支),但万一调到也要不抛
            return MagicMock(config={"configurable": {}})

    return _FakeGraph()


async def test_run_chat_async_normal_path_xadds_events_and_finalizes_done(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_running_task: dict[str, Any],
) -> None:
    fake_redis = FakeRedis(decode_responses=False)
    fake_graph = _build_fake_graph(["hello", " world"])

    await run_chat_async(
        task_id=seeded_running_task["task_id"],
        graph_factory=lambda: fake_graph,
        session_factory=session_factory,
        redis=fake_redis,
        user_message="echo hello",
        session_id=str(seeded_running_task["session_id"]),
        user_id=seeded_running_task["user_id"],
    )

    # Redis Stream has token x2 + done
    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(
        seeded_running_task["session_id"],
        seeded_running_task["task_id"],
        last_id="0",
        count=100,
        block_ms=10,
    )
    types = [e[1].get("type") for e in entries]
    assert "token" in types
    assert "done" in types

    # PG: assistant row + task done
    msg_repo = ChatSessionRepo(session_factory)
    msgs = await msg_repo.list_messages(str(seeded_running_task["session_id"]))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].status == "done"
    assert assistant_msgs[0].content == "hello world"

    task_repo = ChatTaskRepo(session_factory)
    refreshed = await task_repo.get_by_id(seeded_running_task["task_id"])
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.langgraph_checkpoint_id == "ckpt-fake"


async def test_run_chat_async_llm_error_xadds_error_and_marks_error(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_running_task: dict[str, Any],
) -> None:
    fake_redis = FakeRedis(decode_responses=False)
    fake_graph = _build_fake_graph_that_raises(RuntimeError("simulated 429"))

    await run_chat_async(
        task_id=seeded_running_task["task_id"],
        graph_factory=lambda: fake_graph,
        session_factory=session_factory,
        redis=fake_redis,
        user_message="hi",
        session_id=str(seeded_running_task["session_id"]),
        user_id=seeded_running_task["user_id"],
    )

    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(
        seeded_running_task["session_id"],
        seeded_running_task["task_id"],
        last_id="0",
        count=100,
        block_ms=10,
    )
    types = [e[1].get("type") for e in entries]
    assert "error" in types or "error_done" in types

    task_repo = ChatTaskRepo(session_factory)
    refreshed = await task_repo.get_by_id(seeded_running_task["task_id"])
    assert refreshed is not None
    assert refreshed.status == "error"
    assert refreshed.error_message is not None
    assert "simulated 429" in refreshed.error_message
