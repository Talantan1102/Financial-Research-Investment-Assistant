"""Best-effort Redis stream for temporary Run UI events."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args
from uuid import UUID

from app.chatloop.events import EventType
from app.chatloop.run_executor import RunEvent

logger = logging.getLogger(__name__)

RUN_STREAM_VERSION = "v1"
RUN_STREAM_KINDS = (frozenset(get_args(EventType)) | {"input_request", "cancelled"}) - {"reasoning"}
MAX_PAYLOAD_DEPTH = 64
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SAFE_METRIC_KEY_FORMS = frozenset(
    {
        "tokencount",
        "completiontokens",
        "prompttokens",
        "inputtokens",
        "outputtokens",
        "cachedtokens",
        "totaltokens",
        "reasoningtokens",
        "audiotokens",
        "acceptedpredictiontokens",
        "rejectedpredictiontokens",
        "cachereadinputtokens",
        "cachecreationinputtokens",
    }
)
_SENSITIVE_KEY_FORMS = frozenset(
    {
        "authorization",
        "apikey",
        "xapikey",
        "token",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "privatekey",
        "credential",
        "credentials",
        "password",
        "secret",
        "reasoning",
        "reasoningcontent",
        "hiddenreasoning",
        "chainofthought",
    }
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "credentials",
        "password",
        "reasoning",
        "secret",
        "token",
    }
)


def run_stream_key(run_id: UUID) -> str:
    return f"run:stream:{run_id}"


def _normalized_key_parts(raw_key: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", raw_key)
    separated = _CAMEL_BOUNDARY.sub("_", normalized).casefold()
    return tuple(re.findall(r"[a-z0-9]+", separated))


def _is_sensitive_key(raw_key: str) -> bool:
    parts = _normalized_key_parts(raw_key)
    compact = "".join(parts)
    if compact in _SAFE_METRIC_KEY_FORMS:
        return False
    if compact in _SENSITIVE_KEY_FORMS or any(part in _SENSITIVE_KEY_PARTS for part in parts):
        return True
    adjacent_parts = set(zip(parts, parts[1:], strict=False))
    if {("api", "key"), ("private", "key")} & adjacent_parts:
        return True
    return compact.endswith(
        ("token", "secret", "password", "credential", "authorization", "apikey", "privatekey")
    )


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


@dataclass(frozen=True)
class RunStreamRead:
    entries: tuple[RunStreamEntry, ...]
    last_seen_id: str
    scanned_count: int


def _safe_json(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_PAYLOAD_DEPTH:
        raise ValueError("Run stream payload exceeds depth limit")
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("Run stream payload keys must be strings")
            if _is_sensitive_key(raw_key):
                raise ValueError("Run stream payload contains credentials")
            out[raw_key] = _safe_json(item, depth=depth + 1)
        return out
    if isinstance(value, (tuple, list)):
        return [_safe_json(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Run stream payload must be JSON-compatible")


class RunStreamBus:
    DEFAULT_MAX_STREAM_LENGTH = 2_000
    DEFAULT_STREAM_TTL_SECONDS = 86_400
    DEFAULT_MAX_ENVELOPE_BYTES = 16 * 1024
    DEFAULT_PUBLISH_TIMEOUT_SECONDS = 0.1
    DEFAULT_CIRCUIT_COOLDOWN_SECONDS = 5.0

    def __init__(
        self,
        redis: Any,
        *,
        max_stream_length: int = DEFAULT_MAX_STREAM_LENGTH,
        stream_ttl_seconds: int = DEFAULT_STREAM_TTL_SECONDS,
        max_envelope_bytes: int = DEFAULT_MAX_ENVELOPE_BYTES,
        publish_timeout_seconds: float = DEFAULT_PUBLISH_TIMEOUT_SECONDS,
        circuit_cooldown_seconds: float = DEFAULT_CIRCUIT_COOLDOWN_SECONDS,
    ) -> None:
        if (
            min(
                max_stream_length,
                stream_ttl_seconds,
                max_envelope_bytes,
                publish_timeout_seconds,
                circuit_cooldown_seconds,
            )
            <= 0
        ):
            raise ValueError("Run stream bounds must be positive")
        self._redis = redis
        self._max_stream_length = max_stream_length
        self._stream_ttl_seconds = stream_ttl_seconds
        self._max_envelope_bytes = max_envelope_bytes
        self._publish_timeout_seconds = publish_timeout_seconds
        self._circuit_cooldown_seconds = circuit_cooldown_seconds
        self._circuit_open_until = 0.0

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
        loop = asyncio.get_running_loop()
        if loop.time() < self._circuit_open_until:
            return None
        try:
            async with asyncio.timeout(self._publish_timeout_seconds):
                async with self._redis.pipeline(transaction=True) as pipeline:
                    pipeline.xadd(
                        key,
                        {"data": encoded},
                        maxlen=self._max_stream_length,
                        approximate=False,
                    )
                    pipeline.expire(key, self._stream_ttl_seconds)
                    results = await pipeline.execute()
            entry_id = results[0]
        except Exception as exc:  # noqa: BLE001 - Redis is explicitly best-effort
            self._circuit_open_until = loop.time() + self._circuit_cooldown_seconds
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
    ) -> RunStreamRead:
        key = run_stream_key(run_id)
        kwargs: dict[str, Any] = {"streams": {key: after_id}, "count": count}
        if block_ms > 0:
            kwargs["block"] = block_ms
        response = await self._redis.xread(**kwargs)
        if not response:
            return RunStreamRead((), after_id, 0)
        entries: list[RunStreamEntry] = []
        malformed_ids: list[str] = []
        raw_entries = response[0][1]
        last_seen_id = after_id
        for raw_id, fields in raw_entries:
            entry_id = raw_id.decode("ascii") if isinstance(raw_id, bytes) else str(raw_id)
            last_seen_id = entry_id
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
            except (
                TypeError,
                ValueError,
                KeyError,
                RecursionError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
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
        return RunStreamRead(tuple(entries), last_seen_id, len(raw_entries))

    @staticmethod
    def _decode_envelope(data: Any) -> RunStreamEnvelope:
        if not isinstance(data, dict) or data.get("version") != RUN_STREAM_VERSION:
            raise ValueError("unsupported Run stream envelope")
        kind = data["kind"]
        if not isinstance(kind, str) or kind not in RUN_STREAM_KINDS:
            raise ValueError("unsupported Run stream kind")
        payload = _safe_json(data["payload"])
        durable_seq = data["durable_seq"]
        event_seq = data["event_seq"]
        step = data["step"]
        if any(type(value) is not int or value < 0 for value in (durable_seq, event_seq, step)):
            raise ValueError("invalid Run stream sequence")
        raw_run_id = data["run_id"]
        raw_attempt_id = data["attempt_id"]
        if not isinstance(raw_run_id, str) or not isinstance(raw_attempt_id, str):
            raise ValueError("Run stream UUID fields must be strings")
        return RunStreamEnvelope(
            version=RUN_STREAM_VERSION,
            run_id=UUID(raw_run_id),
            attempt_id=UUID(raw_attempt_id),
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
    "RunStreamRead",
    "run_stream_key",
]
