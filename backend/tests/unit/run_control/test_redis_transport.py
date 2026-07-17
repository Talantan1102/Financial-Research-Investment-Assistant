from __future__ import annotations

import json
import uuid
from typing import cast

import pytest
from app.run_control.redis_transport import RedisTransport, serialize_envelope, stream_key
from app.run_control.types import OutboxType
from app.services.run_outbox import OutboxItem
from fakeredis.aioredis import FakeRedis


def _item(event_type: OutboxType) -> OutboxItem:
    attempt_id = None if event_type is OutboxType.SCHEDULE_WAKE else uuid.uuid4()
    worker_id = None if event_type is OutboxType.SCHEDULE_WAKE else uuid.uuid4()
    return OutboxItem(
        id=uuid.uuid4(),
        event_type=event_type,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        attempt_id=attempt_id,
        worker_id=worker_id,
        payload={"z": 1, "a": ["x", 2]},
        delivery_attempts=3,
    )


@pytest.mark.parametrize(
    ("event_type", "expected_key"),
    [
        (OutboxType.ATTEMPT_ASSIGNED, "run:worker:{worker_id}:assignments"),
        (OutboxType.ATTEMPT_CANCEL, "run:attempt:{attempt_id}:control"),
        (OutboxType.SCHEDULE_WAKE, "run:scheduler:wake"),
    ],
)
async def test_publish_uses_exact_stream_key_and_v1_json(
    event_type: OutboxType,
    expected_key: str,
) -> None:
    redis = FakeRedis(decode_responses=False)
    item = _item(event_type)

    entry_id = await RedisTransport(redis).publish(item)

    key = expected_key.format(worker_id=item.worker_id, attempt_id=item.attempt_id)
    assert entry_id.count("-") == 1
    entries = await redis.xrange(key)
    assert len(entries) == 1
    envelope = json.loads(entries[0][1][b"data"])
    assert envelope == {
        "attempt_id": str(item.attempt_id) if item.attempt_id else None,
        "delivery_attempts": 3,
        "event_type": event_type.value,
        "outbox_id": str(item.id),
        "payload": {"a": ["x", 2], "z": 1},
        "run_id": str(item.run_id),
        "tenant_id": str(item.tenant_id),
        "v": 1,
        "worker_id": str(item.worker_id) if item.worker_id else None,
    }


async def test_stream_retention_is_bounded_and_preserves_consumer_group() -> None:
    redis = FakeRedis(decode_responses=False)
    item = _item(OutboxType.ATTEMPT_ASSIGNED)
    key = stream_key(item)
    await redis.xgroup_create(key, "worker-group", id="0", mkstream=True)
    transport = RedisTransport(redis, max_stream_length=5)

    for _ in range(20):
        await transport.publish(item)

    assert await redis.xlen(key) == 5
    groups = await redis.xinfo_groups(key)
    group_name = groups[0].get(b"name", groups[0].get("name"))
    assert group_name in {b"worker-group", "worker-group"}


def test_serializer_is_deterministic_and_rejects_invalid_provenance() -> None:
    item = _item(OutboxType.ATTEMPT_ASSIGNED)
    assert serialize_envelope(item) == serialize_envelope(item)
    invalid = OutboxItem(
        id=item.id,
        event_type=OutboxType.ATTEMPT_ASSIGNED,
        tenant_id=item.tenant_id,
        run_id=item.run_id,
        attempt_id=item.attempt_id,
        worker_id=None,
        payload={},
        delivery_attempts=1,
    )
    with pytest.raises(ValueError, match="provenance"):
        stream_key(invalid)


def test_schedule_wake_rejects_attempt_provenance_and_non_json_payload() -> None:
    item = _item(OutboxType.SCHEDULE_WAKE)
    with_attempt = OutboxItem(
        id=item.id,
        event_type=item.event_type,
        tenant_id=item.tenant_id,
        run_id=item.run_id,
        attempt_id=uuid.uuid4(),
        worker_id=None,
        payload={},
        delivery_attempts=1,
    )
    with pytest.raises(ValueError, match="provenance"):
        serialize_envelope(with_attempt)
    invalid_json = OutboxItem(
        id=item.id,
        event_type=item.event_type,
        tenant_id=item.tenant_id,
        run_id=item.run_id,
        attempt_id=None,
        worker_id=None,
        payload={"bad": object()},
        delivery_attempts=1,
    )
    with pytest.raises(ValueError, match="JSON"):
        serialize_envelope(invalid_json)


def test_serializer_strictly_requires_uuid_identity_provenance() -> None:
    item = _item(OutboxType.SCHEDULE_WAKE)
    missing_tenant = OutboxItem(
        id=item.id,
        event_type=item.event_type,
        tenant_id=cast(uuid.UUID, None),
        run_id=item.run_id,
        attempt_id=None,
        worker_id=None,
        payload={},
        delivery_attempts=1,
    )
    with pytest.raises(ValueError, match="provenance"):
        serialize_envelope(missing_tenant)
