"""Best-effort Redis stream for temporary Run UI events."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.chatloop.run_executor import RunEvent

logger = logging.getLogger(__name__)

RUN_STREAM_VERSION = "v1"
RUN_STREAM_KINDS = frozenset(
    {
        "step_start",
        "token",
        "tool_call",
        "tool_start",
        "tool_end",
        "tool_error",
        "chart",
        "skill_load",
        "loop_halt",
        "approval_request",
        "escalate_request",
        "cost_update",
        "done",
        "error",
        "dispatch_start",
        "dispatch_end",
        "context_pressure",
    }
)
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "credential",
        "password",
        "secret",
        "reasoning",
        "reasoning_content",
        "hidden_reasoning",
        "chain_of_thought",
    }
)


def run_stream_key(run_id: UUID) -> str:
    return f"run:stream:{run_id}"


@dataclass(frozen=True)
class RunStreamEnvelope:
    version: str
    run_id: UUID
    attempt_id: UUID
    kind: str
    payload: dict[str, Any]
    durable_seq: int
    event_seq: int
    step: int


@dataclass(frozen=True)
class RunStreamEntry:
    entry_id: str
    envelope: RunStreamEnvelope


def _safe_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("Run stream payload keys must be strings")
            if raw_key.casefold() in _SENSITIVE_KEYS:
                raise ValueError("Run stream payload contains credentials")
            out[raw_key] = _safe_json(item)
        return out
    if isinstance(value, (tuple, list)):
        return [_safe_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Run stream payload must be JSON-compatible")


class RunStreamBus:
    DEFAULT_MAX_STREAM_LENGTH = 2_000
    DEFAULT_STREAM_TTL_SECONDS = 86_400
    DEFAULT_MAX_ENVELOPE_BYTES = 16 * 1024

    def __init__(
        self,
        redis: Any,
        *,
        max_stream_length: int = DEFAULT_MAX_STREAM_LENGTH,
        stream_ttl_seconds: int = DEFAULT_STREAM_TTL_SECONDS,
        max_envelope_bytes: int = DEFAULT_MAX_ENVELOPE_BYTES,
    ) -> None:
        if min(max_stream_length, stream_ttl_seconds, max_envelope_bytes) <= 0:
            raise ValueError("Run stream bounds must be positive")
        self._redis = redis
        self._max_stream_length = max_stream_length
        self._stream_ttl_seconds = stream_ttl_seconds
        self._max_envelope_bytes = max_envelope_bytes

    async def publish(self, event: RunEvent, *, durable_seq: int = 0) -> str | None:
        if event.kind not in RUN_STREAM_KINDS:
            raise ValueError(f"Run stream event kind is not allowed: {event.kind}")
        if durable_seq < 0:
            raise ValueError("durable_seq must be non-negative")
        payload = _safe_json(event.payload)
        envelope = {
            "version": RUN_STREAM_VERSION,
            "run_id": str(event.run_id),
            "attempt_id": str(event.attempt_id),
            "kind": event.kind,
            "payload": payload,
            "durable_seq": durable_seq,
            "event_seq": event.seq,
            "step": event.step,
        }
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self._max_envelope_bytes:
            raise ValueError("Run stream envelope exceeds size limit")
        key = run_stream_key(event.run_id)
        try:
            entry_id = await self._redis.xadd(
                key,
                {"data": encoded},
                maxlen=self._max_stream_length,
                approximate=False,
            )
            await self._redis.expire(key, self._stream_ttl_seconds)
        except Exception as exc:  # noqa: BLE001 - Redis is explicitly best-effort
            logger.warning("Run stream publish degraded for %s: %s", event.run_id, exc)
            return None
        return entry_id.decode("ascii") if isinstance(entry_id, bytes) else str(entry_id)

    async def read(
        self,
        run_id: UUID,
        *,
        after_id: str,
        count: int = 100,
        block_ms: int = 1_000,
    ) -> list[RunStreamEntry]:
        key = run_stream_key(run_id)
        kwargs: dict[str, Any] = {"streams": {key: after_id}, "count": count}
        if block_ms > 0:
            kwargs["block"] = block_ms
        response = await self._redis.xread(**kwargs)
        if not response:
            return []
        entries: list[RunStreamEntry] = []
        malformed_ids: list[str] = []
        for raw_id, fields in response[0][1]:
            entry_id = raw_id.decode("ascii") if isinstance(raw_id, bytes) else str(raw_id)
            raw_data = fields.get(b"data", fields.get("data"))
            try:
                if isinstance(raw_data, bytes):
                    if len(raw_data) > self._max_envelope_bytes:
                        raise ValueError("Run stream envelope exceeds size limit")
                    raw_data = raw_data.decode("utf-8")
                elif isinstance(raw_data, str):
                    if len(raw_data.encode("utf-8")) > self._max_envelope_bytes:
                        raise ValueError("Run stream envelope exceeds size limit")
                data = json.loads(raw_data)
                envelope = self._decode_envelope(data)
            except (TypeError, ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
                logger.warning("Skipping malformed Run stream entry %s", entry_id)
                malformed_ids.append(entry_id)
                continue
            if envelope.run_id == run_id:
                entries.append(RunStreamEntry(entry_id, envelope))
            else:
                malformed_ids.append(entry_id)
        if malformed_ids:
            try:
                await self._redis.xdel(key, *malformed_ids)
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                logger.warning(
                    "Run stream malformed-entry cleanup degraded for %s: %s", run_id, exc
                )
        return entries

    @staticmethod
    def _decode_envelope(data: Any) -> RunStreamEnvelope:
        if not isinstance(data, dict) or data.get("version") != RUN_STREAM_VERSION:
            raise ValueError("unsupported Run stream envelope")
        kind = data["kind"]
        if kind not in RUN_STREAM_KINDS:
            raise ValueError("unsupported Run stream kind")
        payload = _safe_json(data["payload"])
        durable_seq = data["durable_seq"]
        event_seq = data["event_seq"]
        step = data["step"]
        if any(type(value) is not int or value < 0 for value in (durable_seq, event_seq, step)):
            raise ValueError("invalid Run stream sequence")
        return RunStreamEnvelope(
            version=RUN_STREAM_VERSION,
            run_id=UUID(data["run_id"]),
            attempt_id=UUID(data["attempt_id"]),
            kind=kind,
            payload=payload,
            durable_seq=durable_seq,
            event_seq=event_seq,
            step=step,
        )


__all__ = [
    "RUN_STREAM_KINDS",
    "RunStreamBus",
    "RunStreamEntry",
    "RunStreamEnvelope",
    "run_stream_key",
]
