# mypy: disable-error-code="arg-type"
# SQLAlchemy classical Column[UUID] mypy 推断不准 — 测试代码 silence(参见
# test_chat_runner.py / test_chat_task_repo.py 同 pattern)。
"""Plan 2 集成测试 — GET /api/v0/chat/stream/{task_id} SSE replay。

测试策略:in-memory sqlite + fakeredis;不真起 Celery worker。
预 populate Redis Stream(模拟 worker XADD 的输出),然后用 TestClient 拉 SSE。

覆盖三档 HTTP 语义:
- 200 + 全量 replay(last_event_id=0)
- 200 + 只 replay last_event_id 之后的 entry
- 404 task_id 不存在
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401 — registers users table
from app.router.chat import (
    get_async_session_factory,
    get_chat_graph,
    get_current_user,
    get_escalation_extractor,
    get_escalation_record_repo,
    get_redis_async,
)
from app.router.chat import (
    router as chat_router,
)
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_REQUIRED_TABLE_NAMES = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn: object) -> None:
    tables = [Base.metadata.tables[name] for name in _REQUIRED_TABLE_NAMES]
    Base.metadata.create_all(sync_conn, tables=tables)


class _StubUser:
    def __init__(self) -> None:
        self.id = "test-user"


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


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


def _client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis_obj: FakeRedis,
) -> TestClient:
    """Build FastAPI TestClient with chat router + DI overrides."""
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_chat_graph] = lambda: MagicMock()
    app.dependency_overrides[get_current_user] = lambda: _StubUser()
    app.dependency_overrides[get_escalation_extractor] = lambda: None
    app.dependency_overrides[get_escalation_record_repo] = lambda: None
    app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    app.dependency_overrides[get_redis_async] = lambda: fake_redis_obj
    return TestClient(app, raise_server_exceptions=True)


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """Extract decoded JSON payloads from SSE `data:` lines."""
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: ") :]))
    return events


@pytest.mark.asyncio
async def test_stream_endpoint_replays_existing_events_from_zero(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    seeded_running_task: dict[str, Any],
) -> None:
    """Worker 已推若干 event → GET /stream/{tid}?last_event_id=0 全 replay。"""
    sid = seeded_running_task["session_id"]
    tid = seeded_running_task["task_id"]

    bus = ChatEventBus(fake_redis)
    await bus.xadd_event(sid, tid, {"type": "token", "text": "hello"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": " world"})
    await bus.xadd_event(sid, tid, {"type": "done"})

    client = _client(session_factory, fake_redis)
    resp = client.get(f"/api/v0/chat/stream/{tid}?last_event_id=0")
    assert resp.status_code == 200, f"expected 200 got {resp.status_code}: {resp.text}"
    body = resp.content.decode("utf-8")
    events = _parse_sse_events(body)
    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 2, f"expected 2 tokens, got {len(token_events)}: {events}"
    assert token_events[0]["text"] == "hello"
    assert token_events[1]["text"] == " world"
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1, f"expected 1 done event, got {len(done_events)}: {events}"
    # Verify SSE frame format includes event: line + id: line
    assert "event: token" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_stream_endpoint_with_last_event_id_returns_only_new(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    seeded_running_task: dict[str, Any],
) -> None:
    """传 last_event_id=<first entry id>,应该只返回之后的事件。"""
    sid = seeded_running_task["session_id"]
    tid = seeded_running_task["task_id"]

    bus = ChatEventBus(fake_redis)
    first_id = await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    await bus.xadd_event(sid, tid, {"type": "done"})

    client = _client(session_factory, fake_redis)
    resp = client.get(f"/api/v0/chat/stream/{tid}?last_event_id={first_id}")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    events = _parse_sse_events(body)

    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 1, (
        f"expected only 1 token (after first_id), got {len(token_events)}: {events}"
    )
    assert token_events[0]["text"] == "b"

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_stream_endpoint_404_for_unknown_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Unknown task_id → 404。"""
    fake_tid = uuid.uuid4()
    client = _client(session_factory, fake_redis)
    resp = client.get(f"/api/v0/chat/stream/{fake_tid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_chat_with_redis_enqueues_and_returns_task_id(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan 2 Task 5: POST /chat (Redis wired) → JSON {task_id, stream_url, session_id}.

    - Response 必须是 JSON,不是 SSE
    - Celery enqueue_run_chat 被调用一次,kwargs 正确
    - User message 持久化到 PG (Plan 1 entry semantics 保留)
    - ChatTask 行已创建 (status queued or running)
    """
    enqueued: list[dict[str, Any]] = []

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)

        class _Result:
            def __init__(self, tid: str) -> None:
                self.id = tid

        return _Result(kwargs["task_id"])

    # Patch chat_runner.enqueue_run_chat (production entry from POST handler)
    from app.tasks import chat_runner

    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    # Seed session
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    client = _client(session_factory, fake_redis)
    resp = client.post(
        "/api/v0/chat",
        json={"session_id": str(sid), "message": "查 600519 股价"},
    )
    assert resp.status_code == 200, f"expected 200 got {resp.status_code}: {resp.text}"
    # Content-Type 应该是 application/json,不是 text/event-stream
    assert "application/json" in resp.headers.get("content-type", ""), (
        f"expected JSON content-type, got {resp.headers.get('content-type')}"
    )

    body = resp.json()
    assert "task_id" in body
    assert "stream_url" in body
    assert body["session_id"] == str(sid)
    assert body["task_id"] in body["stream_url"]
    assert body["stream_url"].endswith(body["task_id"])  # path format /chat/stream/{tid}

    # enqueue called once with right kwargs
    assert len(enqueued) == 1, f"expected 1 enqueue, got {len(enqueued)}"
    assert enqueued[0]["session_id"] == str(sid)
    assert enqueued[0]["user_message"] == "查 600519 股价"
    assert "task_id" in enqueued[0]
    assert "user_id" in enqueued[0]

    # PG: user message should be persisted (Plan 1 entry semantics preserved)
    from app.services.chat_session_repo import ChatSessionRepo

    msg_repo = ChatSessionRepo(session_factory)
    msgs = await msg_repo.list_messages(str(sid))
    assert len(msgs) == 1, f"expected 1 user message, got {len(msgs)}"
    assert msgs[0].role == "user"
    assert msgs[0].content == "查 600519 股价"

    # PG: chat_task created with status queued or running (POST handler may or
    # may not mark_running before enqueue — Plan 2 lets Celery worker mark; we
    # accept either here).
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.get_by_id(uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.status in ("queued", "running"), f"expected queued or running, got {task.status}"


# ---------------------------------------------------------------------------
# Plan 3 Task 4: POST /api/v0/chat/cancel/{task_id} — publish to Redis pub/sub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_chat_cancel_publishes_to_pubsub(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
    seeded_running_task: dict[str, Any],
) -> None:
    """POST /api/v0/chat/cancel/{tid} → ChatCancelBus.publish_cancel,Redis pub/sub
    应该有 1 个 receiver(test 内 subscribe)。"""
    import asyncio

    from app.services.chat_cancel_bus import ChatCancelBus

    tid = seeded_running_task["task_id"]
    received: list[bytes] = []
    flag = asyncio.Event()

    async def subscriber() -> None:
        cancel_bus = ChatCancelBus(fake_redis)
        async for data in cancel_bus.subscribe_cancel(tid):
            received.append(data)
            flag.set()
            return

    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.05)

    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/cancel/{tid}")
    assert resp.status_code == 202, f"expected 202 got {resp.status_code}: {resp.text}"

    await asyncio.wait_for(flag.wait(), timeout=2.0)
    await sub_task
    assert len(received) == 1


@pytest.mark.asyncio
async def test_post_chat_cancel_404_for_unknown_task(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """Unknown task_id → 404。"""
    fake_tid = uuid.uuid4()
    client = _client(session_factory, fake_redis)
    resp = client.post(f"/api/v0/chat/cancel/{fake_tid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_chat_cancel_invalid_uuid_404(
    session_factory: async_sessionmaker[AsyncSession],
    fake_redis: FakeRedis,
) -> None:
    """非 UUID 格式 task_id → 404。"""
    client = _client(session_factory, fake_redis)
    resp = client.post("/api/v0/chat/cancel/not-a-uuid")
    assert resp.status_code == 404
