"""ChatEventBus — Redis Streams 封装,负责 chat in-flight event 的 XADD/XREAD。

设计目标:
- 一个 task 对应一个 stream key: chat:events:{session_id}:{task_id}
- XADD 时把 event payload(dict)序列化成 JSON 单字段 'data'(stream entry id 由 Redis 自动生成,单调)
- XREAD BLOCK 等待新 entry,支持 last_id 协议(对应 SSE Last-Event-ID)
- TTL 24h(spec § 6.3),task 创建时 setup,完成时再续 24h

使用模式:
- 一个 ChatEventBus 实例持有一个 redis async client,跨 Celery worker / web SSE handler 共享
"""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

from redis.asyncio import Redis as AsyncRedis

# redis-py xadd fields dict has invariant key/value unions; declare a matching alias
# so mypy strict accepts our 1-key payload dict.
_RedisField = bytes | bytearray | memoryview | str | int | float


class ChatEventBus:
    """Redis Streams 抽象,实例化时持有一个 redis async client。"""

    DEFAULT_TTL_SECONDS = 86400  # 24h, spec § 6.3

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    @staticmethod
    def _stream_key(session_id: uuid.UUID, task_id: uuid.UUID) -> str:
        return f"chat:events:{session_id}:{task_id}"

    async def xadd_event(
        self,
        session_id: uuid.UUID,
        task_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> str:
        """Append one event to the stream. Returns new entry id (e.g., '1716000000000-0').

        Payload 序列化为 JSON 字符串放进 'data' 字段。
        Spec § 6.2: entry id 透传给前端做 SSE last_event_id。
        """
        key = self._stream_key(session_id, task_id)
        data: dict[_RedisField, _RedisField] = {"data": json.dumps(payload, ensure_ascii=False)}
        entry_id = await self._redis.xadd(key, data)
        if isinstance(entry_id, bytes):
            return entry_id.decode()
        return cast(str, entry_id)

    async def xread_blocking(
        self,
        session_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        last_id: str,
        count: int = 50,
        block_ms: int = 30_000,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read entries after last_id. Blocks up to block_ms.

        Returns: list of (entry_id, decoded_payload). Empty list on timeout.
        """
        key = self._stream_key(session_id, task_id)
        result = await self._redis.xread(
            streams={key: last_id},
            count=count,
            block=block_ms,
        )
        if not result:
            return []
        # result shape: [(stream_name, [(entry_id, {field: value, ...}), ...])]
        _, entries = result[0]
        out: list[tuple[str, dict[str, Any]]] = []
        for raw_id, fields in entries:
            entry_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            data_raw: Any = fields.get(b"data") if b"data" in fields else fields.get("data")
            if isinstance(data_raw, bytes):
                data_raw = data_raw.decode("utf-8")
            payload = json.loads(data_raw)
            out.append((entry_id, payload))
        return out

    async def set_ttl(
        self,
        session_id: uuid.UUID,
        task_id: uuid.UUID,
        *,
        seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        """Set/refresh TTL on the stream key. Idempotent."""
        key = self._stream_key(session_id, task_id)
        await self._redis.expire(key, seconds)
