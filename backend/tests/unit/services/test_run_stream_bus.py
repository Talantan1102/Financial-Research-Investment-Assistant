from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
from app.chatloop.run_executor import RunEvent
from app.processes.run_worker import build_run_stream_event_sink
from app.schemas.run import RunEventCursor
from app.services.run_stream_bus import RunStreamBus, run_stream_key


def _event(*, kind: str = "token", payload: dict[str, object] | None = None) -> RunEvent:
    return RunEvent(
        run_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        kind=kind,
        seq=7,
        step=2,
        payload=payload or {"text": "hello"},
    )


@pytest.mark.parametrize(
    ("raw", "durable_seq", "redis_id", "encoded"),
    [
        ("v1:5:1721181123000-4", 5, "1721181123000-4", "v1:5:1721181123000-4"),
        ("5", 5, "0-0", "v1:5:0-0"),
        (None, 0, "0-0", "v1:0:0-0"),
    ],
)
def test_cursor_parses_composite_legacy_and_initial_values(
    raw: str | None,
    durable_seq: int,
    redis_id: str,
    encoded: str,
) -> None:
    cursor = RunEventCursor.parse(raw)

    assert cursor.durable_seq == durable_seq
    assert cursor.redis_id == redis_id
    assert cursor.encode() == encoded


@pytest.mark.parametrize(
    "raw",
    ["", "-1", "1.5", "v2:1:1-0", "v1:-1:1-0", "v1:1:$", "v1:1:1", "v1:1:1-0:extra"],
)
def test_cursor_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        RunEventCursor.parse(raw)


async def test_bus_writes_versioned_bounded_envelope_with_maxlen_and_ttl() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    bus = RunStreamBus(redis, max_stream_length=2, stream_ttl_seconds=60)
    event = _event()

    entry_ids = [await bus.publish(event, durable_seq=index) for index in range(3)]

    assert all(entry_ids)
    key = run_stream_key(event.run_id)
    assert key == f"run:stream:{event.run_id}"
    assert await redis.xlen(key) == 2
    assert 0 < await redis.ttl(key) <= 60
    entries = await bus.read(event.run_id, after_id="0-0", block_ms=0)
    assert [entry.envelope.durable_seq for entry in entries] == [1, 2]
    envelope = entries[-1].envelope
    assert envelope.version == "v1"
    assert envelope.run_id == event.run_id
    assert envelope.attempt_id == event.attempt_id
    assert envelope.kind == "token"
    assert envelope.event_seq == 7
    assert envelope.step == 2
    assert envelope.payload == {"text": "hello"}
    await redis.aclose()


@pytest.mark.parametrize(
    "event",
    [
        _event(kind="reasoning", payload={"text": "hidden chain of thought"}),
        _event(payload={"authorization": "Bearer credential"}),
        _event(payload={"nested": {"api_key": "credential"}}),
        _event(payload={"nested": {"apiKey": "credential"}}),
        _event(payload={"reasoning_content": "hidden chain of thought"}),
        _event(payload={"text": "x" * 20_000}),
    ],
)
async def test_bus_rejects_hidden_reasoning_credentials_and_oversized_payload(
    event: RunEvent,
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    bus = RunStreamBus(redis, max_envelope_bytes=1024)

    with pytest.raises(ValueError):
        await bus.publish(event)

    assert await redis.exists(run_stream_key(event.run_id)) == 0
    await redis.aclose()


async def test_bus_publish_degrades_on_redis_failure() -> None:
    class BrokenRedis:
        async def xadd(self, *_args: object, **_kwargs: object) -> str:
            raise ConnectionError("redis unavailable")

    assert await RunStreamBus(BrokenRedis()).publish(_event()) is None


async def test_bus_skips_corrupt_or_future_version_entries() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event()
    key = run_stream_key(event.run_id)
    await redis.xadd(key, {"data": "not-json"})
    await redis.xadd(key, {"data": json.dumps({"version": "v2"})})
    await redis.xadd(key, {"data": b"\xff"})
    bus = RunStreamBus(redis)

    assert await bus.read(event.run_id, after_id="0-0", block_ms=0) == []
    assert await redis.xlen(key) == 0
    await redis.aclose()


async def test_production_worker_event_sink_publishes_to_run_stream() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event()
    sink = build_run_stream_event_sink(redis)

    await sink(event)

    entries = await RunStreamBus(redis).read(event.run_id, after_id="0-0", block_ms=0)
    assert [entry.envelope.kind for entry in entries] == ["token"]
    await redis.aclose()
