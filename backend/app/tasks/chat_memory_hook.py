"""Chat turn → 记忆写入钩子(Path A 写 episode + 触发 Path B 异步抽取)。

run_chat_async 收尾在「干净成功轮」调 persist_episode_and_trigger:写一条
ChatMemoryEpisode(user+agent 文本),再 fire-and-forget 触发
extract_session_episodes_async("post_turn")。全程 fail-soft —— 回复已 emit+持久化
在前,本钩子是纯副作用,失败只 log、不影响 turn。
设计见 docs/superpowers/specs/2026-06-11-chat-memory-write-wiring-design.md。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

_ANONYMOUS = "anonymous"


def enqueue_episode_extraction(session_id: str) -> Any:
    """Fire-and-forget 触发 Path B 抽取(per-turn,trigger_reason='post_turn')。

    单独成函数:测试 monkey-patch / 注入即可绕开真 Celery .delay()
    (对齐 chat_runner.enqueue_run_chat 的测试惯例)。
    """
    from app.tasks.memory import extract_session_episodes_async

    return extract_session_episodes_async.delay(session_id, "post_turn")


def _should_persist(
    *,
    cancelled: bool,
    loop_error: Exception | None,
    final_state: Any,
    user_id: Any,
    user_message: str,
    agent_response: str,
) -> bool:
    if cancelled or loop_error is not None or final_state is None:
        return False
    if user_id is None or str(user_id) == _ANONYMOUS:
        return False
    if not (user_message and user_message.strip()):
        return False
    return bool(agent_response and agent_response.strip())


async def persist_episode_and_trigger(
    memory: Any,
    *,
    session_id: str,
    user_id: Any,
    user_message: str,
    agent_response: str,
    cancelled: bool,
    loop_error: Exception | None,
    final_state: Any,
    enqueue: Callable[[str], Any] = enqueue_episode_extraction,
) -> bool:
    """干净成功轮:写 episode + 触发抽取。返回是否写了 episode。fail-soft。"""
    if not _should_persist(
        cancelled=cancelled,
        loop_error=loop_error,
        final_state=final_state,
        user_id=user_id,
        user_message=user_message,
        agent_response=agent_response,
    ):
        return False

    try:
        uid = UUID(str(user_id))
        sid = UUID(str(session_id))
        idx = await memory.next_episode_index(sid)
        await memory.write_episode(
            user_id=uid,
            session_id=sid,
            episode_index=idx,
            user_message=user_message,
            agent_response=agent_response,
            source_kind="chat_turn",
        )
    except Exception as exc:  # noqa: BLE001 — 纯副作用,失败不得影响 turn
        logger.warning("chat memory: write_episode 失败 session=%s: %s", session_id, exc)
        return False

    try:
        enqueue(str(session_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat memory: 抽取触发失败 session=%s: %s", session_id, exc)
    return True
