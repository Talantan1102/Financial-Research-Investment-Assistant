"""chat_runner 的 worker 持久事件循环单测(E2E 实测修复回归守护)。

根因(浏览器联调):Celery 同步包装曾用 ``asyncio.run(...)`` —— 每个 task 新建并
关闭一个事件循环;但模块级单例(MCP stdio 流 / redis.asyncio 客户端 / LLMService
持的 httpx)绑定在第一个 task 的循环上,第二个 task 的新循环里复用 → 跨循环崩坏。

Fix(方案 C):进程级常驻 loop,经 ``run_until_complete`` 驱动,使 loop-bound 单例
跨 task 存活。本测试守护两条性质:
1. 两次调用 ``_get_worker_loop`` 返回同一实例;
2. 第一次 run_until_complete 在该 loop 上创建的 asyncio 原语(如 Queue),第二次
   run_until_complete 仍能使用 —— 证明原语未因 loop 关闭而失效,即跨 task 存活。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.chatloop.state import ChatLoopState


@pytest.fixture(autouse=True)
def _reset_worker_loop():
    """每个测试前后复位模块级 loop 单例,避免测试间串扰 / 关掉自建 loop。"""
    import app.tasks.chat_runner as cr

    prev = cr._WORKER_LOOP
    cr._WORKER_LOOP = None
    try:
        yield
    finally:
        created = cr._WORKER_LOOP
        if created is not None and created is not prev and not created.is_closed():
            created.close()
        cr._WORKER_LOOP = prev


def test_get_worker_loop_returns_same_instance() -> None:
    """两次调用同一进程内返回同一 loop 实例(进程级单例)。"""
    from app.tasks.chat_runner import _get_worker_loop

    loop1 = _get_worker_loop()
    loop2 = _get_worker_loop()

    assert loop1 is loop2
    assert not loop1.is_closed()


def test_worker_loop_survives_across_run_until_complete() -> None:
    """跨两次 run_until_complete:第一次创建的 asyncio 原语在第二次仍可用。

    这正是 prod 里 MCP stdio 流 / redis 客户端的 loop-bound 性质 —— 用 asyncio.Queue
    做最小代理:第一次 task 在 loop 上创建并 put,第二次 task 在同一 loop 上 get 出来。
    若 loop 被 asyncio.run 关闭(旧实现),第二次会在新 loop 上,Queue 跨循环不可用。
    """
    from app.tasks.chat_runner import _get_worker_loop

    loop = _get_worker_loop()
    shared: dict[str, asyncio.Queue[str]] = {}

    async def _first() -> None:
        # 在当前 loop 上创建一个 loop-bound 原语并写入,模拟 task 1 构造单例
        q: asyncio.Queue[str] = asyncio.Queue()
        await q.put("from-task-1")
        shared["q"] = q

    async def _second() -> str:
        # 第二个 task:复用 task 1 创建的原语;必须仍绑在同一活 loop 上
        q = shared["q"]
        return await q.get()

    loop.run_until_complete(_first())
    # 关键:loop 没被关闭,仍是同一个
    assert _get_worker_loop() is loop
    assert not loop.is_closed()

    result = loop.run_until_complete(_second())
    assert result == "from-task-1"


def test_worker_loop_rebuilds_if_closed() -> None:
    """若 loop 被意外关闭,下次取用应重建(防 worker 进程内死锁)。"""
    from app.tasks.chat_runner import _get_worker_loop

    loop1 = _get_worker_loop()
    loop1.close()

    loop2 = _get_worker_loop()
    assert loop2 is not loop1
    assert not loop2.is_closed()


@pytest.mark.asyncio
async def test_lazy_episode_resolver_creates_once_and_exposes_id() -> None:
    """archival_insert 首次调用才建 episode；同 turn 重试复用同一 provenance。"""
    from app.tasks.chat_runner import _build_lazy_episode_resolver

    class Memory:
        def __init__(self) -> None:
            self.writes = []

        async def next_episode_index(self, session_id):
            return 4

        async def write_episode(self, **kwargs):
            self.writes.append(kwargs)
            return SimpleNamespace(episode_id=uuid4())

    memory = Memory()
    uid, sid = uuid4(), uuid4()
    resolver, episode_ref = _build_lazy_episode_resolver(memory, user_id=uid, session_id=str(sid))
    state = ChatLoopState(
        user_id=str(uid),
        session_id=str(sid),
        request_id=str(uuid4()),
        messages=[
            {"role": "user", "content": "我买了茅台"},
            {"role": "user", "content": "还买了五粮液"},
        ],
    )

    first = await resolver(state)
    second = await resolver(state)

    assert first == second == episode_ref["episode_id"]
    assert len(memory.writes) == 1
    assert memory.writes[0]["episode_index"] == 4
    assert memory.writes[0]["user_message"] == "我买了茅台\n还买了五粮液"
    assert memory.writes[0]["agent_response"] == ""
