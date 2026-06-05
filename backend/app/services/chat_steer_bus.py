"""ChatSteerBus — 插话(steering)队列写端,Redis List(spec § 4.3)。

为什么用 List 而非 pub/sub(对照 ChatCancelBus):
- worker 在流式输出 token 的几秒里**不在监听** channel;pub/sub 是 at-most-once,
  这期间发的插话会丢。插话语义要求"并入当前 turn,不可丢"——用 List 持久化待并入,
  worker 圈边界 RPOP 必达(RedisSteerSource 读端)。
- cancel 仍走 pub/sub:丢失容忍度不同(漏 cancel 用户会再点一次),spec § 4.3。

key 形状 `chat:steer:{task_id}` 是单一来源(KEY 常量),读端 RedisSteerSource
(worker_wiring)直接 import 本类的 KEY,避免两处硬编码漂移。

写端 LPUSH + EXPIRE,读端 RPOP 循环 = FIFO(先到的插话先并入)。
"""

from __future__ import annotations

from typing import Any

# steer List key 模板 —— 写端(本 bus)与读端(RedisSteerSource)的单一来源。
STEER_KEY_TEMPLATE = "chat:steer:{task_id}"
STEER_TTL_SECONDS = 3600  # turn 级,1h 足够覆盖最长 turn + 重试窗口


def steer_key(task_id: Any) -> str:
    """构造 task 的 steer List key(读写两端共用)。"""
    return STEER_KEY_TEMPLATE.format(task_id=task_id)


class ChatSteerBus:
    """插话队列写端 —— LPUSH 待并入消息 + 刷 TTL。

    实例化时持一个 redis async client(prod redis.asyncio / test fakeredis)。
    读端在 worker_wiring.RedisSteerSource(RPOP 循环),key 经 ``steer_key`` 对齐。
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def push(self, task_id: Any, message: str) -> None:
        """LPUSH 一条插话进 task 的 List,并刷新 TTL。

        LPUSH 头插 + 读端 RPOP 尾取 = FIFO(先到的先并入)。
        EXPIRE 每次写都刷:turn 跨度内 List 不过期;turn 结束后无人 RPOP,
        自然到期清理(避免泄漏)。
        """
        key = steer_key(task_id)
        await self._redis.lpush(key, message.encode("utf-8"))
        await self._redis.expire(key, STEER_TTL_SECONDS)


__all__ = ["STEER_KEY_TEMPLATE", "STEER_TTL_SECONDS", "ChatSteerBus", "steer_key"]
