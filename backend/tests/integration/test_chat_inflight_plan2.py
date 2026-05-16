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
