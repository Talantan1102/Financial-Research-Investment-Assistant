"""L0 — chat turn → 记忆写入钩子:写/不写各分支 + fail-soft + 触发参数。"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from app.tasks.chat_memory_hook import persist_episode_and_trigger


class _FakeMemory:
    def __init__(self, *, raise_on_write: bool = False) -> None:
        self.raise_on_write = raise_on_write
        self.episodes: list[dict[str, Any]] = []
        self._next = 0

    async def next_episode_index(self, session_id: UUID) -> int:
        return self._next

    async def write_episode(self, **kwargs: Any) -> dict[str, Any]:
        if self.raise_on_write:
            raise RuntimeError("PG down")
        self.episodes.append(kwargs)
        self._next += 1
        return kwargs


class _FakeEnqueue:
    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls: list[str] = []
        self.raise_on_call = raise_on_call

    def __call__(self, session_id: str) -> None:
        if self.raise_on_call:
            raise RuntimeError("broker down")
        self.calls.append(session_id)


def _kw(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": str(uuid4()),
        "user_id": uuid4(),
        "user_message": "我重仓茅台",
        "agent_response": "已记录你的持仓偏好。",
        "cancelled": False,
        "loop_error": None,
        "final_state": object(),  # 非 None 即可
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_clean_success_writes_and_triggers() -> None:
    mem = _FakeMemory()
    enq = _FakeEnqueue()
    kw = _kw()
    wrote = await persist_episode_and_trigger(mem, enqueue=enq, **kw)
    assert wrote is True
    assert len(mem.episodes) == 1
    ep = mem.episodes[0]
    assert ep["user_message"] == "我重仓茅台"
    assert ep["agent_response"] == "已记录你的持仓偏好。"
    assert ep["episode_index"] == 0
    assert ep["source_kind"] == "chat_turn"
    assert enq.calls == [kw["session_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"cancelled": True},
        {"loop_error": RuntimeError("boom")},
        {"final_state": None},
        {"user_id": None},
        {"user_id": "anonymous"},
        {"agent_response": "   "},
        {"user_message": ""},
    ],
)
async def test_skips_when_not_clean_success(over: dict[str, Any]) -> None:
    mem = _FakeMemory()
    enq = _FakeEnqueue()
    wrote = await persist_episode_and_trigger(mem, enqueue=enq, **_kw(**over))
    assert wrote is False
    assert mem.episodes == []
    assert enq.calls == []


@pytest.mark.asyncio
async def test_fail_soft_when_write_raises() -> None:
    mem = _FakeMemory(raise_on_write=True)
    enq = _FakeEnqueue()
    # 不得抛出;返回 False;触发不被调用(没写成功就不触发)
    wrote = await persist_episode_and_trigger(mem, enqueue=enq, **_kw())
    assert wrote is False
    assert enq.calls == []


@pytest.mark.asyncio
async def test_fail_soft_when_enqueue_raises() -> None:
    mem = _FakeMemory()
    enq = _FakeEnqueue(raise_on_call=True)
    # episode 已写成功 → 返回 True;触发失败被吞,不抛
    wrote = await persist_episode_and_trigger(mem, enqueue=enq, **_kw())
    assert wrote is True
    assert len(mem.episodes) == 1


def test_enqueue_episode_extraction_passes_post_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 enqueue 必须以 (session_id, "post_turn") 调真 Celery .delay(防 trigger 档漂移)。"""
    import app.tasks.memory as memory_mod
    from app.tasks.chat_memory_hook import enqueue_episode_extraction

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        memory_mod.extract_session_episodes_async, "delay", lambda *a: calls.append(a)
    )
    enqueue_episode_extraction("sess-123")
    assert calls == [("sess-123", "post_turn")]
