# Chat 记忆写入接线 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让跨会话记忆从对话自动积累 —— chat 每轮干净结束后写一条 episode,fire-and-forget 触发已建好的 Path B 异步抽取。

**Architecture:** 在 `chat_runner.run_chat_async` 收尾(`_finalize` 之后)新增一个 fail-soft 钩子:仅在「干净成功轮」写 `ChatMemoryEpisode` 并触发 `extract_session_episodes_async("post_turn")`。钩子逻辑抽到独立小模块 `chat_memory_hook.py` 便于隔离单测;`HierarchicalMemory` 加 `next_episode_index` 算下一个 episode 序号;`_VALID_TRIGGER_REASONS` 加 `post_turn` 档。抽取/AGE 内部不动(复用现成)。

**Tech Stack:** Python 3.12 / asyncio / SQLAlchemy(sync Session via `pg_session_factory`)/ Celery(`.delay` fire-and-forget)/ pytest(asyncio + 真 PG fixture)。后端测试环境 = WSL `~/fria-venv`,跑前 `set -a; . ./.env; set +a`(供 POSTGRES_* 等)。

设计依据:`docs/superpowers/specs/2026-06-11-chat-memory-write-wiring-design.md`。

---

## File Structure

- **Modify** `backend/app/memory/hierarchical.py` — 加 `next_episode_index(session_id) -> int`(一条 `max+1` 查询,沿用 `session.query(...).filter(...)` 风格)。
- **Modify** `backend/app/tasks/memory.py` — `_VALID_TRIGGER_REASONS` 加 `"post_turn"`。
- **Create** `backend/app/tasks/chat_memory_hook.py` — `enqueue_episode_extraction`(`.delay` 薄封装,测试 patch 点)+ `persist_episode_and_trigger`(干净成功轮守卫 + 写 episode + 触发,fail-soft)。
- **Modify** `backend/app/tasks/chat_runner.py` — `run_chat_async` 的 finally 末调 `persist_episode_and_trigger`。
- **Create** `backend/tests/unit/test_chat_memory_hook.py` — L0 钩子逻辑全分支单测(假 memory/假 enqueue)。
- **Create** `backend/tests/unit/test_memory_trigger_reasons.py` — L0 断言 `post_turn` 合法。
- **Modify** `backend/tests/integration/memory/test_episodes_e2e.py` — 加 `next_episode_index` 的 L1 测试。

---

### Task 1: `next_episode_index` on HierarchicalMemory

**Files:**
- Modify: `backend/app/memory/hierarchical.py`(在 `write_episode` 附近加方法)
- Test: `backend/tests/integration/memory/test_episodes_e2e.py`(追加)

- [ ] **Step 1: Write the failing test**(追加到 `test_episodes_e2e.py` 末尾)

```python
@pytest.mark.asyncio
async def test_next_episode_index_increments(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    user_uuid = _make_user(pg_memory_fixture)
    session_uuid = _make_session(pg_memory_fixture, user_uuid)

    # 空 session → 0
    assert await hier_memory.next_episode_index(session_uuid) == 0

    await hier_memory.write_episode(
        user_id=user_uuid,
        session_id=session_uuid,
        episode_index=0,
        user_message="我重仓茅台",
        agent_response="了解,已记录你的持仓偏好。",
    )
    # 写了 index 0 → 下一个是 1
    assert await hier_memory.next_episode_index(session_uuid) == 1

    await hier_memory.write_episode(
        user_id=user_uuid,
        session_id=session_uuid,
        episode_index=1,
        user_message="还有五粮液",
        agent_response="好的。",
    )
    assert await hier_memory.next_episode_index(session_uuid) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a; . ./.env 2>/dev/null; set +a; cd backend && ~/fria-venv/bin/python -m pytest tests/integration/memory/test_episodes_e2e.py::test_next_episode_index_increments -p no:cacheprovider -o addopts='' -q"`
Expected: FAIL — `AttributeError: 'HierarchicalMemory' object has no attribute 'next_episode_index'`

- [ ] **Step 3: Write minimal implementation**(加到 `hierarchical.py`,紧挨 `write_episode` 之后)

```python
    async def next_episode_index(self, session_id: UUID) -> int:
        """返回该 session 下一个 episode_index(max+1;空 session 为 0)。

        DB 有唯一约束 (session_id, episode_index);本方法不加锁,单用户顺序聊天
        无并发,罕见并发由唯一约束 + 上层 fail-soft 兜。
        """
        from sqlalchemy import func

        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            max_idx = (
                session.query(func.max(ChatMemoryEpisode.episode_index))
                .filter(ChatMemoryEpisode.session_id == session_id)
                .scalar()
            )
            return 0 if max_idx is None else int(max_idx) + 1
        finally:
            session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: 同 Step 2 的命令
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/memory/hierarchical.py backend/tests/integration/memory/test_episodes_e2e.py
git commit -m "feat(memory): HierarchicalMemory.next_episode_index(session 下一个 episode 序号)"
```

---

### Task 2: `post_turn` trigger reason

**Files:**
- Modify: `backend/app/tasks/memory.py:36`(`_VALID_TRIGGER_REASONS`)
- Test: `backend/tests/unit/test_memory_trigger_reasons.py`(新建)

- [ ] **Step 1: Write the failing test**

```python
"""L0 — Path B 触发档校验(per-turn 接线加了 post_turn 档)。"""

from __future__ import annotations

from app.tasks.memory import _VALID_TRIGGER_REASONS


def test_post_turn_is_valid_trigger_reason() -> None:
    assert "post_turn" in _VALID_TRIGGER_REASONS


def test_existing_session_boundary_reasons_kept() -> None:
    assert {"session_closed", "idle_30min", "new_session_started"} <= _VALID_TRIGGER_REASONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a; . ./.env 2>/dev/null; set +a; cd backend && ~/fria-venv/bin/python -m pytest tests/unit/test_memory_trigger_reasons.py -p no:cacheprovider -o addopts='' -q"`
Expected: FAIL — `test_post_turn_is_valid_trigger_reason` AssertionError(`post_turn` 不在集合里)

- [ ] **Step 3: Write minimal implementation**(改 `memory.py:36`)

```python
_VALID_TRIGGER_REASONS = frozenset(
    {"session_closed", "idle_30min", "new_session_started", "post_turn"}
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: 同 Step 2
Expected: PASS(2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/memory.py backend/tests/unit/test_memory_trigger_reasons.py
git commit -m "feat(memory): Path B 触发加 post_turn 档(per-turn 接线)"
```

---

### Task 3: `chat_memory_hook.py`(钩子逻辑 + 全分支单测)

**Files:**
- Create: `backend/app/tasks/chat_memory_hook.py`
- Test: `backend/tests/unit/test_chat_memory_hook.py`

- [ ] **Step 1: Write the failing test**

```python
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
    base = {
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a; . ./.env 2>/dev/null; set +a; cd backend && ~/fria-venv/bin/python -m pytest tests/unit/test_chat_memory_hook.py -p no:cacheprovider -o addopts='' -q"`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tasks.chat_memory_hook'`

- [ ] **Step 3: Write minimal implementation**(`backend/app/tasks/chat_memory_hook.py`)

```python
"""Chat turn → 记忆写入钩子(Path A 写 episode + 触发 Path B 异步抽取)。

run_chat_async 收尾在「干净成功轮」调 persist_episode_and_trigger:写一条
ChatMemoryEpisode(user+agent 文本),再 fire-and-forget 触发
extract_session_episodes_async("post_turn")。全程 fail-soft —— 回复已 emit+持久化
在前,本钩子是纯副作用,失败只 log、不影响 turn。
设计见 docs/superpowers/specs/2026-06-11-chat-memory-write-wiring-design.md。
"""

from __future__ import annotations

import logging
from typing import Any, Callable
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
    if not (agent_response and agent_response.strip()):
        return False
    return True


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: 同 Step 2
Expected: PASS(clean + 7 参数化 skip + 2 fail-soft = 10 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/chat_memory_hook.py backend/tests/unit/test_chat_memory_hook.py
git commit -m "feat(memory): chat turn 记忆写入钩子(写 episode + fire-and-forget 触发,fail-soft)"
```

---

### Task 4: 接进 `run_chat_async`

**Files:**
- Modify: `backend/app/tasks/chat_runner.py`(`run_chat_async` 的 finally 末,`_finalize` + TTL 之后)

- [ ] **Step 1: Add the hook call**(在 finally 块内、TTL refresh 之后追加;`emitted_tokens` / `cancelled_by_user` / `loop_error` / `final_state` / `user_message` / `session_id` / `user_id` / `singletons` 此处均在作用域)

```python
        # Path A 写 episode + 触发 Path B 抽取(干净成功轮;纯副作用,fail-soft 双保险)
        try:
            from app.tasks.chat_memory_hook import persist_episode_and_trigger

            await persist_episode_and_trigger(
                singletons.memory,
                session_id=session_id,
                user_id=user_id,
                user_message=user_message,
                agent_response="".join(emitted_tokens),
                cancelled=cancelled_by_user,
                loop_error=loop_error,
                final_state=final_state,
            )
        except Exception as exc:  # noqa: BLE001 — 钩子内部已 fail-soft,这里再兜一层
            logger.warning("chat memory hook failed task=%s: %s", task_id, exc)
```

- [ ] **Step 2: Run existing chatloop e2e + 相关单测验证无回归**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a; . ./.env 2>/dev/null; set +a; cd backend && ~/fria-venv/bin/python -m pytest tests/e2e/test_chatloop_cassette.py tests/unit/chatloop -p no:cacheprovider -o addopts='' -q"`
Expected: PASS(无回归;若 cassette 用的 Fake memory 无 `next_episode_index`,钩子 fail-soft 吞掉、只 log,不破坏断言)

- [ ] **Step 3: Commit**

```bash
git add backend/app/tasks/chat_runner.py
git commit -m "feat(chat): run_chat_async 收尾接记忆写入钩子(per-turn episode + Path B 触发)"
```

---

### Task 5: 回归 + lint/type

**Files:** 无(验证 + 收尾)

- [ ] **Step 1: 改动面全回归**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a; . ./.env 2>/dev/null; set +a; cd backend && ~/fria-venv/bin/python -m pytest tests/unit/test_chat_memory_hook.py tests/unit/test_memory_trigger_reasons.py tests/integration/memory/test_episodes_e2e.py tests/e2e/test_chatloop_cassette.py tests/unit/chatloop -p no:cacheprovider -o addopts='' -q"`
Expected: 全 PASS

- [ ] **Step 2: ruff + mypy(改动文件)**

Run: `wsl.exe -- bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && ~/fria-venv/bin/python -m ruff check app/tasks/chat_memory_hook.py app/tasks/chat_runner.py app/tasks/memory.py app/memory/hierarchical.py && ~/fria-venv/bin/python -m mypy app/tasks/chat_memory_hook.py app/memory/hierarchical.py"`
Expected: ruff All checks passed;mypy no issues(如有 ruff 可 `--fix` 的格式问题就修后重跑)

- [ ] **Step 3: Commit any lint fixes(若有)**

```bash
git add -u backend/app
git commit -m "style(memory): ruff/mypy 收尾"
```

---

## Self-Review

**1. Spec coverage:**
- 轮末写 episode → Task 4(钩子调用)+ Task 3(钩子逻辑)+ Task 1(episode_index)。✓
- 触发抽取 → Task 3(`enqueue_episode_extraction`)+ Task 2(`post_turn` 档)。✓
- fail-soft / 不写分支(cancel/error/匿名/空)→ Task 3 全分支单测。✓
- 不依赖 AGE / 不改 cross_turn_grouper / PathBRunner → 本计划不碰这些文件。✓
- 显式不做(乙 / AGE / 会话边界触发)→ 计划无对应任务,符合 spec。✓

**2. Placeholder scan:** 无 TBD/TODO;每个 code step 给了完整代码。✓

**3. Type consistency:** `persist_episode_and_trigger` / `enqueue_episode_extraction` / `next_episode_index` / `_VALID_TRIGGER_REASONS` 在定义(Task 1-3)与调用(Task 4)处签名一致;`write_episode` 调用的 kwargs(user_id/session_id/episode_index/user_message/agent_response/source_kind)与 `hierarchical.py:693` 真实签名一致。✓
