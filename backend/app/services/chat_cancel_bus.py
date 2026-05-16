"""ChatCancelBus — Redis pub/sub 封装,task cancel 信号传输。

设计:
- channel-per-task: `chat:cancel:{task_id}`
- publish_cancel: 发空 string payload(信号本身是 channel 名)
- subscribe_cancel: async generator yield 一次后 break(caller 设 Event flag)

Plan 3 spec § 6.1: graph 节点之间 wrapper 检查 Event flag,raise
GraphInterrupt → finalize 走 partial commit。Pub/Sub at-most-once delivery,
spec § 9.1 接受罕见漏 cancel(用户可以再点一次)。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis as AsyncRedis


class ChatCancelBus:
    """Redis pub/sub 抽象,实例化时持有一个 redis async client。"""

    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    @staticmethod
    def _channel(task_id: uuid.UUID) -> str:
        return f"chat:cancel:{task_id}"

    async def publish_cancel(self, task_id: uuid.UUID) -> int:
        """发 cancel 信号到 task 的 channel。返 receiver count。"""
        channel = self._channel(task_id)
        result = await self._redis.publish(channel, b"cancel")
        return int(result)

    async def subscribe_cancel(self, task_id: uuid.UUID) -> AsyncIterator[bytes]:
        """Subscribe channel,yield 收到的 message payload。

        Worker 内典型用法::

            async for _ in bus.subscribe_cancel(tid):
                cancel_event.set()
                return  # 第一次 cancel 就 break
        """
        channel = self._channel(task_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data: Any = msg.get("data")
                if isinstance(data, bytes):
                    yield data
                else:
                    yield str(data).encode()
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
