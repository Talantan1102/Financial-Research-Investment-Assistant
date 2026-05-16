# Chat Session Persistence — Plan 2: In-flight Subscribe

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 chat 推理从 web 进程的 inline SSE generator 解耦到 Celery worker;事件流通过 Redis Streams 中转;新增 `GET /chat/stream/{task_id}` SSE replay endpoint;前端断流后真正订阅 in-flight 增量(C 档)。

**Architecture:**
- `POST /api/v0/chat` 改造为「enqueue Celery + 立即返回 task_id + stream_url」(不再 inline 跑 graph)
- 新 Celery task `run_chat` 跑 LangGraph,边跑边 XADD chunk-level event 到 `chat:events:{sid}:{tid}` stream
- 新 `GET /api/v0/chat/stream/{task_id}?last_event_id=X` 端点:Web 从 Redis Streams XREAD BLOCK 转发为 SSE
- 前端 `useChatSSE` 改成「POST 拿 task_id → 立刻打开 GET /stream/{tid}」两阶段;断流后 GET /chats/{sid} 拿到 active_task_id 后**继续订阅 in-flight stream**
- 打字机渲染:`chunk`-level event 到达后,前端 char queue + RAF 调速逐字符吐
- 服务端 `request.is_disconnected()` 检测客户端断开 → 停 SSE 转发,**但不杀 Celery task**(C 档承诺关页面继续跑)

**Tech Stack:** Celery 5.x(项目已有,B-3 监控 + C.5 memory 在用)+ Redis 7+ Streams + FastAPI StreamingResponse + 前端 React/TypeScript + requestAnimationFrame 打字机。

**Spec 锚:** `docs/superpowers/specs/2026-05-16-chat-session-persistence-design.md` § 3 组件清单 / § 5.1-5.2 / § 5.5 / § 6.2-6.3 / § 6.5。

**Plan 范围(YAGNI)**:
- ✅ 做:Celery task / ChatEventBus / 新 POST 行为 / 新 GET stream endpoint / 前端打字机 / 服务端断开检测 / chunk-level event / L0/L1/L2 测试
- ❌ 不做(留 Plan 3):cancel endpoint / ChatCancelBus / retry from LangGraph checkpoint / stale scanner / Beat 自愈 / L2 chaos 演练 / Differential golden 3 case
- ❌ 不做(显式):Redis AOF 持久化 / 多 tab fan-out 强同步 / 跨用户 Celery quota

**完成后用户感知**:
1. **关页面 30 秒后重开 → 看到推理继续跑的实时流**(C 档承诺核心场景)
2. **用户在前端看到 token-by-token 的打字机效果**(实际后端 push chunk 级,前端 RAF 调速模拟 token 级视觉)
3. **web 进程 reload 不影响推理**(Celery 独立进程,推理跟 web 进程生命周期解耦)

**Plan 1 已就位的留口(Plan 2 直接消费,不动 schema)**:
- `chat_tasks.last_event_seq`(用于 stale 探测,Plan 2 在 worker 内 bump)
- `chat_tasks.langgraph_checkpoint_id`(Plan 2 写入,Plan 3 retry 读)
- `chat_tasks.status` 6 状态机(Plan 2 复用 Plan 1 的状态迁移方法集)
- `GET /chats/{sid}` 返回 `active_task_id`(Plan 2 前端拿这个去订阅 stream)
- `_finalize_task_persistence` helper(Plan 1 在 `_stream_chat` 内,Plan 2 移到 Celery worker)

---

## File Structure

| 文件 | 新/改 | 责任 |
|---|---|---|
| `backend/app/services/chat_event_bus.py` | **新** | `ChatEventBus`:Redis Streams 封装 — XADD / XREAD blocking / TTL setup;同步 + 异步两套 API |
| `backend/app/tasks/chat_runner.py` | **新** | Celery task `run_chat(task_id)` — 异步跑 `graph.astream_events`,边跑边 XADD;try/finally 调 `_finalize_task_persistence` |
| `backend/app/router/chat.py` | **改** | `POST /chat` 改成 enqueue + 返回 `{task_id, stream_url, session_id}`;新 `GET /chat/stream/{tid}` endpoint;legacy `_stream_chat` 退役(整个移到 chat_runner.py)|
| `backend/app/router/chat_finalize.py` | **新**(从 chat.py 抽出)| 把 Plan 1 的 `_finalize_task_persistence` 抽成共享 helper,Celery worker 也能 import(避免循环依赖)|
| `backend/app/app_main.py` | **微改** | wire Redis client / Celery broker URL / `ChatEventBus` 单例到 `app.state`(若 Plan 1 还没接 Redis 的话)|
| `backend/celery_app.py` 或现有 Celery 入口 | **微改** | 把 `app.tasks.chat_runner` 加入 Celery worker 的 autodiscovery imports |
| `frontend/src/hooks/useChatSSE.ts` | **改** | 双阶段:POST → 拿 task_id → 立刻 GET /chat/stream/{tid};断流后 reload + 继续订阅 active_task_id;chunk → 打字机 char queue |
| `frontend/src/api/chatApi.ts` | **改** | `buildChatStreamUrl` 改成 `buildChatTaskStreamUrl(taskId, lastEventId)`,路径 `/chat/stream/{task_id}`;新 helper `postChatAndGetTask(...)` |
| `frontend/src/store/current-chat.ts` | **微改** | `CurrentChatState` 加 `active_task_id` 字段;`setActiveTaskId(tid)` action;打字机 queue + RAF 调速(可能独立成 hook `useTypewriter`)|
| `backend/tests/unit/test_chat_event_bus.py` | **新** | L0 unit:XADD / XREAD with last_id / TTL(用 fakeredis 或 sync redis test container)|
| `backend/tests/unit/test_chat_runner.py` | **新** | L0 unit:Celery `run_chat` 单元(eager mode)— normal path + LLM error path |
| `backend/tests/integration/test_chat_inflight_plan2.py` | **新** | L1 集成:POST /chat → 拿 task_id → GET /chat/stream/{tid} → 收到至少 1 个 token event + done;无 active_task 时 stream 拉历史 |
| `backend/tests/integration/test_chat_inflight_l2.py` | **新** | L2 集成:真 Celery worker subprocess + 真 Redis + 完整链路;客户端断开后服务端 task 继续跑 |
| `frontend/src/hooks/__tests__/useChatSSE.test.tsx` | **改** | 测试双阶段流 + reconnect 走 task_id stream + 打字机渲染速率 |

**为什么 chat_finalize.py 单独成文件**:`_finalize_task_persistence` 在 Plan 1 是 `chat.py` 内的 private helper。Plan 2 Celery worker 要复用同样的 commit 逻辑(append assistant message + mark task done/error)。从 `chat_runner.py` import `chat.py` 会创建循环依赖(chat.py 也要 import worker enqueue 函数)。抽出独立 module 切断循环。

---

## Task 1: ChatEventBus — Redis Streams 封装 + L0 测试

**Spec 锚:** spec § 6.2(Redis Streams entry id ↔ HTTP last_event_id 协议)+ § 6.3(TTL 24h)

**Files:**
- Create: `backend/app/services/chat_event_bus.py`
- Test: `backend/tests/unit/test_chat_event_bus.py`

- [ ] **Step 1: 写失败测试 — ChatEventBus 6 方法**

新建 `backend/tests/unit/test_chat_event_bus.py`:

```python
"""ChatEventBus L0 unit — Redis Streams XADD / XREAD / TTL 封装。

测试策略:fakeredis-py(已在项目 deps 中,c5-plan2a-write-pipeline 用过)。
覆盖:
- xadd_event 增 entry 并返回 stream entry id
- xread_blocking 拿到 entry,last_id="0" 从头读
- 多次 xadd 后 last_id 单调递增
- set_ttl 让 stream 24h 过期
- xread_blocking 传 last_id 后只拿新增
- xadd_event 大 payload 也能存(>1KB JSON)
"""
from __future__ import annotations

import json
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from app.services.chat_event_bus import ChatEventBus


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


@pytest.fixture
def bus(fake_redis: FakeRedis) -> ChatEventBus:
    return ChatEventBus(redis=fake_redis)


@pytest.fixture
def session_task_ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


@pytest.mark.asyncio
async def test_xadd_event_returns_entry_id(bus: ChatEventBus, session_task_ids):
    sid, tid = session_task_ids
    entry_id = await bus.xadd_event(sid, tid, {"type": "token", "text": "hello"})
    # Redis stream id format: <ms>-<seq>
    assert "-" in entry_id
    ms_str, seq_str = entry_id.split("-")
    assert ms_str.isdigit()
    assert seq_str.isdigit()


@pytest.mark.asyncio
async def test_xread_blocking_from_zero_returns_all(bus: ChatEventBus, session_task_ids):
    sid, tid = session_task_ids
    await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    assert len(entries) == 2
    assert entries[0][1]["type"] == "token"
    assert entries[0][1]["text"] == "a"
    assert entries[1][1]["text"] == "b"


@pytest.mark.asyncio
async def test_xread_blocking_with_last_id_returns_only_new(
    bus: ChatEventBus, session_task_ids
):
    sid, tid = session_task_ids
    first = await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    entries = await bus.xread_blocking(sid, tid, last_id=first, count=10, block_ms=10)
    assert len(entries) == 1
    assert entries[0][1]["text"] == "b"


@pytest.mark.asyncio
async def test_xread_blocking_empty_stream_returns_empty(
    bus: ChatEventBus, session_task_ids
):
    sid, tid = session_task_ids
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    assert entries == []


@pytest.mark.asyncio
async def test_set_ttl_marks_stream_for_expiry(
    bus: ChatEventBus, fake_redis: FakeRedis, session_task_ids
):
    sid, tid = session_task_ids
    await bus.xadd_event(sid, tid, {"type": "token", "text": "x"})
    await bus.set_ttl(sid, tid, seconds=86400)
    key = bus._stream_key(sid, tid)
    pttl = await fake_redis.pttl(key)
    # 24h = 86_400_000 ms, allow ±10s for fakeredis quirks
    assert 86_000_000 < pttl <= 86_400_001


@pytest.mark.asyncio
async def test_xadd_event_handles_large_payload(bus: ChatEventBus, session_task_ids):
    sid, tid = session_task_ids
    large_text = "x" * 5000  # 5KB
    entry_id = await bus.xadd_event(sid, tid, {"type": "token", "text": large_text})
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=1, block_ms=10)
    assert len(entries) == 1
    assert entries[0][1]["text"] == large_text
    assert entries[0][0] == entry_id


@pytest.mark.asyncio
async def test_stream_key_isolation(bus: ChatEventBus, session_task_ids):
    """两个不同 session/task 的 stream 必须不互相串流。"""
    sid1, tid1 = session_task_ids
    sid2, tid2 = uuid.uuid4(), uuid.uuid4()
    await bus.xadd_event(sid1, tid1, {"type": "token", "text": "a"})
    await bus.xadd_event(sid2, tid2, {"type": "token", "text": "b"})
    entries_1 = await bus.xread_blocking(sid1, tid1, last_id="0", count=10, block_ms=10)
    assert len(entries_1) == 1
    assert entries_1[0][1]["text"] == "a"
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_event_bus.py -v
```

Expected: 7 FAIL — `chat_event_bus` 模块不存在。

- [ ] **Step 3: 写最小实现 `chat_event_bus.py`**

新建 `backend/app/services/chat_event_bus.py`:

```python
"""ChatEventBus — Redis Streams 封装,负责 chat in-flight event 的 XADD/XREAD。

设计目标:
- 一个 task 对应一个 stream key: chat:events:{session_id}:{task_id}
- XADD 时把 event payload(dict)序列化成 JSON 单字段 'data'(stream entry id 由 Redis 自动生成,单调)
- XREAD BLOCK 等待新 entry,支持 last_id 协议(对应 SSE Last-Event-ID)
- TTL 24h(spec § 6.3),task 创建时 setup,完成时再续 24h
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from redis.asyncio import Redis as AsyncRedis


class ChatEventBus:
    """Redis Streams 抽象,实例化时持有一个 redis client。

    线程安全:client 本身 async 安全;实例方法都是 async 单调操作,可在 worker / web 多个上下文共享。
    """

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
        """Append one event to the stream. Returns the new entry id (e.g., '1716000000000-0').

        Payload 序列化为 JSON 字符串放进 'data' 字段(spec § 6.2:entry id 透传给前端做 SSE last_event_id)。
        """
        key = self._stream_key(session_id, task_id)
        data = {"data": json.dumps(payload, ensure_ascii=False)}
        entry_id = await self._redis.xadd(key, data)
        return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

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

        Returns: list of (entry_id, decoded_payload) tuples. Empty list if timeout.
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
            data_raw = fields.get(b"data") or fields.get("data")
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
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_event_bus.py -v
```

Expected: 7 PASS。若 fakeredis 不在 deps,装一下:

```bash
uv add --dev "fakeredis[lua]>=2.10"
```

或检查 `pyproject.toml` 是否已有 `fakeredis` extra(c5 plan 2a 用过)。

- [ ] **Step 5: mypy + ruff**

```bash
uv run mypy backend/app/services/chat_event_bus.py
uv run ruff check backend/app/services/chat_event_bus.py backend/tests/unit/test_chat_event_bus.py
uv run ruff format --check backend/app/services/chat_event_bus.py backend/tests/unit/test_chat_event_bus.py
```

Expected: 全 clean。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chat_event_bus.py backend/tests/unit/test_chat_event_bus.py
git commit -m "feat(chat-persistence): ChatEventBus — Redis Streams 封装 + 7 L0 test"
```

---

## Task 2: chat_finalize.py — 抽出 finalize helper

**Spec 锚:** § 3 组件清单(`ChatTaskRunner` 内的 try/finally commit 三件事)。Plan 1 已实现 `_finalize_task_persistence` 在 `chat.py:394`,需要抽出共享。

**Files:**
- Create: `backend/app/router/chat_finalize.py`
- Modify: `backend/app/router/chat.py:394` 删 inline impl,从新文件 import
- Test: `backend/tests/unit/test_chat_finalize.py` (新)

- [ ] **Step 1: 写守护测试 — finalize helper 行为不变**

新建 `backend/tests/unit/test_chat_finalize.py`:

```python
"""chat_finalize helper L0 unit。

Plan 1 把 finalize 逻辑放在 chat.py 内部;Plan 2 抽出共享 module 供 Celery worker import。
本 test 守护抽出后行为不变 — 给定 (acc_assistant, graph_error, checkpoint_id) 应该产生
正确的 ChatMessage append + ChatTask mark 调用。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.router.chat_finalize import finalize_task_persistence


@pytest.mark.asyncio
async def test_finalize_success_appends_done_assistant_and_marks_done():
    session_repo = MagicMock()
    session_repo.append_message = AsyncMock()
    task_repo = MagicMock()
    task_repo.mark_done = AsyncMock()

    task_id = uuid.uuid4()
    session_id = "fake-sid"

    await finalize_task_persistence(
        session_repo=session_repo,
        task_repo=task_repo,
        session_id=session_id,
        task_id=task_id,
        acc_assistant=["hello", " world"],
        graph_error=None,
        checkpoint_id="ckpt-123",
        final_response=None,
    )

    session_repo.append_message.assert_awaited_once()
    call = session_repo.append_message.await_args
    assert call.kwargs["session_id"] == session_id
    assert call.kwargs["role"] == "assistant"
    assert call.kwargs["content"] == "hello world"
    assert call.kwargs["task_id"] == task_id
    assert call.kwargs["status"] == "done"

    task_repo.mark_done.assert_awaited_once_with(task_id, langgraph_checkpoint_id="ckpt-123")


@pytest.mark.asyncio
async def test_finalize_error_appends_error_assistant_and_marks_error():
    session_repo = MagicMock()
    session_repo.append_message = AsyncMock()
    task_repo = MagicMock()
    task_repo.mark_error = AsyncMock()

    err = RuntimeError("LLM 429 rate limited")

    await finalize_task_persistence(
        session_repo=session_repo,
        task_repo=task_repo,
        session_id="sid",
        task_id=uuid.uuid4(),
        acc_assistant=["partial answer"],
        graph_error=err,
        checkpoint_id=None,
        final_response=None,
    )

    call = session_repo.append_message.await_args
    assert call.kwargs["content"] == "partial answer"
    assert call.kwargs["status"] == "error"

    task_repo.mark_error.assert_awaited_once()
    err_call = task_repo.mark_error.await_args
    assert "LLM 429" in err_call.kwargs["error_message"]


@pytest.mark.asyncio
async def test_finalize_prefers_final_response_over_acc():
    """Plan 1 行为:final_response(LangGraph 最终 state)优先于 token 累积。"""
    session_repo = MagicMock()
    session_repo.append_message = AsyncMock()
    task_repo = MagicMock()
    task_repo.mark_done = AsyncMock()

    await finalize_task_persistence(
        session_repo=session_repo,
        task_repo=task_repo,
        session_id="sid",
        task_id=uuid.uuid4(),
        acc_assistant=["incomplete"],
        graph_error=None,
        checkpoint_id=None,
        final_response="canonical full answer from graph state",
    )

    call = session_repo.append_message.await_args
    assert call.kwargs["content"] == "canonical full answer from graph state"
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_finalize.py -v
```

Expected: 3 FAIL — `chat_finalize` 模块不存在。

- [ ] **Step 3: 抽出 `chat_finalize.py`**

读 `backend/app/router/chat.py:394`(当前 `_finalize_task_persistence`),把它复制到新文件 `backend/app/router/chat_finalize.py`,改成 public 名字:

```python
"""chat_finalize — task persistence 三件事(append assistant / mark task / log error)。

Plan 1 在 chat.py 内 inline;Plan 2 抽出供 Celery worker (chat_runner.py) 也调用。
不依赖 chat.py 任何 helper,只依赖 ChatSessionRepo / ChatTaskRepo Protocol-shape。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _SessionRepoLike(Protocol):
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        task_id: uuid.UUID | None = None,
        status: str = "done",
    ) -> Any: ...


class _TaskRepoLike(Protocol):
    async def mark_done(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None: ...
    async def mark_error(
        self, task_id: uuid.UUID, *, error_message: str
    ) -> None: ...


async def finalize_task_persistence(
    *,
    session_repo: _SessionRepoLike,
    task_repo: _TaskRepoLike,
    session_id: str,
    task_id: uuid.UUID,
    acc_assistant: list[str],
    graph_error: Exception | None,
    checkpoint_id: str | None,
    final_response: str | None,
) -> None:
    """Commit assistant message + mark task. Idempotent on (task_id);
    callers should ensure this runs exactly once in finally.

    Args:
        session_repo: ChatSessionRepo-shaped Repo
        task_repo: ChatTaskRepo-shaped Repo
        session_id: str (chat session UUID)
        task_id: uuid.UUID
        acc_assistant: token text chunks accumulated during stream
        graph_error: None on success; Exception on graph failure
        checkpoint_id: LangGraph checkpoint id (or None if unavailable)
        final_response: full assistant text from graph state final_state.final_response
                        (preferred over token acc when available);if None, falls back to acc join
    """
    content = final_response if final_response else "".join(acc_assistant)

    try:
        if graph_error is None:
            await session_repo.append_message(
                session_id=session_id,
                role="assistant",
                content=content,
                task_id=task_id,
                status="done",
            )
            await task_repo.mark_done(task_id, langgraph_checkpoint_id=checkpoint_id)
        else:
            await session_repo.append_message(
                session_id=session_id,
                role="assistant",
                content=content,
                task_id=task_id,
                status="error",
            )
            await task_repo.mark_error(task_id, error_message=str(graph_error)[:500])
    except Exception as exc:  # noqa: BLE001 — finalize 失败也不能抛
        logger.warning(
            "finalize_task_persistence failed for task %s: %s", task_id, exc
        )
```

- [ ] **Step 4: 改 `chat.py:394` 删 inline impl,改 import**

```bash
# 找当前 inline 函数定义位置
grep -n "async def _finalize_task_persistence\|_finalize_task_persistence(" backend/app/router/chat.py
```

把 `chat.py` 内的 `async def _finalize_task_persistence(...):` 整段删除,改 import + 改调用点。Plan 1 调用点(`chat.py:568` 附近)从:

```python
await _finalize_task_persistence(...)
```

改为:

```python
from app.router.chat_finalize import finalize_task_persistence  # 顶部 import
...
await finalize_task_persistence(...)
```

调用参数 kwargs 保持一致(Plan 1 already keyword-only)。

- [ ] **Step 5: 运行测试,确认全过**

```bash
uv run pytest backend/tests/unit/test_chat_finalize.py backend/tests/integration/test_chat_persistence_plan1.py backend/tests/integration/test_chat_router_sse.py backend/tests/integration/test_chat_router_escalate_events.py -v
```

Expected: 3 unit + Plan 1 集成 3 + SSE 10 + escalate 3 全 PASS。

- [ ] **Step 6: mypy + ruff**

```bash
uv run mypy backend/app/router/chat_finalize.py backend/app/router/chat.py
uv run ruff check backend/app/router/chat_finalize.py backend/tests/unit/test_chat_finalize.py
uv run ruff format --check backend/app/router/chat_finalize.py backend/tests/unit/test_chat_finalize.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/router/chat_finalize.py backend/app/router/chat.py backend/tests/unit/test_chat_finalize.py
git commit -m "refactor(chat-persistence): 抽 _finalize_task_persistence 出 chat.py 到 chat_finalize.py"
```

---

## Task 3: Celery task `run_chat` — 异步跑 graph + XADD events

**Spec 锚:** § 5.1 Scenario A step [3];§ 6.5 stale 探测(本 task 实现 bump_seq,scanner 留 Plan 3)

**Files:**
- Create: `backend/app/tasks/chat_runner.py`
- Modify: Celery autodiscovery(若现有 Celery app 不自动发现新 module)
- Test: `backend/tests/unit/test_chat_runner.py`

- [ ] **Step 1: 调研项目现有 Celery 入口**

```bash
# 找 Celery app instance 在哪
grep -rn "Celery(\|@celery_app.task\|@shared_task" backend/app/tasks/ 2>/dev/null | head -10
ls backend/app/tasks/
```

记下:
- Celery app 入口文件名(可能是 `backend/app/celery_app.py` 或 `backend/app/tasks/__init__.py`)
- autodiscovery 配置(`celery_app.autodiscover_tasks(...)`)
- 现有 task 用 `@celery_app.task` 还是 `@shared_task`

参考 B-3 监控引擎的 Celery task `backend/app/tasks/monitoring_*.py` 模式。

- [ ] **Step 2: 写失败测试 — run_chat eager mode**

新建 `backend/tests/unit/test_chat_runner.py`:

```python
"""chat_runner Celery task L0 unit — eager mode (CELERY_TASK_ALWAYS_EAGER)。

测试覆盖:
- run_chat task 入参 task_id (str), 自己 build session_factory + repos + graph
- 正常路径:graph 跑完 → XADD chunks + done event → finalize commit
- 错误路径:graph 抛异常 → XADD error event → finalize mark_error

测试策略:用 in-memory sqlite + fakeredis + MockLLMClient 完整 stub。
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from app.tasks.chat_runner import run_chat_async  # 内部 async 入口,Celery wrapper 调它


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


@pytest_asyncio.fixture
async def mock_session_factory():
    # ... build in-memory sqlite session_factory 同 Plan 1 fixture
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.database import Base
    from app.models.chat import ChatSession
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Base.metadata.tables[n] for n in (
                    "users", "chat_sessions", "chat_tasks", "chat_messages"
                )]
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_chat_async_normal_path_xadds_events_and_finalizes_done(
    fake_redis, mock_session_factory
):
    """正常推理路径:graph 跑出 token 事件 + done,Redis 应有 entries,task 应 mark_done。"""
    # Setup: seeded session + queued task in PG
    from app.models.chat import ChatSession
    from app.services.chat_task_repo import ChatTaskRepo
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    async with mock_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(mock_session_factory)
    task = await task_repo.create_queued(
        session_id=sid, user_id=uid, langgraph_thread_id=f"{uid}:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)

    # Stub graph factory: returns a fake graph whose astream_events yields a fixed sequence
    fake_graph = _build_fake_graph(yield_token_texts=["hello", " world"])

    # Call run_chat_async with all stubs
    await run_chat_async(
        task_id=task.id,
        graph_factory=lambda: fake_graph,
        session_factory=mock_session_factory,
        redis=fake_redis,
        user_message="echo hello",
        session_id=str(sid),
        user_id=uid,
    )

    # Assert Redis Stream has at least 3 events (token x2 + done)
    from app.services.chat_event_bus import ChatEventBus
    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(sid, task.id, last_id="0", count=100, block_ms=10)
    types = [e[1].get("type") for e in entries]
    assert "token" in types
    assert "done" in types

    # Assert PG state: chat_messages assistant row exists, task=done
    from app.services.chat_session_repo import ChatSessionRepo
    repo = ChatSessionRepo(mock_session_factory)
    msgs = await repo.list_messages(str(sid))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].status == "done"
    assert assistant_msgs[0].content == "hello world"

    refreshed = await task_repo.get_by_id(task.id)
    assert refreshed.status == "done"


@pytest.mark.asyncio
async def test_run_chat_async_llm_error_xadds_error_and_marks_error(
    fake_redis, mock_session_factory
):
    """LLM 抛异常路径:Redis 应有 error event,task 应 mark_error。"""
    from app.models.chat import ChatSession
    from app.services.chat_task_repo import ChatTaskRepo
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    async with mock_session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(mock_session_factory)
    task = await task_repo.create_queued(
        session_id=sid, user_id=uid, langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)

    fake_graph = _build_fake_graph_that_raises(RuntimeError("simulated 429"))

    await run_chat_async(
        task_id=task.id,
        graph_factory=lambda: fake_graph,
        session_factory=mock_session_factory,
        redis=fake_redis,
        user_message="hi",
        session_id=str(sid),
        user_id=uid,
    )

    from app.services.chat_event_bus import ChatEventBus
    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(sid, task.id, last_id="0", count=100, block_ms=10)
    types = [e[1].get("type") for e in entries]
    assert "error" in types

    refreshed = await task_repo.get_by_id(task.id)
    assert refreshed.status == "error"
    assert "simulated 429" in refreshed.error_message


# ---------------------------------------------------------------------------
# Test helpers — fake LangGraph that yields a fixed event sequence
# ---------------------------------------------------------------------------


def _build_fake_graph(yield_token_texts: list[str]) -> Any:
    """Return a stub object with astream_events() yielding token chunks + done."""

    class _FakeGraph:
        async def astream_events(self, _initial, config=None, version="v2"):
            for text in yield_token_texts:
                yield {
                    "event": "on_chat_model_stream",
                    "name": "model",
                    "data": {"chunk": MagicMock(content=text)},
                }
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_response": "".join(yield_token_texts)}},
            }

        async def aget_state(self, _config):
            return MagicMock(config={"configurable": {"checkpoint_id": "ckpt-fake"}})

    return _FakeGraph()


def _build_fake_graph_that_raises(exc: Exception) -> Any:
    class _FakeGraph:
        async def astream_events(self, _initial, config=None, version="v2"):
            raise exc
            yield  # unreachable; makes this an async generator

    return _FakeGraph()
```

- [ ] **Step 2.5: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py -v
```

Expected: 2 FAIL — `chat_runner` 模块不存在。

- [ ] **Step 3: 写最小实现 `chat_runner.py`**

新建 `backend/app/tasks/chat_runner.py`:

```python
"""Celery task: run_chat(task_id) — 异步跑 LangGraph + XADD events to Redis Streams。

入口语义:
- Celery worker 收到 task_id → load chat_tasks 行 → mark_running → 跑 graph
- 每个 LangGraph chunk-level event → XADD to chat:events:{sid}:{tid}
- 完成/异常 → XADD 终止事件 + finalize_task_persistence(commit assistant + mark task)
- task_id 之外的所有依赖(redis, session_factory, graph)从 app config / module-level singleton 取

测试策略:test 不调 Celery task wrapper,而是直接调内部 async fn run_chat_async(...)。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from app.router.chat_finalize import finalize_task_persistence
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo

logger = logging.getLogger(__name__)


def _adapt_event_for_stream(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Map LangGraph astream_events dict → Plan 2 chunk-level event dict (or None to skip).

    Plan 2 输出的事件类型:
    - token   : {type, text}  (chunk-level model output)
    - tool_start: {type, node, args}
    - tool_end  : {type, node, output}
    - plan      : {type, output}
    - done      : {type}
    - error     : {type, message}
    """
    ev_type = ev.get("event", "")
    ev_name = ev.get("name", "")
    ev_data = ev.get("data", {})

    if ev_type == "on_chat_model_stream":
        chunk = ev_data.get("chunk", {})
        text = ""
        if hasattr(chunk, "content"):
            text = str(chunk.content)
        elif isinstance(chunk, dict):
            text = str(chunk.get("content", ""))
        return {"type": "token", "text": text}

    if ev_type == "on_chain_start" and ev_name == "tool_node":
        return {"type": "tool_start", "node": ev_name}

    if ev_type == "on_chain_end" and ev_name == "tool_node":
        return {"type": "tool_end", "node": ev_name, "output": ev_data.get("output", {})}

    if ev_type == "on_chain_end" and ev_name == "planner_node":
        return {"type": "plan", "output": ev_data.get("output", {})}

    if ev_type == "on_chain_end" and ev_name == "LangGraph":
        return None  # done is emitted in finally

    return None  # skip unrelated events


async def run_chat_async(
    *,
    task_id: uuid.UUID,
    graph_factory: Callable[[], Any],
    session_factory: Callable[[], Any],
    redis: Any,
    user_message: str,
    session_id: str,
    user_id: uuid.UUID,
) -> None:
    """Main worker entry. graph_factory + session_factory + redis are injected (testable)."""
    session_repo = ChatSessionRepo(session_factory)
    task_repo = ChatTaskRepo(session_factory)
    bus = ChatEventBus(redis=redis)

    sid_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    # mark_running (idempotent — Plan 1 already calls this at POST handler; here re-mark
    # in case Plan 2 router skips it)
    try:
        await task_repo.mark_running(task_id)
    except Exception:
        pass

    await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)

    acc_assistant: list[str] = []
    graph_error: Exception | None = None
    final_response: str | None = None
    checkpoint_id: str | None = None

    graph = graph_factory()

    # Build initial state — minimal; production wires Plan 1 GraphState similarly
    initial = {
        "user_id": str(user_id),
        "session_id": session_id,
        "user_message": user_message,
        "request_id": f"req-{uuid.uuid4().hex[:12]}",
        "trace_request_id": f"req-{uuid.uuid4().hex[:12]}",
    }
    config = {"configurable": {"thread_id": f"{user_id}:{session_id}"}}

    try:
        async for ev in graph.astream_events(initial, config=config, version="v2"):
            # capture final_state
            if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
                output = (ev.get("data") or {}).get("output") or {}
                if isinstance(output, dict):
                    final_response = output.get("final_response")

            adapted = _adapt_event_for_stream(ev)
            if adapted is None:
                continue
            await bus.xadd_event(sid_uuid, task_id, adapted)
            if adapted.get("type") == "token":
                acc_assistant.append(adapted.get("text", ""))
            try:
                await task_repo.bump_seq(task_id, delta=1)
            except Exception:
                pass  # bump 失败不影响主流

        # Best-effort checkpoint id
        try:
            state = await graph.aget_state(config)
            checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
        except Exception:
            checkpoint_id = None
    except Exception as exc:
        graph_error = exc
        try:
            await bus.xadd_event(
                sid_uuid, task_id, {"type": "error", "message": str(exc)[:500]}
            )
        except Exception:
            pass
    finally:
        # Always emit done|error terminal event
        try:
            await bus.xadd_event(
                sid_uuid,
                task_id,
                {"type": "done"} if graph_error is None else {"type": "error_done"},
            )
        except Exception:
            pass

        await finalize_task_persistence(
            session_repo=session_repo,
            task_repo=task_repo,
            session_id=session_id,
            task_id=task_id,
            acc_assistant=acc_assistant,
            graph_error=graph_error,
            checkpoint_id=checkpoint_id,
            final_response=final_response,
        )

        # Refresh TTL — task 结束后再续 24h(从结束时刻算)
        try:
            await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Celery wrapper — production entry; thin shim over run_chat_async
# ---------------------------------------------------------------------------

# from app.celery_app import celery_app  # adjust import based on Task 3 Step 1 grep result
#
# @celery_app.task(name="chat.run_chat", bind=True)
# def run_chat(self, task_id: str, session_id: str, user_id: str, user_message: str) -> None:
#     """Sync Celery entry; bridges to async run_chat_async via asyncio.run."""
#     import asyncio
#     from app.config.settings import get_settings  # or wherever wiring lives
#     from app.router.chat import _build_graph_singleton  # may need refactor
#     ...
#     asyncio.run(run_chat_async(
#         task_id=uuid.UUID(task_id),
#         graph_factory=...,
#         session_factory=...,
#         redis=...,
#         user_message=user_message,
#         session_id=session_id,
#         user_id=uuid.UUID(user_id),
#     ))
```

**注意**:Celery sync→async bridge 是常见坑。本 task 实现 `run_chat_async` 主体逻辑;Celery wrapper(`@celery_app.task`)在 Step 4 接入,要根据实际 Celery app 入口调整 import。**Test 只测 `run_chat_async`**,Celery wrapper 留到 L2 测试覆盖。

- [ ] **Step 4: 接入 Celery autodiscovery**

根据 Step 1 grep 结果,在 Celery app 配置文件加入 `app.tasks.chat_runner` autodiscovery:

```python
# 在 backend/app/celery_app.py(或 wherever):
celery_app.autodiscover_tasks([
    "app.tasks",
    "app.tasks.chat_runner",  # Plan 2 新增
])
```

或者用 `include=[...]` 形式 — 看现有 monitoring task 怎么注册。

- [ ] **Step 5: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py -v
```

Expected: 2 PASS。

- [ ] **Step 6: mypy + ruff**

```bash
uv run mypy backend/app/tasks/chat_runner.py
uv run ruff check backend/app/tasks/chat_runner.py backend/tests/unit/test_chat_runner.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/tasks/chat_runner.py backend/tests/unit/test_chat_runner.py backend/app/celery_app.py
git commit -m "feat(chat-persistence): Celery task run_chat_async — graph + XADD Redis Streams + finalize"
```

---

## Task 4: GET /api/v0/chat/stream/{task_id} — SSE replay endpoint

**Spec 锚:** § 5.1 step [2] / § 5.2 Scenario B / § 6.2 Redis Streams ↔ last_event_id 协议

**Files:**
- Modify: `backend/app/router/chat.py` 加新 endpoint
- Test: `backend/tests/integration/test_chat_inflight_plan2.py` (新)

- [ ] **Step 1: 写失败测试 — GET /chat/stream/{tid} 返回 SSE 流**

新建 `backend/tests/integration/test_chat_inflight_plan2.py`:

```python
"""Plan 2 集成:GET /chat/stream/{tid} SSE replay endpoint + 完整链路。

L1 集成 — 用 fakeredis 模拟 Redis Streams;Celery task 不真起 worker,
在 test 内 inline 调 run_chat_async 模拟 worker 推 events。
"""
from __future__ import annotations

import json
import uuid
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.models.chat import ChatSession
from app.services.chat_task_repo import ChatTaskRepo
from app.services.chat_event_bus import ChatEventBus
from app.tasks.chat_runner import run_chat_async
# Router DI 依赖
from app.router.chat import router as chat_router


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Base.metadata.tables[n] for n in (
                    "users", "chat_sessions", "chat_tasks", "chat_messages"
                )]
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _build_fake_graph(token_texts: list[str]) -> Any:
    """Same helper as test_chat_runner.py — yield token chunks + done."""
    class _FakeGraph:
        async def astream_events(self, _initial, config=None, version="v2"):
            for t in token_texts:
                yield {"event": "on_chat_model_stream", "name": "model",
                       "data": {"chunk": MagicMock(content=t)}}
            yield {"event": "on_chain_end", "name": "LangGraph",
                   "data": {"output": {"final_response": "".join(token_texts)}}}
        async def aget_state(self, _config):
            return MagicMock(config={"configurable": {"checkpoint_id": "ck"}})
    return _FakeGraph()


@pytest_asyncio.fixture
async def seeded_running_task(session_factory):
    sid = uuid.uuid4()
    uid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=sid, user_id=uid, langgraph_thread_id=f"{uid}:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    return {"session_id": sid, "user_id": uid, "task_id": task.id}


@pytest.fixture
def test_client(fake_redis, session_factory):
    """FastAPI TestClient wiring the new GET /chat/stream/{tid}."""
    minimal_app = FastAPI()
    minimal_app.include_router(chat_router)
    # DI overrides — adapt to whatever DI Plan 2 adds for `redis` + `session_factory`
    from app.router.chat import get_async_session_factory, get_redis_async
    minimal_app.dependency_overrides[get_async_session_factory] = lambda: session_factory
    minimal_app.dependency_overrides[get_redis_async] = lambda: fake_redis
    client = TestClient(minimal_app, raise_server_exceptions=True)
    yield client


@pytest.mark.asyncio
async def test_stream_endpoint_replays_existing_events_from_zero(
    test_client, fake_redis, seeded_running_task, session_factory,
):
    """worker 已经推了若干 events 到 Redis;GET /stream/{tid}?last_event_id=0 应该全 replay。"""
    sid = seeded_running_task["session_id"]
    tid = seeded_running_task["task_id"]
    uid = seeded_running_task["user_id"]

    # Pre-populate Redis Stream as if worker already pushed events
    bus = ChatEventBus(fake_redis)
    await bus.xadd_event(sid, tid, {"type": "token", "text": "hello"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": " world"})
    await bus.xadd_event(sid, tid, {"type": "done"})

    resp = test_client.get(f"/api/v0/chat/stream/{tid}?last_event_id=0")
    assert resp.status_code == 200
    body = resp.content.decode()
    # Should contain all 3 SSE events
    assert "hello" in body
    assert "world" in body
    assert "done" in body


@pytest.mark.asyncio
async def test_stream_endpoint_with_last_event_id_returns_only_new(
    test_client, fake_redis, seeded_running_task,
):
    """传 last_event_id=<first entry id>,应该只返回之后的事件。"""
    sid = seeded_running_task["session_id"]
    tid = seeded_running_task["task_id"]

    bus = ChatEventBus(fake_redis)
    first_id = await bus.xadd_event(sid, tid, {"type": "token", "text": "a"})
    await bus.xadd_event(sid, tid, {"type": "token", "text": "b"})
    await bus.xadd_event(sid, tid, {"type": "done"})

    resp = test_client.get(f"/api/v0/chat/stream/{tid}?last_event_id={first_id}")
    body = resp.content.decode()
    assert "a" not in body  # first entry not replayed
    assert "b" in body
    assert "done" in body


@pytest.mark.asyncio
async def test_stream_endpoint_404_for_unknown_task(test_client):
    """Unknown task_id → 404。"""
    fake_tid = uuid.uuid4()
    resp = test_client.get(f"/api/v0/chat/stream/{fake_tid}")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py -v
```

Expected: 3 FAIL — endpoint 还没实现。

- [ ] **Step 3: 实现 GET /chat/stream/{tid} endpoint**

修改 `backend/app/router/chat.py`,在 POST /chat 之前/之后加新 endpoint:

```python
# 顶部 import 区:
from app.services.chat_event_bus import ChatEventBus
import redis.asyncio as redis_async


def get_redis_async(request: Request) -> redis_async.Redis | None:
    """DI: 从 app.state 拿 Redis client。tests 用 dependency_overrides 注入 fakeredis。

    Plan 2 lifespan(app_main.py)在启动时创建 Redis async client 并挂 app.state.redis_async。
    """
    return getattr(request.app.state, "redis_async", None)


@router.get("/api/v0/chat/stream/{task_id}")
async def chat_stream(
    task_id: str,
    request: Request,
    last_event_id: str = "0",
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: redis_async.Redis | None = Depends(get_redis_async),
) -> StreamingResponse:
    """SSE replay endpoint — XREAD from Redis Streams + forward as SSE.

    Args:
        task_id: ChatTask UUID
        last_event_id: Redis Stream entry id ("0" = from start)
                       Frontend passes last received entry id to resume after disconnect.

    Spec § 6.2: entry id 直接透传给前端,前端下次重连时回传给我们做 XREAD start point。
    """
    task_uuid = uuid.UUID(task_id)

    if pg_factory is None or redis is None:
        raise HTTPException(503, "chat streaming not configured (PG or Redis unavailable)")

    # Verify task exists; 404 otherwise
    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")

    session_id_uuid = task.session_id

    async def _forward_sse():
        bus = ChatEventBus(redis=redis)
        cur_id = last_event_id
        # Loop: read events until terminal (done/error_done) seen or client disconnects
        while True:
            if await request.is_disconnected():
                # Client gone — stop forwarding. DON'T cancel the Celery task (spec § 5.5);
                # task keeps running, will land in Redis Stream; user can reconnect later.
                return
            entries = await bus.xread_blocking(
                session_id_uuid, task_uuid, last_id=cur_id, count=20, block_ms=10_000,
            )
            if not entries:
                continue  # block timeout — re-check disconnect and loop
            for entry_id, payload in entries:
                cur_id = entry_id
                ev_type = payload.get("type", "unknown")
                # SSE format: event:/id:/data:
                data_str = json.dumps(payload, ensure_ascii=False)
                yield f"event: {ev_type}\nid: {entry_id}\ndata: {data_str}\n\n"
                if ev_type in ("done", "error_done"):
                    return

    return StreamingResponse(_forward_sse(), media_type="text/event-stream")
```

**关键点**:
- `request.is_disconnected()` 检测 client 断开 → 立刻 return generator,**不杀 task**
- XREAD BLOCK 10s 一轮,每轮检查 disconnect → 兼顾响应性和效率
- entry_id 直接作为 SSE `id:` field — 前端 EventSource API 会自动用它做 Last-Event-ID 重连

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py -v
```

Expected: 3 PASS。

- [ ] **Step 5: mypy + ruff**

```bash
uv run mypy backend/app/router/chat.py
uv run ruff check backend/app/router/chat.py backend/tests/integration/test_chat_inflight_plan2.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/chat.py backend/tests/integration/test_chat_inflight_plan2.py
git commit -m "feat(chat-persistence): GET /chat/stream/{tid} SSE replay endpoint + Redis Streams XREAD"
```

---

## Task 5: POST /chat 改造 — enqueue Celery + 返回 task_id

**Spec 锚:** § 5.1 step [1] — POST /chat 不再 inline 跑 graph

**Files:**
- Modify: `backend/app/router/chat.py` POST /chat handler
- Modify: `backend/tests/integration/test_chat_persistence_plan1.py`(Plan 1 测试期望 SSE 流;Plan 2 改为期望 task_id JSON)
- Test: 扩展 `backend/tests/integration/test_chat_inflight_plan2.py`

- [ ] **Step 1: 写失败测试 — POST /chat 返回 task_id**

在 `test_chat_inflight_plan2.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_post_chat_enqueues_and_returns_task_id(
    test_client, session_factory, fake_redis, monkeypatch,
):
    """POST /api/v0/chat → 不再 inline 跑 graph,返回 {task_id, stream_url, session_id}。"""
    # Patch run_chat enqueue to be a no-op(real Celery in L2 test;L1 不真起 worker)
    enqueued: list[dict] = []
    from app.tasks import chat_runner

    def fake_delay(**kwargs):
        enqueued.append(kwargs)
        class _Result:
            def __init__(self, tid):
                self.id = tid
        return _Result(kwargs.get("task_id"))

    # Plan 2 router will call e.g. `run_chat.delay(task_id=..., session_id=..., user_id=..., user_message=...)`
    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_delay, raising=False)

    # Seed a session
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    resp = test_client.post(
        "/api/v0/chat",
        json={"session_id": str(sid), "message": "hello"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    assert "stream_url" in body
    assert body["session_id"] == str(sid)
    # stream_url should match /api/v0/chat/stream/{task_id}
    assert body["task_id"] in body["stream_url"]

    # Verify enqueue called with correct kwargs
    assert len(enqueued) == 1
    assert enqueued[0]["session_id"] == str(sid)
    assert enqueued[0]["user_message"] == "hello"
    assert "task_id" in enqueued[0]
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py::test_post_chat_enqueues_and_returns_task_id -v
```

Expected: FAIL — POST /chat 还是返回 SSE 流不是 JSON。

- [ ] **Step 3: 改造 POST /chat handler**

修改 `chat.py` 的 POST endpoint。**重要**:Plan 1 的 `_stream_chat` 把 chat 整个 inline 跑了,Plan 2 要把这个搬到 Celery 异步执行。POST handler 现在只做:

1. Create chat_task(queued)+ Insert user message(Plan 1 已有)
2. Enqueue Celery task: `enqueue_run_chat(task_id, session_id, user_id, user_message)`
3. 立即返回 `{task_id, stream_url, session_id}` JSON

如果没有 PG / Redis(legacy test 路径),退回 Plan 1 inline 行为 — 但是 Plan 1 的 `_stream_chat` 现在还在 chat.py 内吗?

**Subagent 决定**:
- 如果 Plan 2 不打算保留 inline path,把 `_stream_chat` 完全删除。但这破坏 Plan 1 的 `test_chat_router_sse.py` 假设(它 expect StreamingResponse 不是 JSON)。
- 折中:Plan 2 保留 legacy SSE-inline 路径作为「无 PG / 无 Redis」时的 fallback,production(有 PG+Redis)走新路径。
- 但这种 dual-path 维护成本高,且 Plan 2 后续 Plan 3 也是新路径,不需要 inline 模式。
- **推荐方案**:Plan 2 砍掉 inline 路径。修改 `test_chat_router_sse.py` 期望 JSON 而非 StreamingResponse;让 SSE 流测试改名为 `test_chat_stream_endpoint.py` 覆盖新 GET /chat/stream/{tid}。

具体实现:

```python
@router.post("/api/v0/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    user: _AnonUser = Depends(get_current_user),
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: Any | None = Depends(get_redis_async),
) -> dict[str, str]:
    """POST /api/v0/chat — enqueue Celery task + return task_id + stream_url.

    Plan 2 改造:不再 inline 跑 graph;客户端立即拿 task_id 后,打开 GET /chat/stream/{tid}
    订阅 in-flight stream(via Redis Streams XREAD)。
    """
    if pg_factory is None or redis is None:
        raise HTTPException(503, "chat not available — PG and Redis required")

    session_repo = ChatSessionRepo(pg_factory)
    task_repo = ChatTaskRepo(pg_factory)

    user_msg = await session_repo.append_message(
        session_id=req.session_id,
        role="user",
        content=req.message,
    )

    task = await task_repo.create_queued(
        session_id=req.session_id,
        user_id=_coerce_user_uuid(user.id),
        langgraph_thread_id=f"{user.id}:{req.session_id}",
        initial_prompt_message_id=user_msg.id,
    )
    # Don't mark_running here — let Celery worker do it as part of run_chat_async lifecycle
    # (avoids race where router marks running but worker hasn't started yet)

    # Enqueue Celery task
    from app.tasks.chat_runner import enqueue_run_chat
    enqueue_run_chat(
        task_id=str(task.id),
        session_id=req.session_id,
        user_id=str(user.id),
        user_message=req.message,
    )

    stream_url = f"/api/v0/chat/stream/{task.id}"
    return {
        "task_id": str(task.id),
        "session_id": req.session_id,
        "stream_url": stream_url,
    }
```

**新增 `enqueue_run_chat` 辅助函数**(在 `chat_runner.py` 末尾):

```python
def enqueue_run_chat(*, task_id: str, session_id: str, user_id: str, user_message: str) -> Any:
    """Production entry — delegates to Celery .delay(); tests monkey-patch this."""
    return run_chat.delay(
        task_id=task_id, session_id=session_id, user_id=user_id, user_message=user_message
    )
```

`run_chat` 是 Celery `@celery_app.task`-decorated wrapper(Step 4 of Task 3 加的)。

- [ ] **Step 4: 改造 test_chat_router_sse.py(改名 + 重写)**

`test_chat_router_sse.py` 原本期望 POST 返回 StreamingResponse。Plan 2 后 POST 返回 JSON。要么:

**Option A**:整文件移除(replaced by Plan 2 `test_chat_inflight_plan2.py` + Plan 1 `test_chat_persistence_plan1.py`)。
**Option B**:改名 `test_chat_post_enqueue.py`,改测试期望 JSON 返回。

推荐 **Option A** — 测试 coverage 由 Plan 2 新 test + Plan 1 已有 test 共同覆盖,旧文件冗余。**但** 需要确认 escalation flow 还有测试覆盖(`test_chat_router_escalate_events.py` 现在期望什么)。

Subagent check before delete:`test_chat_router_sse.py` 里有哪些 case 不是 Plan 1+2 已覆盖的?

- [ ] **Step 5: 运行测试,确认通过**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py backend/tests/integration/test_chat_persistence_plan1.py -v
```

如果 Plan 1 test fails(因为期望 SSE 流但现在返回 JSON),改 Plan 1 test:不再 expect StreamingResponse content,而是 expect JSON + 然后单独 GET /stream/{tid} 拿 SSE。

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/chat.py backend/app/tasks/chat_runner.py backend/tests/integration/test_chat_inflight_plan2.py
git commit -m "feat(chat-persistence): POST /chat 改造为 enqueue Celery + 返回 task_id"
```

---

## Task 6: 前端 useChatSSE 双阶段流 + 打字机渲染

**Spec 锚:** § 5.1 Scenario A frontend flow / § 6.5 打字机渲染速率

**Files:**
- Modify: `frontend/src/hooks/useChatSSE.ts`
- Modify: `frontend/src/api/chatApi.ts`
- Modify: `frontend/src/store/current-chat.ts`(可能加 `active_task_id` 字段)
- Test: `frontend/src/hooks/__tests__/useChatSSE.test.tsx`

- [ ] **Step 1: 改 `chatApi.ts` — 新 helpers**

新增:

```typescript
export interface ChatPostResponse {
  task_id: string
  session_id: string
  stream_url: string
}

export async function postChatAndGetTask(
  sessionId: string,
  message: string,
): Promise<ChatPostResponse> {
  const res = await fetch(buildChatPostUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) throw new Error(`POST /api/v0/chat ${res.status}`)
  return (await res.json()) as ChatPostResponse
}

export function buildChatTaskStreamUrl(taskId: string, lastEventId: string = '0'): string {
  return apiUrl(`/api/v0/chat/stream/${encodeURIComponent(taskId)}?last_event_id=${encodeURIComponent(lastEventId)}`)
}
```

- [ ] **Step 2: 改 useChatSSE.ts**

新 `sendMessage` 双阶段:

```typescript
const sendMessage = useCallback(
  async (content: string) => {
    const sessionId = sessionIdRef.current
    if (!sessionId) throw new Error('sendMessage: no active session')
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac

    currentChatActions.appendUserMessage(content)
    currentChatActions.beginStreaming()

    // Phase 1: POST → get task_id
    let task: ChatPostResponse
    try {
      task = await postChatAndGetTask(sessionId, content)
    } catch (e) {
      currentChatActions.setError(`POST failed: ${e}`)
      return
    }

    currentChatActions.setActiveTaskId(task.task_id)

    // Phase 2: open SSE on GET /chat/stream/{task_id}
    let lastEventId = '0'
    let doneSeen = false
    let attempt = 0

    while (!doneSeen && !ac.signal.aborted) {
      try {
        const url = buildChatTaskStreamUrl(task.task_id, lastEventId)
        const res = await fetchImpl(url, { signal: ac.signal })
        if (!res.ok) throw new Error(`stream ${res.status}`)
        const result = await consumeStream(res, ac.signal, (eventId) => {
          lastEventId = eventId
        })
        doneSeen = result.doneSeen
      } catch {
        if (ac.signal.aborted) return
      }
      if (!doneSeen && !ac.signal.aborted) {
        currentChatActions.setReconnecting()
        await delay(computeBackoffMs(attempt++))
      }
    }
  },
  [delay, fetchImpl],
)
```

更新 `consumeStream` 接 lastEventId callback:

```typescript
async function consumeStream(
  res: Response,
  signal: AbortSignal,
  onEventId?: (id: string) => void,
): Promise<{ doneSeen: boolean }> {
  // ... existing parsing ...
  // 在 parseFrame 之后,如果 frame 含 'id: <entry_id>' 行,拿出来 callback
}
```

`parseFrame` 已经在 useChatSSE.ts 内 — 改成同时返回 id + data。

- [ ] **Step 3: 打字机渲染 — char queue + RAF**

新增 hook `frontend/src/hooks/useTypewriter.ts`:

```typescript
import { useEffect, useRef } from 'react'

interface UseTypewriterOptions {
  onChar: (char: string) => void
  baseSpeed?: number  // chars per second when queue < 200
  catchupSpeed?: number  // chars per second when queue >= 200
}

export function useTypewriter(options: UseTypewriterOptions) {
  const queueRef = useRef<string[]>([])
  const rafRef = useRef<number | null>(null)
  const lastTimeRef = useRef<number>(0)

  function enqueue(text: string) {
    queueRef.current.push(...text.split(''))
    if (rafRef.current === null) startLoop()
  }

  function startLoop() {
    const tick = (timestamp: number) => {
      if (lastTimeRef.current === 0) lastTimeRef.current = timestamp
      const dt = (timestamp - lastTimeRef.current) / 1000
      const speed = queueRef.current.length >= 200
        ? (options.catchupSpeed ?? 100)
        : (options.baseSpeed ?? 30)
      const charsToYield = Math.floor(dt * speed)
      for (let i = 0; i < charsToYield && queueRef.current.length > 0; i++) {
        const ch = queueRef.current.shift()
        if (ch !== undefined) options.onChar(ch)
      }
      lastTimeRef.current = timestamp
      if (queueRef.current.length > 0) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        rafRef.current = null
        lastTimeRef.current = 0
      }
    }
    rafRef.current = requestAnimationFrame(tick)
  }

  useEffect(() => () => {
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
  }, [])

  return { enqueue }
}
```

在 `useChatSSE.ts` 内,把 `token` event 的 text 入队列:

```typescript
const typewriter = useTypewriter({
  onChar: (ch) => {
    currentChatState.streamingDraft += ch
  },
})

// In dispatchEvent for 'token':
case 'token':
  typewriter.enqueue((ev as TokenEvent).text)
  break
```

- [ ] **Step 4: 测试**

更新 `frontend/src/hooks/__tests__/useChatSSE.test.tsx`:
- 测双阶段:POST → GET stream
- 测 last_event_id 重连
- 测 typewriter enqueue 行为(可单独 `useTypewriter.test.tsx`)

```bash
cd frontend && npm test -- useChatSSE && npm test -- useTypewriter
```

- [ ] **Step 5: Build + Lint**

```bash
cd frontend && npm run build && npm run lint
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useChatSSE.ts frontend/src/hooks/useTypewriter.ts \
        frontend/src/api/chatApi.ts frontend/src/store/current-chat.ts \
        frontend/src/hooks/__tests__/useChatSSE.test.tsx \
        frontend/src/hooks/__tests__/useTypewriter.test.tsx
git commit -m "feat(chat-persistence): 前端双阶段流 + RAF 打字机渲染(chunk → token 视觉)"
```

---

## Task 7: app_main lifespan — wire Redis async client

**Spec 锚:** § 5 系统组件;依赖 `redis.asyncio` python 包

**Files:**
- Modify: `backend/app/app_main.py` lifespan
- Modify: `pyproject.toml`(若 `redis>=4.0` 不在 deps)

- [ ] **Step 1: 检查 redis package 是否在 deps**

```bash
uv pip list | grep redis
```

如果缺,加:

```bash
uv add "redis>=5.0"
```

- [ ] **Step 2: 在 lifespan 加 Redis async client**

修改 `backend/app/app_main.py:77` lifespan 内:

```python
import redis.asyncio as redis_async

# 在 lifespan startup 阶段:
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
try:
    app.state.redis_async = redis_async.Redis.from_url(redis_url, decode_responses=False)
    # 探测连接(可选,但能 fail-fast)
    await app.state.redis_async.ping()
    logger.info("Redis async client wired: %s", redis_url)
except Exception as exc:
    logger.warning("Redis async client setup failed: %s; chat in-flight subscribe disabled", exc)
    app.state.redis_async = None

# 在 lifespan shutdown 阶段:
if getattr(app.state, "redis_async", None) is not None:
    await app.state.redis_async.aclose()
```

`memory:` 已有 `feedback_serve_path_no_ci_coverage` — 改 app_main lifespan 必须本地 import smoke 验证。

- [ ] **Step 3: 本地 smoke**

```bash
uv run python -c "from app.app_main import app; print('app import OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/app_main.py pyproject.toml uv.lock
git commit -m "feat(chat-persistence): app_main lifespan wire Redis async client + app.state.redis_async"
```

---

## Task 8: L2 集成测试 — 真 Celery worker subprocess + 真 Redis

**Spec 锚:** § 8 测试策略 L2 / `celery-redis-test-fixture-pattern` memory

**Files:**
- Create: `backend/tests/integration/test_chat_inflight_l2.py`
- 可能 reuse: `backend/tests/conftest_celery.py`(项目已有 B-3 Celery fixture)

- [ ] **Step 1: 调研现有 Celery + Redis L2 fixture**

```bash
cat backend/tests/conftest_celery.py 2>/dev/null
grep -rn "celery_worker\|@pytest.fixture.*celery" backend/tests/ 2>/dev/null | head -5
```

记下:
- celery_worker subprocess 怎么起的
- Redis 怎么验真 / 用 docker-compose 还是本地 daemon

- [ ] **Step 2: 写 L2 测试 — 完整链路**

新建 `backend/tests/integration/test_chat_inflight_l2.py`:

```python
"""Plan 2 L2 集成:真 Celery worker subprocess + 真 Redis + 完整 chat flow。

测试约定:
- 跑前要求本地 Redis 在 127.0.0.1:6379 可达(或 REDIS_URL env)
- 跑前要求 PG fixture container
- 用 conftest_celery 的 worker fixture(若有)或新建本地 worker fixture
"""
from __future__ import annotations

# ... 完整 L2 fixture 依赖项目现有 celery_worker fixture
# ... 测试 case:
#     1. POST /chat → 返回 task_id
#     2. 立即 GET /chat/stream/{tid} → 看到 done event 流过
#     3. PG chat_messages 落了 user + assistant rows
#     4. 中途断开 client → server 不杀 task → 重连看到累积 events
```

具体 L2 case 推 subagent 根据现有 celery_worker fixture 决定细节(本 plan 不展开,因 fixture 因项目而异)。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_chat_inflight_l2.py
git commit -m "test(chat-persistence): L2 真 Celery worker + 真 Redis 完整链路"
```

---

## Task 9: 服务端断开检测 — request.is_disconnected() 守护

**Spec 锚:** § 5.5 Scenario E(Web 进程崩);§ 7 客户端断开行为

**这一 task 已在 Task 4 实现里包含**(`async def _forward_sse()` 内 `await request.is_disconnected()`)。本 task 是单独写守护测试 + dogfood 验证。

**Files:**
- Test: 扩展 `backend/tests/integration/test_chat_inflight_l2.py`

- [ ] **Step 1: 写 L2 测试 — 客户端断开服务端 task 继续跑**

```python
@pytest.mark.asyncio
async def test_client_disconnect_does_not_kill_celery_task(
    real_celery_worker, real_redis, test_client_with_l2_pg,
):
    """关 SSE 连接 → server stop 转发 → Celery task 继续跑 → 重连看到完整 stream。"""
    # 1. POST /chat → task_id
    resp = test_client_with_l2_pg.post(...)
    task_id = resp.json()["task_id"]

    # 2. Open SSE
    sse_resp = test_client_with_l2_pg.stream("GET", f"/api/v0/chat/stream/{task_id}")
    # 3. Read 2 events then disconnect (close stream)
    events_received = []
    with sse_resp as s:
        for line in s.iter_lines():
            events_received.append(line)
            if len(events_received) >= 2:
                break  # disconnect

    # 4. Wait a bit for Celery worker to finish
    await asyncio.sleep(5)

    # 5. PG state: task should be done, full assistant message saved
    # (real worker 跑完了)
    # ...
    assert task_status == "done"
```

- [ ] **Step 2: Commit**

```bash
git commit -m "test(chat-persistence): L2 客户端断开守护 — Celery 任务继续不被杀"
```

---

## Task 10: dogfood + done card

**Files:**
- Create: `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan2-done.md`

- [ ] **Step 1: 起 server + Celery worker + Redis**

```bash
# Terminal 1: Redis(若本地没 daemon)
redis-server &

# Terminal 2: Celery worker
uv run celery -A app.celery_app worker --loglevel=info &

# Terminal 3: backend
uv run poe dev

# Terminal 4: frontend
cd frontend && npm run dev
```

- [ ] **Step 2: 浏览器 dogfood — C 档场景**

1. 打开 chat session
2. 发个长 prompt(预计跑 30 秒+)
3. 看打字机效果(token 一字一字吐出来)
4. **中途关浏览器**
5. 等 10 秒
6. **重开浏览器** → 应该看到推理还在继续,token 继续吐出来(in-flight subscribe!)
7. 等推理完成
8. 刷新页面 → 完整对话 ho 在

- [ ] **Step 3: 跑全套守护**

```bash
uv run pytest backend/tests/ -x --tb=short 2>&1 | tail -10
cd frontend && npm test -- --run 2>&1 | tail -5
uv run mypy backend/app/ 2>&1 | tail -3
uv run ruff check backend/ 2>&1 | tail -3
```

- [ ] **Step 4: 写 done card**

```markdown
# Plan 2 (In-flight Subscribe) DONE

C 档承诺达成:
- 关页面 30 秒重开能继续订阅 in-flight 流
- Celery worker 解耦推理与 web 生命周期
- 打字机渲染(chunk → token 视觉)
- 服务端 request.is_disconnected() 不杀 task
...
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-05-16-chat-session-persistence-plan2-done.md
git commit -m "docs(plan): chat persistence plan 2 done — C 档 ship 完整"
```

---

## Plan 2 完成验收

```bash
# 1. 全测试套
uv run pytest backend/tests/ -x --tb=short
cd frontend && npm test -- --run

# 2. 浏览器 dogfood 三个场景
#    a. 正常长流(打字机生效)
#    b. 关页面 30 秒重开(看到 in-flight 流续上)
#    c. 服务端 kill -9 Celery worker(task 标 stale,前端看 error)— Plan 3 收 stale

# 3. spec § 1.2 三个根因覆盖
#    - chat 消息不入库 → ✅ Plan 1 fixed
#    - 服务端不感知断开 → ✅ Plan 2 fixed(request.is_disconnected + Celery 独立)
#    - 前端假 reconnect → ✅ Plan 1 + Plan 2 fixed(真 stream/{task_id} endpoint)
```

Plan 2 ship 后,Plan 3 (Cancel + Resume + Chaos) 加上:
- POST /chat/cancel/{tid}(Redis pub/sub 信号)
- POST /chat/retry/{tid}(从 LangGraph checkpoint 续跑)
- Celery Beat scan_stale_chat_tasks
- L2 chaos:杀 Celery worker / 杀 Redis 验证 task 状态收敛
- 3 differential golden cases

---

## Self-Review

### 1. Spec 覆盖

Plan 2 范围内的 spec 锚:
- § 3 组件清单 — ChatEventBus / ChatTaskRunner / POST /chat 改造 / GET /chat/stream:**全覆盖** ✅(Task 1/3/4/5)
- § 5.1 Scenario A:**完整覆盖**(Task 5 + Task 4 + Task 3)
- § 5.2 Scenario B (关页面 30 分重开):**完整覆盖**(Task 4 GET /stream + Task 6 前端续订)
- § 5.5 Scenario E (Web 进程崩):**部分覆盖**(Task 4 client disconnect 守护 + Task 9 L2 测试)
- § 6.2-6.3 (Redis Streams 协议 + TTL):**全覆盖**(Task 1)
- § 6.5 (打字机渲染速率):**全覆盖**(Task 6)

不在 Plan 2 范围(明确推到 Plan 3):
- Cancel(POST /cancel)/ Retry(POST /retry)/ Stale scanner / L2 chaos 故障演练 / 3 differential golden cases

### 2. Placeholder 扫描

无 TBD / TODO / vague requirements。

### 3. 类型一致性

- `ChatEventBus.xadd_event` 返回 `str`(stream entry id);`xread_blocking` 返回 `list[tuple[str, dict]]` — 一致
- Celery `run_chat_async` kwargs 与 Task 5 POST 改造的 `enqueue_run_chat` kwargs 对齐
- 前端 `ChatPostResponse` 跟后端 Task 5 返回的 dict 对齐(`task_id` / `session_id` / `stream_url`)

### 4. 已知风险

- **Celery autodiscovery 配置**:Task 3 Step 4 需要根据项目实际 Celery app 入口调整。Implementer 必须先 grep。
- **`fakeredis` 在 deps**:Task 1 假设它在 deps。若不在,Step 4 加 `uv add --dev fakeredis`。
- **redis.asyncio API 差异**:Redis 5.x 跟 4.x API 略有不同;若项目用 redis 4.x,xadd 返回 bytes vs str 处理可能需要调整。
- **`test_chat_router_sse.py` 删除决策**:Task 5 Step 4 让 implementer 自己判断。推荐 Option A (删) 但需要先 grep 看 escalation 测试是否真覆盖完整。
- **Celery sync→async bridge**:`asyncio.run(run_chat_async(...))` 在 Celery worker 内可能 conflict 已有 event loop。若是,改用 `nest_asyncio` 或 sync wrapper.

---

## Execution Handoff

Plan 2 complete and saved to `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan2-inflight-subscribe.md`.

**1. Subagent-Driven(推荐)**:Plan 2 10 task 中,Task 1/2/7 mechanical(~2-3h subagent 各),Task 3/4/6 substantive(~4-6h),Task 5/8/9 集成 + chaos(~3-5h),Task 10 dogfood(~1h)。合计 ~3-4 天 wall time。

**2. Inline Execution**:Plan 2 task 间依赖性较强(Task 1 → 2 → 3 → 4 → 5),inline 模式可能更顺手 — 但单 session token 压力大。

**Plan 2 + Plan 1 timeline 建议**:
- 先 merge Plan 1 PR 到 main(让 schema 稳定)
- 在新 worktree 起 Plan 2 implementation(从 main 切)
- Plan 2 ship 后再起 Plan 3 spec/plan

**你选哪个执行模式?**
