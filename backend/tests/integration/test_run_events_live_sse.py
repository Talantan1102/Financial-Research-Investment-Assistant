from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from app.chatloop.run_executor import RunEvent as TemporaryRunEvent
from app.router.auth_router import get_current_user_required
from app.router.runs import get_run_service, get_run_stream_bus, router
from app.services.run_stream_bus import RunStreamBus, run_stream_key
from fastapi import FastAPI
from redis.asyncio import Redis


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    redis = Redis.from_url(
        "redis://127.0.0.1:6379/0",
        decode_responses=False,
        socket_connect_timeout=0.5,
    )
    try:
        try:
            await redis.ping()
        except Exception as exc:  # noqa: BLE001 - environment capability probe
            pytest.skip(f"true Redis unavailable: {type(exc).__name__}")
        yield redis
    finally:
        await redis.aclose()


def _durable(seq: int, event_type: str, payload: dict[str, object]) -> object:
    return SimpleNamespace(seq=seq, event_type=event_type, payload=payload)


class ScriptedRunService:
    def __init__(self, *, terminal_from_start: bool = False) -> None:
        self.created = _durable(1, "run.created", {"status": "queued"})
        self.running = _durable(2, "run.running", {"status": "running"})
        self.final = _durable(3, "run.completed", {"final_message_id": "message-1"})
        self.terminal_from_start = terminal_from_start
        self.list_reads = 0
        self.run_reads = 0

    async def list_events(
        self,
        _tenant_id: uuid.UUID,
        _run_id: uuid.UUID,
        _actor_id: uuid.UUID,
        *,
        after_seq: int = 0,
    ) -> tuple[object, ...]:
        self.list_reads += 1
        terminal = self.terminal_from_start or self.list_reads > 3
        if terminal:
            events = (self.created, self.running, self.final)
        elif self.list_reads > 1:
            events = (self.created, self.running)
        else:
            events = (self.created,)
        return tuple(event for event in events if event.seq > after_seq)

    async def get_run(
        self,
        _tenant_id: uuid.UUID,
        _run_id: uuid.UUID,
        _actor_id: uuid.UUID,
    ) -> object:
        self.run_reads += 1
        terminal = self.terminal_from_start or self.run_reads > 3
        return SimpleNamespace(status="completed" if terminal else "running")

    async def get_final_message(
        self,
        _tenant_id: uuid.UUID,
        _run_id: uuid.UUID,
        _actor_id: uuid.UUID,
    ) -> object:
        return SimpleNamespace(content="durable final")


@asynccontextmanager
async def _client(
    *,
    service: ScriptedRunService,
    bus: RunStreamBus,
    actor_id: uuid.UUID,
) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_required] = lambda: SimpleNamespace(id=actor_id)
    app.dependency_overrides[get_run_service] = lambda: service
    app.dependency_overrides[get_run_stream_bus] = lambda: bus
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


def _frames(body: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for raw in body.strip().split("\n\n") if body.strip() else []:
        fields = dict(line.split(": ", 1) for line in raw.splitlines())
        frames.append(
            {"id": fields["id"], "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return frames


async def test_live_sse_orders_durable_before_token_then_final_durable(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.router.runs._RUN_STREAM_BLOCK_MS", 1)
    tenant_id, run_id, attempt_id, actor_id = (uuid.uuid4() for _ in range(4))
    bus = RunStreamBus(redis_client)
    token_id = await bus.publish(
        TemporaryRunEvent(
            run_id=run_id,
            attempt_id=attempt_id,
            kind="token",
            seq=1,
            step=1,
            payload={"text": "live"},
        ),
        durable_seq=0,
    )
    assert token_id is not None
    service = ScriptedRunService()

    async with _client(service=service, bus=bus, actor_id=actor_id) as client:
        response = await client.get(f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events")

    frames = _frames(response.text)
    assert [(frame["event"], frame["data"]) for frame in frames] == [
        ("run.created", {"status": "queued"}),
        ("run.running", {"status": "running"}),
        ("token", {"text": "live"}),
        ("run.completed", {"final_message_id": "message-1", "content": "durable final"}),
    ]
    assert [frame["id"] for frame in frames] == [
        "v1:1:0-0",
        "v1:2:0-0",
        f"v1:2:{token_id}",
        f"v1:3:{token_id}",
    ]
    assert service.list_reads >= 4
    assert service.run_reads >= 4
    await redis_client.delete(run_stream_key(run_id))


async def test_composite_reconnect_does_not_repeat_token_and_uses_durable_final(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.router.runs._RUN_STREAM_BLOCK_MS", 1)
    tenant_id, run_id, attempt_id, actor_id = (uuid.uuid4() for _ in range(4))
    bus = RunStreamBus(redis_client)
    token_id = await bus.publish(
        TemporaryRunEvent(
            run_id=run_id,
            attempt_id=attempt_id,
            kind="token",
            seq=1,
            step=1,
            payload={"text": "old token"},
        ),
        durable_seq=0,
    )
    assert token_id is not None
    service = ScriptedRunService(terminal_from_start=True)

    async with _client(service=service, bus=bus, actor_id=actor_id) as client:
        response = await client.get(
            f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events",
            headers={"Last-Event-ID": f"v1:2:{token_id}"},
        )

    assert _frames(response.text) == [
        {
            "id": f"v1:3:{token_id}",
            "event": "run.completed",
            "data": {"final_message_id": "message-1", "content": "durable final"},
        }
    ]
    await redis_client.delete(run_stream_key(run_id))


async def test_redis_read_failure_backs_off_and_still_delivers_durable_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenBus:
        async def read(self, *_args: object, **_kwargs: object) -> tuple[object, ...]:
            raise ConnectionError("redis unavailable")

    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.router.runs._RUN_STREAM_BLOCK_MS", 1)
    monkeypatch.setattr("app.router.runs.asyncio.sleep", record_sleep)
    tenant_id, run_id, actor_id = (uuid.uuid4() for _ in range(3))
    service = ScriptedRunService()

    async with _client(
        service=service,
        bus=BrokenBus(),  # type: ignore[arg-type]
        actor_id=actor_id,
    ) as client:
        response = await client.get(f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events")

    assert [frame["event"] for frame in _frames(response.text)] == [
        "run.created",
        "run.running",
        "run.completed",
    ]
    assert sleeps
    assert set(sleeps) == {0.001}


@pytest.mark.parametrize(
    "cursor",
    ["v1:1:$", "v2:1:1-0", "v1:-1:1-0", "v1:1:bad"],
)
async def test_live_sse_rejects_malformed_composite_cursor(
    cursor: str,
    redis_client: Redis,
) -> None:
    tenant_id, run_id, actor_id = (uuid.uuid4() for _ in range(3))
    bus = RunStreamBus(redis_client)
    service = ScriptedRunService(terminal_from_start=True)

    async with _client(service=service, bus=bus, actor_id=actor_id) as client:
        response = await client.get(
            f"/api/v1/tenants/{tenant_id}/runs/{run_id}/events",
            headers={"Last-Event-ID": cursor},
        )

    assert response.status_code == 422


async def test_true_redis_round_trip_is_bounded_and_expiring(redis_client: Redis) -> None:
    run_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    bus = RunStreamBus(redis_client, max_stream_length=2, stream_ttl_seconds=60)
    for seq in range(3):
        await bus.publish(
            TemporaryRunEvent(
                run_id=run_id,
                attempt_id=attempt_id,
                kind="token",
                seq=seq,
                step=1,
                payload={"text": str(seq)},
            )
        )

    assert await redis_client.xlen(run_stream_key(run_id)) == 2
    assert 0 < await redis_client.ttl(run_stream_key(run_id)) <= 60
    assert [
        entry.envelope.payload for entry in await bus.read(run_id, after_id="0-0", block_ms=1)
    ] == [
        {"text": "1"},
        {"text": "2"},
    ]
    await redis_client.delete(run_stream_key(run_id))
