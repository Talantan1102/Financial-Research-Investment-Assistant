# mypy: disable-error-code="arg-type"
"""L1 集成测试 — POST /chat/retry/{tid}。

Phase 4 Task 4.3 改造(spec § 4.3,checkpoint 退役 → 整 turn 重跑):
- task 是失败态 → retry 创建新 task(parent_task_id=旧 tid)+ enqueue 整 turn 重跑
  (resume_checkpoint_id=None,user_message=原消息+插话),前端拿到新 task_id + stream_url
- **删除"无 checkpoint → 422"守卫**:整 turn 重跑无需 checkpoint(原 422 用例改为断言
  现在 200,见 test_steer_and_retry.py 的差分 golden)
- task status != error/partial/cancelled → 409(只有失败 task 能 retry)
- 404 for unknown task_id
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


def _client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
) -> TestClient:
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_current_user] = lambda: _StubUser()
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.asyncio
async def test_post_retry_failed_task_enqueues_whole_turn_rerun(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed task → retry 创建新 task(parent 链接旧 tid)+ 整 turn 重跑。

    Phase 4 Task 4.3:checkpoint 退役。enqueue 收到 resume_checkpoint_id=None,
    user_message = 原 turn user 消息(initial_prompt 关联)。
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

    # Seed session + 原始 user 消息 + error task(initial_prompt 关联)
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    from app.services.chat_session_repo import ChatSessionRepo

    repo = ChatSessionRepo(session_factory)
    user_msg = await repo.append_message(session_id=str(sid), role="user", content="原始提问")

    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=user_msg.id,
    )
    await task_repo.mark_running(old_task.id)
    await task_repo.mark_error(old_task.id, error_message="simulated crash")

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "task_id" in body
    new_tid = body["task_id"]
    assert new_tid != str(old_task.id)
    assert body.get("parent_task_id") == str(old_task.id)
    # checkpoint 退役 → 不再返回 resumed_from_checkpoint
    assert "resumed_from_checkpoint" not in body
    assert "stream_url" in body
    assert new_tid in body["stream_url"]

    # enqueue 整 turn 重跑:checkpoint=None,user_message=原消息
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] is None
    assert enqueued[0]["task_id"] == new_tid
    assert "原始提问" in enqueued[0]["user_message"]

    # 新 chat_tasks row 存在,parent_task_id 链接
    new_task = await task_repo.get_by_id(uuid.UUID(new_tid))
    assert new_task is not None
    assert new_task.parent_task_id == old_task.id


@pytest.mark.asyncio
async def test_post_retry_without_checkpoint_no_longer_422(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed task 没 checkpoint_id → 不再 422(整 turn 重跑无需 checkpoint)。

    旧契约:422 cannot resume。新契约(Task 4.3):200 整 turn 重跑。
    """
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", lambda **kw: enqueued.append(kw))

    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_error(old_task.id, error_message="early failure")

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 200, resp.text
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] is None


@pytest.mark.asyncio
async def test_post_retry_running_task_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """status=running 不能 retry(正在跑)。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=sid,
        user_id=None,
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/retry/{task.id}")
    assert resp.status_code == 409


def test_post_retry_404_for_unknown_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Unknown task_id → 404。"""
    client = _client(session_factory, fake_redis)
    fake_tid = uuid.uuid4()
    resp = client.post(f"/api/v0/chat/retry/{fake_tid}")
    assert resp.status_code == 404
