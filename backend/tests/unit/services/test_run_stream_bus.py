from __future__ import annotations

import asyncio
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


def _deep_list(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = [value]
    return value


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
    entries = (await bus.read(event.run_id, after_id="0-0", block_ms=0)).entries
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
        _event(payload={"nested": {"token": "credential"}}),
        _event(payload={"nested": {"refreshToken": "credential"}}),
        _event(payload={"nested": {"client-secret": "credential"}}),
        _event(payload={"nested": {"private_key": "credential"}}),
        _event(payload={"nested": {"x-api-key": "credential"}}),
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


async def test_bus_allows_token_metrics_that_are_not_credentials() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event(payload={"usage": {"token_count": 12, "completion_tokens": 7}})

    assert await RunStreamBus(redis).publish(event) is not None

    await redis.aclose()


@pytest.mark.parametrize(
    "credential_key",
    [
        "auth_token",
        "session_token",
        "id_token",
        "api_secret",
        "secret_key",
        "api_key_id",
        "private_key_id",
    ],
)
async def test_bus_rejects_normalized_credential_family_keys(credential_key: str) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event(payload={"nested": {credential_key: "credential"}})

    with pytest.raises(ValueError, match="credentials"):
        await RunStreamBus(redis).publish(event)

    assert await redis.exists(run_stream_key(event.run_id)) == 0
    await redis.aclose()


async def test_bus_allows_real_token_metrics_and_ordinary_identifier_keys() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event(
        payload={
            "usage": {
                "token_count": 1,
                "completion_tokens": 2,
                "prompt_tokens": 3,
                "input_tokens": 4,
                "output_tokens": 5,
                "cached_tokens": 6,
                "total_tokens": 7,
            },
            "cache_key": "cache-1",
            "semantic_key": "semantic-1",
            "tool_call_id": "call-1",
        }
    )

    assert await RunStreamBus(redis).publish(event) is not None

    await redis.aclose()


@pytest.mark.parametrize("kind", ["input_request", "steer_merged", "cancelled"])
async def test_bus_accepts_every_control_and_loop_event_emitted_by_run_executor(
    kind: str,
) -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    assert await RunStreamBus(redis).publish(_event(kind=kind, payload={"value": "safe"}))

    await redis.aclose()


async def test_bus_publish_degrades_on_redis_failure() -> None:
    class BrokenRedis:
        async def xadd(self, *_args: object, **_kwargs: object) -> str:
            raise ConnectionError("redis unavailable")

    assert await RunStreamBus(BrokenRedis()).publish(_event()) is None


async def test_bus_publish_timeout_opens_short_circuit_for_hanging_redis() -> None:
    class HangingPipeline:
        async def __aenter__(self) -> HangingPipeline:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def xadd(self, *_args: object, **_kwargs: object) -> HangingPipeline:
            return self

        def expire(self, *_args: object, **_kwargs: object) -> HangingPipeline:
            return self

        async def execute(self) -> None:
            await asyncio.Event().wait()

    class HangingRedis:
        def __init__(self) -> None:
            self.pipeline_calls = 0

        def pipeline(self, *, transaction: bool) -> HangingPipeline:
            assert transaction is True
            self.pipeline_calls += 1
            return HangingPipeline()

    redis = HangingRedis()
    bus = RunStreamBus(redis, publish_timeout_seconds=0.01, circuit_cooldown_seconds=10)
    started = asyncio.get_running_loop().time()

    assert await bus.publish(_event()) is None
    assert await bus.publish(_event()) is None

    assert asyncio.get_running_loop().time() - started < 0.2
    assert redis.pipeline_calls == 1


async def test_bus_publish_uses_atomic_transaction_for_xadd_and_expire() -> None:
    class RecordingPipeline:
        def __init__(self) -> None:
            self.commands: list[str] = []

        async def __aenter__(self) -> RecordingPipeline:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def xadd(self, *_args: object, **_kwargs: object) -> RecordingPipeline:
            self.commands.append("xadd")
            return self

        def expire(self, *_args: object, **_kwargs: object) -> RecordingPipeline:
            self.commands.append("expire")
            return self

        async def execute(self) -> list[object]:
            return [b"123-0", True]

    class PipelineOnlyRedis:
        def __init__(self) -> None:
            self.pipeline_instance = RecordingPipeline()

        def pipeline(self, *, transaction: bool) -> RecordingPipeline:
            assert transaction is True
            return self.pipeline_instance

    redis = PipelineOnlyRedis()

    assert await RunStreamBus(redis).publish(_event()) == "123-0"
    assert redis.pipeline_instance.commands == ["xadd", "expire"]


@pytest.mark.parametrize("failure_point", ["before_exec", "after_exec"])
async def test_atomic_publish_connection_ambiguity_never_leaves_stream_without_ttl(
    failure_point: str,
) -> None:
    inner = fakeredis.aioredis.FakeRedis(decode_responses=False)

    class AmbiguousPipeline:
        def __init__(self) -> None:
            self.delegate = inner.pipeline(transaction=True)

        async def __aenter__(self) -> AmbiguousPipeline:
            await self.delegate.__aenter__()
            return self

        async def __aexit__(self, *args: object) -> None:
            await self.delegate.__aexit__(*args)

        def xadd(self, *args: object, **kwargs: object) -> AmbiguousPipeline:
            self.delegate.xadd(*args, **kwargs)
            return self

        def expire(self, *args: object, **kwargs: object) -> AmbiguousPipeline:
            self.delegate.expire(*args, **kwargs)
            return self

        async def execute(self) -> None:
            if failure_point == "after_exec":
                await self.delegate.execute()
            raise ConnectionError("ambiguous EXEC response")

    class AmbiguousRedis:
        def pipeline(self, *, transaction: bool) -> AmbiguousPipeline:
            assert transaction is True
            return AmbiguousPipeline()

    event = _event()

    assert await RunStreamBus(AmbiguousRedis(), stream_ttl_seconds=60).publish(event) is None

    key = run_stream_key(event.run_id)
    assert await inner.xlen(key) in {0, 1}
    if await inner.xlen(key):
        assert 0 < await inner.ttl(key) <= 60
    await inner.aclose()


async def test_bus_skips_corrupt_or_future_version_entries() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event()
    key = run_stream_key(event.run_id)
    await redis.xadd(key, {"data": "not-json"})
    await redis.xadd(key, {"data": json.dumps({"version": "v2"})})
    await redis.xadd(key, {"data": b"\xff"})
    bus = RunStreamBus(redis)

    assert (await bus.read(event.run_id, after_id="0-0", block_ms=0)).entries == ()
    assert await redis.xlen(key) == 0
    await redis.aclose()


async def test_read_advances_scanned_cursor_when_poison_delete_fails_then_delivers_later_entry() -> (
    None
):
    inner = fakeredis.aioredis.FakeRedis(decode_responses=False)

    class DeleteFailingRedis:
        async def xread(self, **kwargs: object) -> object:
            return await inner.xread(**kwargs)

        async def xdel(self, *_args: object, **_kwargs: object) -> int:
            raise ConnectionError("delete unavailable")

    event = _event()
    key = run_stream_key(event.run_id)
    poison_id = await inner.xadd(key, {"data": "not-json"})
    bus = RunStreamBus(DeleteFailingRedis())

    poison_batch = await bus.read(event.run_id, after_id="0-0", block_ms=0)

    assert poison_batch.entries == ()
    assert poison_batch.scanned_count == 1
    assert poison_batch.last_seen_id == poison_id.decode("ascii")

    valid_id = await RunStreamBus(inner).publish(event)
    assert valid_id is not None
    valid_batch = await bus.read(
        event.run_id,
        after_id=poison_batch.last_seen_id,
        block_ms=0,
    )
    assert [entry.envelope.kind for entry in valid_batch.entries] == ["token"]
    assert valid_batch.last_seen_id == valid_id
    await inner.aclose()


async def test_decoder_isolates_non_string_uuid_fields_and_delivers_following_valid_entry() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event()
    key = run_stream_key(event.run_id)
    base = {
        "version": "v1",
        "run_id": str(event.run_id),
        "attempt_id": str(event.attempt_id),
        "kind": "token",
        "payload": {"text": "poison"},
        "durable_seq": 0,
        "event_seq": 1,
        "step": 1,
    }
    await redis.xadd(key, {"data": json.dumps({**base, "run_id": 123})})
    await redis.xadd(key, {"data": json.dumps({**base, "attempt_id": ["bad"]})})
    valid_id = await RunStreamBus(redis).publish(event)
    assert valid_id is not None

    batch = await RunStreamBus(redis).read(event.run_id, after_id="0-0", block_ms=0)

    assert [entry.entry_id for entry in batch.entries] == [valid_id]
    assert batch.scanned_count == 3
    assert batch.last_seen_id == valid_id
    await redis.aclose()


async def test_read_isolates_deep_poison_advances_cursor_and_delivers_valid_when_delete_fails() -> (
    None
):
    inner = fakeredis.aioredis.FakeRedis(decode_responses=False)

    class DeleteFailingRedis:
        async def xread(self, **kwargs: object) -> object:
            return await inner.xread(**kwargs)

        async def xdel(self, *_args: object, **_kwargs: object) -> int:
            raise ConnectionError("delete unavailable")

    event = _event()
    envelope = {
        "version": "v1",
        "run_id": str(event.run_id),
        "attempt_id": str(event.attempt_id),
        "kind": "token",
        "payload": "__DEEP_PAYLOAD__",
        "durable_seq": 0,
        "event_seq": 1,
        "step": 1,
    }
    deep_json = "[" * 1_100 + "0" + "]" * 1_100
    encoded = json.dumps(envelope).replace('"__DEEP_PAYLOAD__"', deep_json)
    key = run_stream_key(event.run_id)
    await inner.xadd(key, {"data": encoded})
    valid_id = await RunStreamBus(inner).publish(event)
    assert valid_id is not None

    batch = await RunStreamBus(DeleteFailingRedis()).read(
        event.run_id,
        after_id="0-0",
        block_ms=0,
    )

    assert [entry.entry_id for entry in batch.entries] == [valid_id]
    assert batch.scanned_count == 2
    assert batch.last_seen_id == valid_id
    assert await inner.xlen(key) == 2
    await inner.aclose()


async def test_publish_rejects_deep_payload_and_production_sink_fails_open() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event(payload={"nested": _deep_list(1_100)})

    with pytest.raises(ValueError, match="depth"):
        await RunStreamBus(redis).publish(event)
    await build_run_stream_event_sink(redis)(event)

    assert await redis.exists(run_stream_key(event.run_id)) == 0
    await redis.aclose()


async def test_production_worker_event_sink_publishes_to_run_stream() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event()
    sink = build_run_stream_event_sink(redis)

    await sink(event)

    entries = (await RunStreamBus(redis).read(event.run_id, after_id="0-0", block_ms=0)).entries
    assert [entry.envelope.kind for entry in entries] == ["token"]
    await redis.aclose()


async def test_production_worker_event_sink_fails_open_on_rejected_temporary_event() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    event = _event(kind="reasoning", payload={"text": "hidden"})

    await build_run_stream_event_sink(redis)(event)

    assert await redis.exists(run_stream_key(event.run_id)) == 0
    await redis.aclose()
