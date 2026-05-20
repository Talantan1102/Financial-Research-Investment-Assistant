# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence(参见
# test_chat_task_repo.py / Plan 1 Task 6)。
"""chat_runner L0 unit — eager-style 异步入口测试。

测试策略:
- 不真起 Celery worker;直接 `await run_chat_async(...)`
- 真 PG(industry_assistant_test) async_session_factory + fakeredis Redis
- 用 fake graph stub yield 固定 event 序列

覆盖:
- 正常路径:graph 跑出 token + done → Redis 有 entries + chat_messages 落 assistant
  + chat_tasks=done
- 异常路径:graph raise → Redis 有 error event + chat_tasks=error + error_message 截断
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import MagicMock

import pytest_asyncio
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — 注册 users 表
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_runner import run_chat_async
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def seeded_running_task(
    async_session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    sid = uuid.uuid4()
    # user_id=None: chat_tasks.user_id is nullable FK; random UUID fails PG FK check.
    # run_chat_async only uses user_id for LangGraph thread_id concatenation,
    # so we pass a fixed sentinel string "test-user" at the run_chat_async call site.
    async with async_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(async_session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,  # nullable FK; PG enforces FK so we use None
        langgraph_thread_id=f"test:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    return {"session_id": sid, "user_id": "test-user", "task_id": task.id}


def _async_factory_of(graph: Any) -> Callable[[], Awaitable[Any]]:
    """Wrap a pre-built fake graph in an async factory matching run_chat_async's
    graph_factory: Callable[[], Awaitable[Any]] contract (MCP-only refactor)."""

    async def _factory() -> Any:
        return graph

    return _factory


def _async_factory_of(graph: Any) -> Callable[[], Awaitable[Any]]:
    """Wrap a pre-built fake graph in an async factory matching run_chat_async's
    graph_factory: Callable[[], Awaitable[Any]] contract (MCP-only refactor)."""

    async def _factory() -> Any:
        return graph

    return _factory


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
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_running_task: dict[str, Any],
) -> None:
    fake_redis = FakeRedis(decode_responses=False)
    fake_graph = _build_fake_graph(["hello", " world"])

    await run_chat_async(
        task_id=seeded_running_task["task_id"],
        graph_factory=_async_factory_of(fake_graph),
        session_factory=async_session_factory,
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
    msg_repo = ChatSessionRepo(async_session_factory)
    msgs = await msg_repo.list_messages(str(seeded_running_task["session_id"]))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].status == "done"
    assert assistant_msgs[0].content == "hello world"

    task_repo = ChatTaskRepo(async_session_factory)
    refreshed = await task_repo.get_by_id(seeded_running_task["task_id"])
    assert refreshed is not None
    assert refreshed.status == "done"
    assert refreshed.langgraph_checkpoint_id == "ckpt-fake"


async def test_run_chat_async_llm_error_xadds_error_and_marks_error(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_running_task: dict[str, Any],
) -> None:
    fake_redis = FakeRedis(decode_responses=False)
    fake_graph = _build_fake_graph_that_raises(RuntimeError("simulated 429"))

    await run_chat_async(
        task_id=seeded_running_task["task_id"],
        graph_factory=_async_factory_of(fake_graph),
        session_factory=async_session_factory,
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

    task_repo = ChatTaskRepo(async_session_factory)
    refreshed = await task_repo.get_by_id(seeded_running_task["task_id"])
    assert refreshed is not None
    assert refreshed.status == "error"
    assert refreshed.error_message is not None
    assert "simulated 429" in refreshed.error_message


async def test_run_chat_async_cancel_signal_aborts_graph_and_marks_partial(
    async_session_factory: async_sessionmaker[AsyncSession],
    seeded_running_task: dict[str, Any],
) -> None:
    """模拟 ChatCancelBus.publish_cancel 期间 worker listener 收到 signal,
    graph wrapper 检查 cancel_event → raise → finalize 走 partial 路径。

    Steps:
    1. Build fake graph with 0.3s gap between chunks
    2. Run run_chat_async + 并行 publish cancel after 0.5s(gap 内)
    3. Verify task.status=partial, assistant.status=partial, Redis Stream
       cancelled event
    """
    import asyncio

    from app.services.chat_cancel_bus import ChatCancelBus

    fake_redis = FakeRedis(decode_responses=False)
    cancel_bus = ChatCancelBus(fake_redis)

    # Fake graph yields part1 → 0.3s gap → part2 → 2s gap → done.
    # cancel publish at 0.5s 应该在 part1 yield 之后,part2 之后的检查 cycle 触发。
    class _SlowFakeGraph:
        async def astream_events(
            self,
            _initial: Any,
            config: Any = None,
            version: str = "v2",
        ) -> AsyncIterator[dict[str, Any]]:
            yield {
                "event": "on_chat_model_stream",
                "name": "model",
                "data": {"chunk": MagicMock(content="part1 ")},
            }
            await asyncio.sleep(0.3)
            yield {
                "event": "on_chat_model_stream",
                "name": "model",
                "data": {"chunk": MagicMock(content="part2 ")},
            }
            await asyncio.sleep(2.0)
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_response": "full"}},
            }

        async def aget_state(self, _config: Any) -> Any:
            return MagicMock(config={"configurable": {"checkpoint_id": "ckpt-partial"}})

    fake_graph = _SlowFakeGraph()
    tid = seeded_running_task["task_id"]
    sid = seeded_running_task["session_id"]
    uid = seeded_running_task["user_id"]

    async def trigger_cancel() -> None:
        await asyncio.sleep(0.5)
        await cancel_bus.publish_cancel(tid)

    cancel_trigger = asyncio.create_task(trigger_cancel())

    await run_chat_async(
        task_id=tid,
        graph_factory=_async_factory_of(fake_graph),
        session_factory=async_session_factory,
        redis=fake_redis,
        user_message="cancel me",
        session_id=str(sid),
        user_id=uid,
    )
    await cancel_trigger

    # Assertions: task.status=partial,checkpoint_id 写入
    task_repo = ChatTaskRepo(async_session_factory)
    refreshed = await task_repo.get_by_id(tid)
    assert refreshed is not None
    assert refreshed.status in ("partial", "cancelled"), (
        f"expected partial/cancelled, got {refreshed.status}"
    )

    # PG chat_messages assistant 应该 status=partial,内容含至少 part1
    msg_repo = ChatSessionRepo(async_session_factory)
    msgs = await msg_repo.list_messages(str(sid))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].status in ("partial", "cancelled")
    assert "part1" in assistant_msgs[0].content

    # Redis Stream 应有 cancelled / error_done 终止事件
    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=100, block_ms=10)
    types = [e[1].get("type") for e in entries]
    has_cancel_terminal = "cancelled" in types or any(
        e[1].get("reason") == "cancelled" for e in entries
    )
    assert has_cancel_terminal, f"expected cancelled-style terminal, got types={types}"
