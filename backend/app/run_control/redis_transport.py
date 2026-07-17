"""Versioned Redis Stream envelopes for run-control notifications."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from uuid import UUID

from app.run_control.types import OutboxType
from app.services.run_outbox import OutboxItem


class InvalidRedisEnvelopeError(ValueError):
    """Raised when a Stream entry cannot be treated as a run notification."""


@dataclass(frozen=True)
class AckDeleteResult:
    acknowledged: int
    deleted: int


@dataclass(frozen=True)
class RecoveredMessage:
    entry_id: str
    item: OutboxItem


@dataclass(frozen=True)
class PendingRecovery:
    next_start_id: str
    messages: tuple[RecoveredMessage, ...]
    deleted_ids: tuple[str, ...]
    invalid_ids: tuple[str, ...]


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


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


def parse_stream_envelope(fields: Mapping[Any, Any]) -> OutboxItem:
    raw_data = fields.get(b"data") if b"data" in fields else fields.get("data")
    if not isinstance(raw_data, bytes | str):
        raise InvalidRedisEnvelopeError("Redis envelope is missing data")
    try:
        value = json.loads(_text(raw_data))
        if not isinstance(value, dict) or value.get("v") != 1:
            raise ValueError
        payload = value["payload"]
        delivery_attempts = value["delivery_attempts"]
        if not isinstance(payload, dict):
            raise ValueError
        if isinstance(delivery_attempts, bool) or not isinstance(delivery_attempts, int):
            raise ValueError
        item = OutboxItem(
            id=UUID(value["outbox_id"]),
            event_type=OutboxType(value["event_type"]),
            tenant_id=UUID(value["tenant_id"]),
            run_id=UUID(value["run_id"]),
            attempt_id=UUID(value["attempt_id"]) if value["attempt_id"] is not None else None,
            worker_id=UUID(value["worker_id"]) if value["worker_id"] is not None else None,
            payload=_freeze_json(payload),
            delivery_attempts=delivery_attempts,
        )
        stream_key(item)
        return item
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidRedisEnvelopeError("Redis envelope is invalid") from exc


class RedisTransport:
    """Bounded acceleration channel; PostgreSQL Outbox remains the source of truth.

    Exact trimming cannot permanently lose an unacknowledged Assignment/Cancel
    because its durable Outbox row remains eligible for redelivery. ScheduleWake
    may expire or trim because the Scheduler retains PostgreSQL polling fallback.
    MAXLEN is per Stream key; TTL is a global idle boundary for the key, consumer
    groups, and PEL. Active Outbox redelivery refreshes it on every XADD.
    """

    DEFAULT_MAX_STREAM_LENGTH = 10_000
    DEFAULT_STREAM_TTL_SECONDS = 86_400

    def __init__(
        self,
        redis: Any,
        *,
        max_stream_length: int = DEFAULT_MAX_STREAM_LENGTH,
        stream_ttl_seconds: int = DEFAULT_STREAM_TTL_SECONDS,
    ) -> None:
        if max_stream_length <= 0:
            raise ValueError("max_stream_length must be positive")
        if stream_ttl_seconds <= 0:
            raise ValueError("stream_ttl_seconds must be positive")
        self._redis = redis
        self._max_stream_length = max_stream_length
        self._stream_ttl_seconds = stream_ttl_seconds

    async def publish(self, item: OutboxItem) -> str:
        key = stream_key(item)
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.xadd(
                key,
                {"data": serialize_envelope(item)},
                maxlen=self._max_stream_length,
                approximate=False,
            )
            pipeline.expire(key, self._stream_ttl_seconds)
            results = await pipeline.execute()
        entry_id = results[0]
        if isinstance(entry_id, bytes):
            return entry_id.decode("ascii")
        return str(entry_id)

    async def acknowledge_and_delete(
        self,
        key: str,
        group: str,
        entry_id: str,
    ) -> AckDeleteResult:
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.xack(key, group, entry_id)
            pipeline.xdel(key, entry_id)
            acknowledged, deleted = await pipeline.execute()
        return AckDeleteResult(acknowledged=int(acknowledged), deleted=int(deleted))

    async def recover_pending(
        self,
        key: str,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int,
        count: int = 100,
        start_id: str = "0-0",
    ) -> PendingRecovery:
        if min_idle_ms < 0:
            raise ValueError("min_idle_ms must be nonnegative")
        if count <= 0:
            raise ValueError("count must be positive")
        response = await self._redis.xautoclaim(
            key,
            group,
            consumer,
            min_idle_ms,
            start_id=start_id,
            count=count,
        )
        next_start_id = _text(response[0])
        entries = response[1]
        deleted_ids = tuple(_text(entry_id) for entry_id in response[2])
        messages: list[RecoveredMessage] = []
        invalid_ids: list[str] = []
        for raw_id, fields in entries:
            entry_id = _text(raw_id)
            try:
                item = parse_stream_envelope(fields)
            except InvalidRedisEnvelopeError:
                invalid_ids.append(entry_id)
                continue
            messages.append(RecoveredMessage(entry_id=entry_id, item=item))
        if invalid_ids:
            async with self._redis.pipeline(transaction=True) as pipeline:
                for entry_id in invalid_ids:
                    pipeline.xack(key, group, entry_id)
                    pipeline.xdel(key, entry_id)
                await pipeline.execute()
        return PendingRecovery(
            next_start_id=next_start_id,
            messages=tuple(messages),
            deleted_ids=deleted_ids,
            invalid_ids=tuple(invalid_ids),
        )

    async def delete_stream(self, key: str) -> int:
        """Delete exactly one terminal Worker/Attempt Stream key and its group/PEL."""

        return int(await self._redis.delete(key))
