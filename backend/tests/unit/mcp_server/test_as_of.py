"""_as_of 双路径(env / ContextVar)+ 并发隔离单测。

T1(verl 工具对齐):RL 工具服务单进程并发处理多题、每题 as_of 不同。
旧实现只读 env(进程全局)→ 并发会串题。改用 ContextVar(task-local)后并发安全。
本测重点证明:① ContextVar 优先 env ② 并发两 task 不同 as_of 互不串。
"""

import asyncio

import pytest
from app.mcp_server._as_of import _ASOF_VAR, eval_as_of, set_eval_as_of


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """每个用例:清 env + 重置 ContextVar,避免互相污染。"""
    monkeypatch.delenv("CHAT_TOOLS_AS_OF", raising=False)
    token = _ASOF_VAR.set(None)
    yield
    _ASOF_VAR.reset(token)


def test_default_none():
    assert eval_as_of() is None


def test_env_fallback(monkeypatch):
    monkeypatch.setenv("CHAT_TOOLS_AS_OF", "20260612")
    assert eval_as_of() == "20260612"  # 生产/SFT 采轨路径不变


def test_contextvar_precedence(monkeypatch):
    monkeypatch.setenv("CHAT_TOOLS_AS_OF", "20260612")
    set_eval_as_of("20240101")
    assert eval_as_of() == "20240101"  # ContextVar 压过 env


def test_empty_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("CHAT_TOOLS_AS_OF", "20260612")
    set_eval_as_of(None)
    assert eval_as_of() == "20260612"  # 清覆盖 → 回落 env


@pytest.mark.asyncio
async def test_concurrent_isolation(monkeypatch):
    """命门:env 设成第三值,两并发 task 各设不同 as_of,各读各的、都不等 env。"""
    monkeypatch.setenv("CHAT_TOOLS_AS_OF", "29990101")
    results: dict[str, str | None] = {}

    async def worker(val: str) -> None:
        set_eval_as_of(val)
        await asyncio.sleep(0.01)  # 让两 task 交错执行,暴露全局串扰
        results[val] = eval_as_of()

    # create_task 在创建时拷贝上下文;各 worker 在自己 task 上下文里 set,互不影响
    await asyncio.gather(
        asyncio.create_task(worker("20240101")),
        asyncio.create_task(worker("20250202")),
    )
    assert results["20240101"] == "20240101"  # 没串成对方 / env
    assert results["20250202"] == "20250202"
