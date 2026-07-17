"""Versioned Redis Stream envelopes for run-control notifications."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.run_control.types import OutboxType
from app.services.run_outbox import OutboxItem


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def stream_key(item: OutboxItem) -> str:
    if not all(isinstance(value, UUID) for value in (item.id, item.tenant_id, item.run_id)):
        raise ValueError("envelope requires outbox/tenant/run UUID provenance")
    if not isinstance(item.event_type, OutboxType) or item.delivery_attempts < 1:
        raise ValueError("envelope requires valid event/delivery provenance")
    if item.event_type is OutboxType.ATTEMPT_ASSIGNED:
        if not isinstance(item.attempt_id, UUID) or not isinstance(item.worker_id, UUID):
            raise ValueError("assignment envelope requires attempt/worker provenance")
        return f"run:worker:{item.worker_id}:assignments"
    if item.event_type is OutboxType.ATTEMPT_CANCEL:
        if not isinstance(item.attempt_id, UUID) or not isinstance(item.worker_id, UUID):
            raise ValueError("cancel envelope requires attempt/worker provenance")
        return f"run:attempt:{item.attempt_id}:control"
    if item.event_type is OutboxType.SCHEDULE_WAKE:
        if item.attempt_id is not None or item.worker_id is not None:
            raise ValueError("schedule wake envelope forbids attempt/worker provenance")
        return "run:scheduler:wake"
    raise ValueError(f"unsupported Outbox event type: {item.event_type}")


def serialize_envelope(item: OutboxItem) -> str:
    stream_key(item)
    envelope = {
        "v": 1,
        "outbox_id": str(item.id),
        "event_type": item.event_type.value,
        "tenant_id": str(item.tenant_id),
        "run_id": str(item.run_id),
        "attempt_id": str(item.attempt_id) if item.attempt_id is not None else None,
        "worker_id": str(item.worker_id) if item.worker_id is not None else None,
        "payload": _json_value(item.payload),
        "delivery_attempts": item.delivery_attempts,
    }
    try:
        return json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Redis envelope payload must be JSON serializable") from exc


class RedisTransport:
    """Bounded acceleration channel; PostgreSQL Outbox remains the source of truth.

    Exact trimming cannot permanently lose an unacknowledged notification because
    its durable Outbox row remains eligible for redelivery.
    """

    DEFAULT_MAX_STREAM_LENGTH = 10_000

    def __init__(
        self,
        redis: Any,
        *,
        max_stream_length: int = DEFAULT_MAX_STREAM_LENGTH,
    ) -> None:
        if max_stream_length <= 0:
            raise ValueError("max_stream_length must be positive")
        self._redis = redis
        self._max_stream_length = max_stream_length

    async def publish(self, item: OutboxItem) -> str:
        entry_id = await self._redis.xadd(
            stream_key(item),
            {"data": serialize_envelope(item)},
            maxlen=self._max_stream_length,
            approximate=False,
        )
        if isinstance(entry_id, bytes):
            return entry_id.decode("ascii")
        return str(entry_id)
