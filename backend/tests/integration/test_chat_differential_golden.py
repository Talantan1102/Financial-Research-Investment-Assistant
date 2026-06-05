# mypy: disable-error-code="arg-type"
"""differential golden — spec § 5.2 守护 turn 原子语义不破老路径。

3 cases:
- Case A: cancel(partial content) vs complete(full content)— 终态对比
- Case B: retry 整 turn 重跑(Phase 4 Task 4.3,checkpoint 退役)— parent_task_id 链
  + enqueue 收到 resume_checkpoint_id=None + user_message=原 turn 消息
- Case C: 两轮 prompt + 第二轮 running — active_task_id 路径

测试策略:用已有 L1 fixture(真 PG + fakeredis + ChatTaskRepo + direct DB seed),
不真起 Celery worker。Case A/B 的 cancel/retry 通过直接 mark_* 模拟 worker 行为;
Case C 验 GET /chats/{sid} 返回 active_task_id。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — registers users table
from app.router.chat import (
    get_async_session_factory,
    get_current_user,
    get_redis_async,
)
from app.router.chat import router as chat_router
from app.router.chats import get_repo as get_chats_repo
from app.router.chats import router as chats_router
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


@pytest.fixture
def session_factory(
    pg_async_session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    """Alias to global pg_async_session_factory — real PG, no sqlite.

    PR-A T15: replaced sqlite+aiosqlite (broke on JSONB after with_variant removal).
    """
    return pg_async_session_factory


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


def _chat_client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
) -> TestClient:
    """Build FastAPI TestClient with chat router (POST /chat/retry/{tid} etc.)."""
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_current_user] = lambda: _StubUser()
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


def _chats_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> TestClient:
    """Build FastAPI TestClient with chats router (GET /chats/{sid}) wired to real repo."""
    app = FastAPI()
    app.include_router(chats_router)
    repo = ChatSessionRepo(session_factory)
    app.dependency_overrides[get_chats_repo] = lambda: repo
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Case A — Cancel vs Complete: 终态对比
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_a_cancel_vs_complete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Case A: 同 session 两个 task,一个 cancel partial,一个 complete done。

    验证:
    - cancel 终态: chat_tasks.status='partial', chat_messages.assistant.status='partial'
    - complete 终态: chat_tasks.status='done', chat_messages.assistant.status='done'
    - partial content 比 done content 短(模拟 cancel 在生成中途截断)
    """
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    task_repo = ChatTaskRepo(session_factory)
    msg_repo = ChatSessionRepo(session_factory)

    # --- Cancel path: task_a 走 partial ---
    task_a = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task_a.id)
    await task_repo.mark_partial(task_a.id, langgraph_checkpoint_id="ckpt-a")
    await msg_repo.append_message(
        session_id=str(sid),
        role="user",
        content="prompt 1",
    )
    await msg_repo.append_message(
        session_id=str(sid),
        role="assistant",
        content="partial answer 50 chars",
        task_id=task_a.id,
        status="partial",
    )

    # --- Complete path: task_b 走 done ---
    task_b = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task_b.id)
    await task_repo.mark_done(task_b.id, langgraph_checkpoint_id="ckpt-b")
    await msg_repo.append_message(
        session_id=str(sid),
        role="user",
        content="prompt 2",
    )
    await msg_repo.append_message(
        session_id=str(sid),
        role="assistant",
        content="this is a much longer full answer that has more than 50 chars total",
        task_id=task_b.id,
        status="done",
    )

    # === Assertions: 终态对比 ===
    refreshed_a = await task_repo.get_by_id(task_a.id)
    refreshed_b = await task_repo.get_by_id(task_b.id)
    assert refreshed_a is not None and refreshed_a.status == "partial"
    assert refreshed_b is not None and refreshed_b.status == "done"

    msgs = await msg_repo.list_messages(str(sid))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 2, (
        f"expected 2 assistant messages, got {len(assistant_msgs)}: "
        f"{[(m.status, m.content[:30]) for m in assistant_msgs]}"
    )
    partial_msg = next(m for m in assistant_msgs if m.status == "partial")
    done_msg = next(m for m in assistant_msgs if m.status == "done")
    # cancel content 应该比 done content 短(partial 是 prefix 模拟)
    assert len(partial_msg.content) < len(done_msg.content), (
        f"expected partial.content shorter than done.content, "
        f"got partial={len(partial_msg.content)} done={len(done_msg.content)}"
    )
    # task linkage 正确
    assert partial_msg.task_id == task_a.id
    assert done_msg.task_id == task_b.id


# ---------------------------------------------------------------------------
# Case B — Retry 整 turn 重跑(checkpoint 退役): parent_task_id 链 + 原 turn 消息
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_b_retry_whole_turn_rerun(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case B(Phase 4 Task 4.3):task1 mark_error → POST /retry → task2 parent=task1
    + enqueue 整 turn 重跑(resume_checkpoint_id=None,user_message=原 turn 消息)。

    验证(turn 原子语义,checkpoint 退役):
    - retry endpoint 返回新 task_id + parent_task_id=task1.id,**不再有 resumed_from_checkpoint**
    - enqueue_run_chat 被调用一次,kwargs.resume_checkpoint_id=None,user_message 含原消息
    - chat_tasks 中 task2.parent_task_id == task1.id
    """
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)

        class _R:
            def __init__(self, tid: str) -> None:
                self.id = tid

        return _R(kwargs["task_id"])

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    # 原始 user 消息(POST /chat 形状:task 尚不存在,经 initial_prompt 关联)
    msg_repo = ChatSessionRepo(session_factory)
    user_msg = await msg_repo.append_message(session_id=str(sid), role="user", content="原始问题")

    task_repo = ChatTaskRepo(session_factory)
    task1 = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=user_msg.id,
    )
    await task_repo.mark_running(task1.id)
    await task_repo.mark_error(task1.id, error_message="simulated crash")

    client = _chat_client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{task1.id}")
    assert resp.status_code == 200, f"expected 200 got {resp.status_code}: {resp.text}"
    body = resp.json()
    task2_id = uuid.UUID(body["task_id"])
    assert task2_id != task1.id
    assert body["parent_task_id"] == str(task1.id)
    assert "resumed_from_checkpoint" not in body  # checkpoint 退役

    # task2 row + parent 链
    task2 = await task_repo.get_by_id(task2_id)
    assert task2 is not None
    assert task2.parent_task_id == task1.id

    # enqueue 整 turn 重跑:checkpoint=None,user_message=原 turn 消息
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] is None
    assert enqueued[0]["task_id"] == str(task2_id)
    assert "原始问题" in enqueued[0]["user_message"]


# ---------------------------------------------------------------------------
# Case C — Two-turn with second in-flight: active_task_id 路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_c_two_turn_with_second_in_flight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Case C: 两轮 prompt,task1 done,task2 running → GET /chats/{sid} 返
    messages + active_task_id=task2.id。

    验证:
    - task1 完成后无 active_task,task2 mark_running 后 active_task_id=task2.id
    - messages 含 3 条(user1 / assistant1 / user2);task1 message status=done
    - chat_tasks: task1 done / task2 running
    """
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    task_repo = ChatTaskRepo(session_factory)
    msg_repo = ChatSessionRepo(session_factory)

    # --- Turn 1: 完成 ---
    task1 = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task1.id)
    await task_repo.mark_done(task1.id, langgraph_checkpoint_id="ckpt-1")
    await msg_repo.append_message(
        session_id=str(sid),
        role="user",
        content="first prompt",
    )
    await msg_repo.append_message(
        session_id=str(sid),
        role="assistant",
        content="first answer",
        task_id=task1.id,
        status="done",
    )

    # --- Turn 2: in-flight(只 mark_running,不 finalize)---
    task2 = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task2.id)
    await msg_repo.append_message(
        session_id=str(sid),
        role="user",
        content="second prompt",
    )

    # === GET /chats/{sid} ===
    client = _chats_client(session_factory)
    resp = client.get(f"/api/v0/chats/{sid}")
    assert resp.status_code == 200, f"expected 200 got {resp.status_code}: {resp.text}"
    body = resp.json()

    # active_task_id 应该是 task2.id(task1 done,task2 running)
    assert body["active_task_id"] == str(task2.id), (
        f"expected active_task_id={task2.id}, got {body.get('active_task_id')}"
    )

    # messages 含 3 条(user1 / assistant1 / user2)
    messages = body["messages"]
    assert len(messages) == 3, (
        f"expected 3 messages, got {len(messages)}: "
        f"{[(m['role'], m.get('status')) for m in messages]}"
    )
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user"]
    # assistant1 status=done + task_id 链接 task1
    assert messages[1]["status"] == "done"
    assert messages[1]["task_id"] == str(task1.id)

    # === chat_tasks 终态: task1 done / task2 running ===
    refreshed_task1 = await task_repo.get_by_id(task1.id)
    refreshed_task2 = await task_repo.get_by_id(task2.id)
    assert refreshed_task1 is not None and refreshed_task1.status == "done"
    assert refreshed_task2 is not None and refreshed_task2.status == "running"
