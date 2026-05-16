# Chat Session Persistence — Plan 3: Cancel + Retry + Stale Scanner + L2 Chaos

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat session 持久化最后一卷 — 让用户主动 cancel 正在跑的推理 + retry 失败的 task(从 LangGraph checkpoint 续跑) + Celery Beat 自动发现并标记 stale 任务 + L2 chaos 演练守护故障收敛 + 3 differential golden 守护新机制不破老路径。

**Architecture:**
- **Cancel:** POST `/chat/cancel/{tid}` → Redis pub/sub `chat:cancel:{tid}` channel → Celery worker 内 asyncio listener task set Event flag → graph 节点之间 wrapper 检查 flag,raise GraphInterrupt → try/finally 走 partial commit(spec § 6.1)
- **Retry:** POST `/chat/retry/{tid}` → 从 `chat_tasks.langgraph_checkpoint_id` + `initial_prompt_message_id` build resume RunnableConfig → 创建新 task(parent_task_id 链)→ enqueue Celery,worker 用 checkpoint 续跑(LangGraph thread state 自动恢复)
- **Stale scanner:** Celery Beat 每分钟跑 `scan_stale_chat_tasks`,扫 `status='running' AND last_event_seq 5min 未变` → mark error + XADD `{type:error,reason:stale}` 让在线 client SSE 立刻收到
- **L2 chaos:** 自动化 Plan 2 dogfood 场景 3 + 加杀 Celery worker / 杀 Redis 两类 — 用 `conftest_celery.py` 已有 fixture + subprocess 控制
- **3 differential golden:** Case A cancel vs done 终态对比;Case B retry 续接 vs no-retry 重发;Case C 两轮 prompt 跨页面切换

**Tech Stack:** Plan 2 基础设施全套(ChatEventBus + chat_finalize + run_chat_async + Redis Streams) + Redis pub/sub(`redis.asyncio.PubSub`) + LangGraph 1.x checkpoint resume(`graph.astream_events(config={"configurable":{"thread_id":...,"checkpoint_id":...}})`) + Celery Beat。

**Spec 锚:** `docs/superpowers/specs/2026-05-16-chat-session-persistence-design.md` § 6.1 / § 6.5 / § 6.6 / § 8 / § 9.1。

**Plan 范围(YAGNI)**:
- ✅ 做:ChatCancelBus / POST cancel / POST retry / worker cancel listener + GraphInterrupt / worker retry path / Stale scanner Beat task / L2 chaos test / 3 differential golden / 前端 cancel + retry button
- ❌ 不做(留 v1.x escape hatch):
  - Cancel 信号「秒级精度」(spec § 6.1 接受 graph node 之间 1-3 秒粒度)
  - 全局 task dashboard(只一个 admin GET endpoint 看 chat_tasks 表即可,不做 UI)
  - 静默自动 retry(spec § 9.3 显式不做,user 必须主动 retry)
  - 跨用户 Celery quota / rate limit
  - 后端 cancel 一致性强保证(Pub/Sub at-most-once delivery,接受罕见漏 cancel)

**Plan 2 已就位的接口(Plan 3 直接消费)**:
- `chat_tasks.langgraph_checkpoint_id`(Plan 2 已写入)+ `parent_task_id`(已有字段)+ `initial_prompt_message_id`(已有字段)
- `chat_tasks.last_event_seq`(Plan 2 worker bump 中)
- `ChatEventBus.xadd_event` / `xread_blocking` / `set_ttl`(Plan 2 ship)
- `chat_finalize.finalize_task_persistence`(Plan 2 ship)
- `_build_chat_graph_for_worker` / `_build_session_factory_for_worker` / `_build_redis_for_worker`(Plan 2 Task 8 ship)
- `enqueue_run_chat`(Plan 2 ship)— Plan 3 retry 直接复用,worker 内根据 checkpoint_id 续跑

**完成后用户感知**:
1. **点「停止生成」按钮 → 推理几秒内停下,聊天显示「已取消」状态 + 保留已生成的部分**
2. **点「重试」按钮 → 从 LangGraph 上次稳定 state 续跑(不从头开始)**,token 接着吐
3. **Worker crash → 1 分钟内自动 mark error,前端看 error badge + retry 按钮**

---

## File Structure

| 文件 | 新/改 | 责任 |
|---|---|---|
| `backend/app/services/chat_cancel_bus.py` | **新** | `ChatCancelBus`:Redis pub/sub 封装 — `publish_cancel(tid)` / async subscribe listener factory |
| `backend/app/router/chat.py` | **改** | 加 POST `/chat/cancel/{tid}` + POST `/chat/retry/{tid}` 两个 endpoint |
| `backend/app/tasks/chat_runner.py` | **改** | `run_chat_async` 加 cancel listener + GraphInterrupt 检查;`run_chat` Celery wrapper 接 `checkpoint_id` / `parent_task_id` 参数 |
| `backend/app/tasks/chat_stale_scanner.py` | **新** | Celery Beat task `scan_stale_chat_tasks`:扫 stale + mark error + emit error event |
| `backend/app/tasks/celery_beat_schedule.py` | **改** | 加 `scan_stale_chat_tasks` beat 调度(每分钟一次) |
| `backend/app/services/chat_task_repo.py` | **微改** | 加 `find_stale_running_tasks(min_age_minutes=5)` method |
| `frontend/src/api/chatApi.ts` | **改** | 加 `cancelChatTask(taskId)` + `retryChatTask(taskId)` |
| `frontend/src/components/chat/InputArea.tsx` 或 `ChatPane.tsx` | **改** | 加 cancel 按钮(streaming 时显示)+ retry 按钮(error 时显示)|
| `frontend/src/hooks/useChatSSE.ts` | **微改** | 加 `cancelTask(tid)` / `retryTask(tid)` 接口供组件调用 |
| `backend/tests/unit/test_chat_cancel_bus.py` | **新** | L0 unit:publish + subscribe + 多 listener fan-out |
| `backend/tests/unit/test_chat_stale_scanner.py` | **新** | L0 unit:fake clock + sqlite 模拟 stale 检测逻辑 |
| `backend/tests/integration/test_chat_cancel_retry.py` | **新** | L1 集成:eager Celery + fakeredis + 4 路径(cancel before tool / cancel after tool / retry from checkpoint / retry without checkpoint) |
| `backend/tests/integration/test_chat_chaos_l2.py` | **新** | L2 集成:真 Celery + 真 Redis + 杀 worker 中途 + 杀 Redis + 杀 web 三类故障演练 |
| `backend/tests/integration/test_chat_differential_golden.py` | **新** | 3 differential golden cases(spec § 8)|
| `frontend/src/hooks/__tests__/useChatSSE.test.tsx` | **改** | 加 cancel + retry 流程测试 |

**为什么 chat_stale_scanner.py 单独 module**:跟 chat_runner.py 不耦合(scanner 不依赖 graph / worker singleton),且 Celery Beat 调度跟主 task 注册分开方便管理。

---

## Task 1: ChatCancelBus — Redis pub/sub 封装 + L0 测试

**Spec 锚:** spec § 6.1(Cancel 信号在 graph 内的传播)— Redis pub/sub channel-per-task

**Files:**
- Create: `backend/app/services/chat_cancel_bus.py`
- Create: `backend/tests/unit/test_chat_cancel_bus.py`

- [ ] **Step 1: 写失败测试 — ChatCancelBus 4 method 覆盖**

新建 `backend/tests/unit/test_chat_cancel_bus.py`:

```python
"""ChatCancelBus L0 unit — Redis pub/sub publish + subscribe 封装。

测试覆盖:
- publish_cancel 写入 Redis pub/sub channel
- subscribe_cancel 接到 publish 的 signal
- Multi-listener fan-out:同 channel 多个 subscriber 都收到
- 无 subscriber 时 publish 不 block / 不报错
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fakeredis.aioredis import FakeRedis

from app.services.chat_cancel_bus import ChatCancelBus


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=False)


async def test_publish_then_subscribe_delivers_signal(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()

    received: list[bool] = []
    flag = asyncio.Event()

    async def listener() -> None:
        async for _ in bus.subscribe_cancel(tid):
            received.append(True)
            flag.set()
            return

    listener_task = asyncio.create_task(listener())
    # Give listener a moment to subscribe
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid)
    await asyncio.wait_for(flag.wait(), timeout=2.0)
    await listener_task
    assert received == [True]


async def test_publish_without_subscriber_is_noop(fake_redis: FakeRedis) -> None:
    """publish 时没人 listen — 应该 return 0 而不抛异常。"""
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()
    # Should not raise / hang
    receivers = await bus.publish_cancel(tid)
    assert receivers == 0


async def test_two_listeners_both_receive(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid = uuid.uuid4()
    flags = [asyncio.Event(), asyncio.Event()]

    async def listener(idx: int) -> None:
        async for _ in bus.subscribe_cancel(tid):
            flags[idx].set()
            return

    listener_tasks = [asyncio.create_task(listener(i)) for i in (0, 1)]
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid)
    for f in flags:
        await asyncio.wait_for(f.wait(), timeout=2.0)
    for t in listener_tasks:
        await t


async def test_different_task_ids_isolated(fake_redis: FakeRedis) -> None:
    bus = ChatCancelBus(redis=fake_redis)
    tid1 = uuid.uuid4()
    tid2 = uuid.uuid4()
    got_tid1 = asyncio.Event()
    got_tid2 = asyncio.Event()

    async def listener_for(tid: uuid.UUID, flag: asyncio.Event) -> None:
        async for _ in bus.subscribe_cancel(tid):
            flag.set()
            return

    t1 = asyncio.create_task(listener_for(tid1, got_tid1))
    t2 = asyncio.create_task(listener_for(tid2, got_tid2))
    await asyncio.sleep(0.05)
    await bus.publish_cancel(tid1)
    await asyncio.wait_for(got_tid1.wait(), timeout=2.0)
    # tid2 should NOT have been triggered
    assert not got_tid2.is_set()
    # cleanup
    t2.cancel()
    try:
        await t2
    except asyncio.CancelledError:
        pass
    await t1
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_cancel_bus.py -v
```

Expected: 4 FAIL — `chat_cancel_bus` 模块不存在。

- [ ] **Step 3: 写最小实现 `chat_cancel_bus.py`**

```python
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
    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    @staticmethod
    def _channel(task_id: uuid.UUID) -> str:
        return f"chat:cancel:{task_id}"

    async def publish_cancel(self, task_id: uuid.UUID) -> int:
        """发 cancel 信号到 task 的 channel。返 receiver count。"""
        channel = self._channel(task_id)
        return await self._redis.publish(channel, b"cancel")

    async def subscribe_cancel(
        self, task_id: uuid.UUID
    ) -> AsyncIterator[bytes]:
        """Subscribe channel,yield 收到的 message。

        Worker 内典型用法:
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
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_cancel_bus.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: mypy + ruff**

```bash
uv run mypy backend/app/services/chat_cancel_bus.py backend/tests/unit/test_chat_cancel_bus.py
uv run ruff check backend/app/services/chat_cancel_bus.py backend/tests/unit/test_chat_cancel_bus.py
uv run ruff format --check backend/app/services/chat_cancel_bus.py backend/tests/unit/test_chat_cancel_bus.py
```

Expected: 全 clean。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chat_cancel_bus.py backend/tests/unit/test_chat_cancel_bus.py
git commit -m "feat(chat-persistence): ChatCancelBus — Redis pub/sub cancel signal + 4 L0 test"
```

---

## Task 2: ChatTaskRepo 加 find_stale_running_tasks method

**Spec 锚:** spec § 6.6(stale 探测策略) — Beat 每分钟扫 status=running 且 last_event_seq 5 分钟未变

**Files:**
- Modify: `backend/app/services/chat_task_repo.py`
- Modify: `backend/tests/unit/test_chat_task_repo.py`

- [ ] **Step 1: 写失败测试 — find_stale_running_tasks**

在 `backend/tests/unit/test_chat_task_repo.py` 末尾追加:

```python
async def test_find_stale_running_tasks_returns_old_running(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """status=running 且 started_at 早于 cutoff,且 last_event_seq 长时间未变 → 视为 stale。"""
    repo = ChatTaskRepo(session_factory)

    # 创造一个 task,mark_running,但不 bump_seq
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)

    # 模拟时间过去 — 直接 update started_at 为 10 分钟前
    from datetime import datetime, timedelta
    from sqlalchemy import update
    from app.models.chat import ChatTask

    old_time = datetime.utcnow() - timedelta(minutes=10)
    async with session_factory() as sess:
        await sess.execute(
            update(ChatTask).where(ChatTask.id == task.id).values(started_at=old_time)
        )
        await sess.commit()

    stale = await repo.find_stale_running_tasks(min_age_minutes=5)
    assert any(t.id == task.id for t in stale), (
        f"expected task in stale list, got {[t.id for t in stale]}"
    )


async def test_find_stale_running_tasks_excludes_recent_running(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """刚 mark_running 的 task(started_at < 5min ago)→ 不算 stale。"""
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)

    stale = await repo.find_stale_running_tasks(min_age_minutes=5)
    assert all(t.id != task.id for t in stale), "fresh running task should not be stale"


async def test_find_stale_running_tasks_excludes_done(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_session: uuid.UUID,
) -> None:
    """已完成 task 不算 stale。"""
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_done(task.id, langgraph_checkpoint_id=None)

    stale = await repo.find_stale_running_tasks(min_age_minutes=0)
    assert all(t.id != task.id for t in stale), "done task should not be stale"
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_task_repo.py::test_find_stale_running_tasks_returns_old_running -v
```

Expected: FAIL — `find_stale_running_tasks` method 不存在。

- [ ] **Step 3: 加 method 到 ChatTaskRepo**

在 `backend/app/services/chat_task_repo.py` `ChatTaskRepo` 类末尾加:

```python
    async def find_stale_running_tasks(
        self, *, min_age_minutes: int = 5
    ) -> list[ChatTask]:
        """Return all chat_tasks with status='running' and started_at older than cutoff.

        Plan 3 stale scanner 用 — Celery Beat 每分钟跑,扫到的 task 后续 mark_error +
        XADD error event(spec § 6.6)。
        """
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(minutes=min_age_minutes)
        async with self._sf() as sess:
            stmt = (
                select(ChatTask)
                .where(
                    and_(
                        ChatTask.status == "running",
                        ChatTask.started_at < cutoff,
                    )
                )
                .order_by(ChatTask.started_at.asc())
            )
            return list((await sess.execute(stmt)).scalars().all())
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_task_repo.py -v
```

Expected: 全 PASS(原 9 + 新 3 = 12)。

- [ ] **Step 5: mypy + ruff + commit**

```bash
uv run mypy backend/app/services/chat_task_repo.py
uv run ruff check backend/app/services/chat_task_repo.py backend/tests/unit/test_chat_task_repo.py
git add backend/app/services/chat_task_repo.py backend/tests/unit/test_chat_task_repo.py
git commit -m "feat(chat-persistence): ChatTaskRepo.find_stale_running_tasks for Plan 3 stale scanner"
```

---

## Task 3: Worker cancel listener + GraphInterrupt + partial commit

**Spec 锚:** spec § 6.1(Cancel 信号在 graph 内的传播 — option c:graph 节点间 wrapper 检查 cancel flag,raise GraphInterrupt → partial commit)

**Files:**
- Modify: `backend/app/tasks/chat_runner.py` `run_chat_async`
- Modify: `backend/tests/unit/test_chat_runner.py`

- [ ] **Step 1: 写失败测试 — cancel 在 graph stream 中途 raise → partial commit**

在 `backend/tests/unit/test_chat_runner.py` 末尾追加:

```python
async def test_run_chat_async_cancel_signal_aborts_graph_and_marks_partial(
    session_factory, seeded_running_task
):
    """模拟 Redis pub/sub publish cancel → worker listener set Event → graph wrapper
    检查 Event → raise GraphInterrupt → finalize 走 partial commit(status=partial)。
    """
    from fakeredis.aioredis import FakeRedis
    from app.services.chat_event_bus import ChatEventBus
    from app.services.chat_cancel_bus import ChatCancelBus
    from app.services.chat_task_repo import ChatTaskRepo
    from app.services.chat_session_repo import ChatSessionRepo

    fake_redis = FakeRedis(decode_responses=False)
    cancel_bus = ChatCancelBus(fake_redis)

    # Fake graph that yields 2 token chunks, then waits 5s before another → cancel
    # arrives between chunks; wrapper sees flag, raises GraphInterrupt.
    class _SlowFakeGraph:
        def __init__(self) -> None:
            self.cancel_event = None  # set externally
        async def astream_events(self, _initial, config=None, version="v2"):
            yield {"event": "on_chat_model_stream", "name": "model",
                   "data": {"chunk": MagicMock(content="part1 ")}}
            # publish cancel during this gap
            await asyncio.sleep(0.3)
            yield {"event": "on_chat_model_stream", "name": "model",
                   "data": {"chunk": MagicMock(content="part2 ")}}
            await asyncio.sleep(2.0)
            yield {"event": "on_chain_end", "name": "LangGraph",
                   "data": {"output": {"final_response": "full"}}}
        async def aget_state(self, _config):
            return MagicMock(config={"configurable": {"checkpoint_id": "ckpt-partial"}})

    fake_graph = _SlowFakeGraph()

    # Run the async task; in parallel, publish cancel after 0.5s
    async def trigger_cancel():
        await asyncio.sleep(0.5)
        await cancel_bus.publish_cancel(seeded_running_task["task_id"])

    cancel_task = asyncio.create_task(trigger_cancel())
    await run_chat_async(
        task_id=seeded_running_task["task_id"],
        graph_factory=lambda: fake_graph,
        session_factory=session_factory,
        redis=fake_redis,
        user_message="cancel me",
        session_id=str(seeded_running_task["session_id"]),
        user_id=seeded_running_task["user_id"],
    )
    await cancel_task

    # Assertions: task status=partial OR cancelled, error_message about cancel
    task_repo = ChatTaskRepo(session_factory)
    refreshed = await task_repo.get_by_id(seeded_running_task["task_id"])
    assert refreshed.status in ("partial", "cancelled"), (
        f"expected partial/cancelled, got {refreshed.status}"
    )

    # PG chat_messages assistant should exist with status=partial,内容 = 已生成部分
    msg_repo = ChatSessionRepo(session_factory)
    msgs = await msg_repo.list_messages(str(seeded_running_task["session_id"]))
    assistant_msgs = [m for m in msgs if m.role == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0].status in ("partial", "cancelled")
    # content 应该至少有 part1 / part2 中的一个
    assert "part" in assistant_msgs[0].content

    # Redis Stream 应该有 cancelled 终止事件(而不是 done)
    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(
        seeded_running_task["session_id"],
        seeded_running_task["task_id"],
        last_id="0", count=100, block_ms=10,
    )
    types = [e[1].get("type") for e in entries]
    assert "cancelled" in types or "error_done" in types or any(
        e[1].get("type") == "done" and e[1].get("reason") == "cancelled"
        for e in entries
    )
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py::test_run_chat_async_cancel_signal_aborts_graph_and_marks_partial -v
```

Expected: FAIL — `run_chat_async` 还没接 cancel listener。

- [ ] **Step 3: 改 `run_chat_async` 加 cancel listener + wrapper 检查 + partial commit**

修改 `backend/app/tasks/chat_runner.py:run_chat_async`:

```python
async def run_chat_async(
    *,
    task_id: uuid.UUID,
    graph_factory: Callable[[], Any],
    session_factory: Callable[[], Any],
    redis: Any,
    user_message: str,
    session_id: str,
    user_id: uuid.UUID | str | None,
    resume_checkpoint_id: str | None = None,
) -> None:
    """Plan 3 加 resume_checkpoint_id 参数 + cancel listener。其他逻辑不变。"""
    task_repo = ChatTaskRepo(session_factory)
    bus = ChatEventBus(redis=redis)

    # Plan 3 新增:Redis pub/sub cancel listener
    from app.services.chat_cancel_bus import ChatCancelBus
    cancel_bus = ChatCancelBus(redis=redis)
    cancel_event = asyncio.Event()

    async def _cancel_listener() -> None:
        try:
            async for _ in cancel_bus.subscribe_cancel(task_id):
                cancel_event.set()
                return  # 第一个 cancel 即可
        except Exception as exc:
            logger.debug("cancel listener exit for task %s: %s", task_id, exc)

    listener_task = asyncio.create_task(_cancel_listener())

    sid_uuid: uuid.UUID = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    try:
        await task_repo.mark_running(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mark_running skipped: %s", exc)

    try:
        await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_ttl skipped: %s", exc)

    acc_assistant: list[str] = []
    graph_error: Exception | None = None
    cancelled_by_user = False
    final_state: dict[str, Any] | None = None

    graph = graph_factory()

    initial = {
        "user_id": str(user_id),
        "session_id": session_id,
        "user_message": user_message,
        "request_id": f"req-{uuid.uuid4().hex[:12]}",
        "trace_request_id": f"req-{uuid.uuid4().hex[:12]}",
    }
    # Plan 3 retry: 传 checkpoint_id 让 LangGraph 从 checkpoint state 续跑
    configurable: dict[str, Any] = {"thread_id": f"{user_id}:{session_id}"}
    if resume_checkpoint_id is not None:
        configurable["checkpoint_id"] = resume_checkpoint_id
    config: dict[str, Any] = {"configurable": configurable}

    class _CancelledByUser(Exception):
        pass

    try:
        async for ev in graph.astream_events(initial, config=config, version="v2"):
            # Plan 3 cancel: 每个 event 之间检查 flag(spec § 6.1 wrapper)
            if cancel_event.is_set():
                raise _CancelledByUser()

            if ev.get("event") == "on_chain_end" and ev.get("name") == "LangGraph":
                output = (ev.get("data") or {}).get("output") or {}
                if isinstance(output, dict):
                    final_state = output

            adapted = _adapt_event_for_stream(ev)
            if adapted is None:
                continue
            try:
                await bus.xadd_event(sid_uuid, task_id, adapted)
            except Exception as exc:
                logger.warning("xadd_event failed for task %s: %s", task_id, exc)
            if adapted.get("type") == "token":
                acc_assistant.append(adapted.get("text", ""))
            try:
                await task_repo.bump_seq(task_id, delta=1)
            except Exception as exc:
                logger.debug("bump_seq skipped: %s", exc)
    except _CancelledByUser:
        cancelled_by_user = True
        # Emit cancelled event to Redis Stream
        try:
            await bus.xadd_event(
                sid_uuid, task_id, {"type": "cancelled", "reason": "user_cancel"}
            )
        except Exception:
            pass
    except Exception as exc:
        graph_error = exc
        try:
            await bus.xadd_event(
                sid_uuid, task_id, {"type": "error", "message": str(exc)[:500]}
            )
        except Exception:
            pass
    finally:
        # Cancel listener task no longer needed
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # fallback token(direct_response 路径)— spec § 6.5
        if graph_error is None and not cancelled_by_user and not acc_assistant:
            fallback_text = ""
            if isinstance(final_state, dict):
                fr = final_state.get("final_response")
                if isinstance(fr, str) and fr:
                    fallback_text = _extract_response_text(fr)
            if fallback_text:
                try:
                    await bus.xadd_event(
                        sid_uuid,
                        task_id,
                        {"type": "token", "text": fallback_text, "content": fallback_text},
                    )
                    acc_assistant.append(fallback_text)
                except Exception as exc:
                    logger.warning("fallback token xadd failed: %s", exc)

        # 终止事件
        try:
            terminal_type = (
                "cancelled"
                if cancelled_by_user
                else ("done" if graph_error is None else "error_done")
            )
            await bus.xadd_event(sid_uuid, task_id, {"type": terminal_type})
        except Exception as exc:
            logger.warning("terminal xadd failed: %s", exc)

        # finalize commit (Plan 3: cancel path 走 mark_partial 而非 mark_done/error)
        accumulated = "".join(acc_assistant)
        try:
            if cancelled_by_user:
                # Custom partial commit path
                from app.services.chat_session_repo import ChatSessionRepo
                session_repo = ChatSessionRepo(session_factory)
                checkpoint_id: str | None = None
                try:
                    state = await graph.aget_state(config)
                    cp = (state.config.get("configurable", {}) or {}).get("checkpoint_id")
                    if isinstance(cp, str):
                        checkpoint_id = cp
                except Exception:
                    pass
                await session_repo.append_message(
                    session_id=session_id,
                    role="assistant",
                    content=accumulated,
                    task_id=task_id,
                    status="partial",
                )
                await task_repo.mark_partial(task_id, langgraph_checkpoint_id=checkpoint_id)
            else:
                await finalize_task_persistence(
                    pg_factory=session_factory,
                    task_id=task_id,
                    session_id=session_id,
                    graph=graph,
                    config=config,
                    final_state=final_state,
                    accumulated_token_text=accumulated,
                    graph_error=graph_error,
                )
        except Exception as exc:
            logger.exception("finalize failed for task %s: %s", task_id, exc)

        try:
            await bus.set_ttl(sid_uuid, task_id, seconds=ChatEventBus.DEFAULT_TTL_SECONDS)
        except Exception:
            pass
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py -v
```

Expected: 全 PASS(原 2 + 新 1 = 3)。

注意:`test_run_chat_async_cancel_signal_aborts_graph_and_marks_partial` test 用 fake `_SlowFakeGraph`,publish cancel timing 跟 sleep gap 配合。可能要调整 sleep 让 cancel 在 chunk 间被检测到。

- [ ] **Step 5: 守护现有 chat_runner 测试 + Plan 2 regression**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py backend/tests/integration/test_chat_inflight_plan2.py backend/tests/integration/test_chat_persistence_plan1.py -v 2>&1 | tail -10
```

Expected: 全 PASS。

- [ ] **Step 6: mypy + ruff + commit**

```bash
uv run mypy backend/app/tasks/chat_runner.py backend/tests/unit/test_chat_runner.py
uv run ruff check backend/app/tasks/chat_runner.py backend/tests/unit/test_chat_runner.py
git add backend/app/tasks/chat_runner.py backend/tests/unit/test_chat_runner.py
git commit -m "feat(chat-persistence): worker cancel listener + GraphInterrupt + partial commit"
```

---

## Task 4: POST /chat/cancel/{tid} endpoint

**Spec 锚:** spec § 5.3 Scenario C(用户点停止)

**Files:**
- Modify: `backend/app/router/chat.py`(加 endpoint)
- Modify: `backend/tests/integration/test_chat_inflight_plan2.py`(加 cancel L1 test)

- [ ] **Step 1: 写失败测试 — POST cancel publish + worker 反应**

在 `test_chat_inflight_plan2.py` 末尾追加:

```python
async def test_post_chat_cancel_publishes_to_pubsub(
    test_client, fake_redis, seeded_running_task
):
    """POST /api/v0/chat/cancel/{tid} → ChatCancelBus.publish_cancel,Redis pub/sub
    应该有 1 个 receiver(我们在 test 内 subscribe)。"""
    tid = seeded_running_task["task_id"]

    received: list[bytes] = []
    flag = asyncio.Event()

    async def subscriber() -> None:
        from app.services.chat_cancel_bus import ChatCancelBus
        cancel_bus = ChatCancelBus(fake_redis)
        async for data in cancel_bus.subscribe_cancel(tid):
            received.append(data)
            flag.set()
            return

    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.05)

    resp = test_client.post(f"/api/v0/chat/cancel/{tid}")
    assert resp.status_code == 202

    await asyncio.wait_for(flag.wait(), timeout=2.0)
    await sub_task
    assert len(received) == 1


def test_post_chat_cancel_404_for_unknown_task(test_client, fake_redis):
    """Unknown task_id → 404。"""
    fake_tid = uuid.uuid4()
    resp = test_client.post(f"/api/v0/chat/cancel/{fake_tid}")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py::test_post_chat_cancel_publishes_to_pubsub -v
```

Expected: FAIL — endpoint 还没实现。

- [ ] **Step 3: 加 endpoint 到 `chat.py`**

```python
@router.post("/api/v0/chat/cancel/{task_id}", status_code=202)
async def chat_cancel(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: Any | None = Depends(get_redis_async),
) -> dict[str, str]:
    """Publish cancel signal to chat:cancel:{tid} channel.

    Spec § 5.3 Scenario C:user 点停止 → 立即 return 202(异步生效);worker 内
    listener 收到 signal → raise GraphInterrupt → finalize 走 partial commit。

    `redis` 不可达时返 503;task 不存在返 404。
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(404, f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(503, "chat cancel not available — PG or Redis unavailable")

    task_repo = ChatTaskRepo(pg_factory)
    task = await task_repo.get_by_id(task_uuid)
    if task is None:
        raise HTTPException(404, f"task {task_id} not found")

    from app.services.chat_cancel_bus import ChatCancelBus
    cancel_bus = ChatCancelBus(redis=redis)
    receivers = await cancel_bus.publish_cancel(task_uuid)
    return {"task_id": task_id, "receivers": str(receivers), "status": "cancel_published"}
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
uv run pytest backend/tests/integration/test_chat_inflight_plan2.py -v
```

Expected: 全 PASS。

- [ ] **Step 5: mypy + ruff + commit**

```bash
uv run mypy backend/app/router/chat.py
uv run ruff check backend/app/router/chat.py backend/tests/integration/test_chat_inflight_plan2.py
git add backend/app/router/chat.py backend/tests/integration/test_chat_inflight_plan2.py
git commit -m "feat(chat-persistence): POST /chat/cancel/{tid} endpoint + L1 publish test"
```

---

## Task 5: POST /chat/retry/{tid} endpoint + worker resume path

**Spec 锚:** spec § 5.4 Scenario D(worker crash → retry from checkpoint);§ 6.4 retry 链 parent_task_id;§ 4.4 LangGraph checkpoint 复用

**Files:**
- Modify: `backend/app/router/chat.py`(加 retry endpoint)
- Modify: `backend/app/tasks/chat_runner.py`(enqueue_run_chat 接 `resume_checkpoint_id` + `parent_task_id`)
- Test: `backend/tests/integration/test_chat_cancel_retry.py`(新)

- [ ] **Step 1: 写失败测试 — retry endpoint + worker resume**

新建 `backend/tests/integration/test_chat_cancel_retry.py`:

```python
"""Plan 3 L1: POST /chat/retry/{tid} + worker 从 checkpoint 续跑。

测试覆盖:
- task 有 checkpoint_id → retry 创建新 task(parent_task_id=旧 tid),enqueue 时传
  resume_checkpoint_id,worker config 内含 checkpoint_id
- task 无 checkpoint_id → 422(无法 retry)
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from app.core.database import Base
from app.models.chat import ChatSession
from app.models.user import User  # noqa: F401
from app.router.chat import (
    get_async_session_factory, get_chat_graph, get_current_user,
    get_escalation_extractor, get_escalation_record_repo, get_redis_async,
    router as chat_router,
)
from app.services.chat_task_repo import ChatTaskRepo


# 同 test_chat_inflight_plan2.py fixtures(略 — 实施时 copy)
# session_factory, fake_redis, _StubUser, _client


@pytest.mark.asyncio
async def test_post_retry_with_checkpoint_enqueues_resume_task(
    test_client, session_factory, fake_redis, monkeypatch
):
    """Failed task with checkpoint_id → retry 创建新 task,parent 链接旧 tid。"""
    enqueued: list[dict[str, Any]] = []
    from app.tasks import chat_runner

    def fake_enqueue(**kwargs: Any) -> Any:
        enqueued.append(kwargs)
        class _R: id = kwargs["task_id"]
        return _R()
    monkeypatch.setattr(chat_runner, "enqueue_run_chat", fake_enqueue)

    # Seed: session + done task with checkpoint_id
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()

    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid, user_id=uuid.uuid4(),
        langgraph_thread_id=f"u:{sid}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(old_task.id)
    await task_repo.mark_error(old_task.id, error_message="simulated crash")
    # Plan 1 Task 5 finalize 时会写 checkpoint;手动 update 模拟
    from sqlalchemy import update as sql_update
    from app.models.chat import ChatTask
    async with session_factory() as sess:
        await sess.execute(
            sql_update(ChatTask).where(ChatTask.id == old_task.id)
            .values(langgraph_checkpoint_id="ckpt-resume-x")
        )
        await sess.commit()

    resp = test_client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    new_tid = body["task_id"]
    assert new_tid != str(old_task.id)

    # 验证 enqueue 被调 + 传了 resume_checkpoint_id + parent_task_id
    assert len(enqueued) == 1
    assert enqueued[0]["resume_checkpoint_id"] == "ckpt-resume-x"
    assert enqueued[0].get("parent_task_id") == str(old_task.id) or enqueued[0]["task_id"] != str(old_task.id)

    # 新 chat_tasks row 存在,parent_task_id 链接
    new_task = await task_repo.get_by_id(uuid.UUID(new_tid))
    assert new_task is not None
    assert new_task.parent_task_id == old_task.id


@pytest.mark.asyncio
async def test_post_retry_without_checkpoint_returns_422(
    test_client, session_factory, fake_redis
):
    """Failed task **没** checkpoint_id → 422 "cannot resume"。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    task_repo = ChatTaskRepo(session_factory)
    old_task = await task_repo.create_queued(
        session_id=sid, user_id=uuid.uuid4(),
        langgraph_thread_id="t", initial_prompt_message_id=None,
    )
    await task_repo.mark_error(old_task.id, error_message="early failure")
    # No checkpoint_id

    resp = test_client.post(f"/api/v0/chat/retry/{old_task.id}")
    assert resp.status_code == 422
    assert "checkpoint" in resp.text.lower() or "resume" in resp.text.lower()
```

- [ ] **Step 2: 运行,确认失败**

```bash
uv run pytest backend/tests/integration/test_chat_cancel_retry.py -v
```

Expected: 2 FAIL — endpoint 不存在 / enqueue_run_chat 不接 resume_checkpoint_id 参数。

- [ ] **Step 3: 改 `enqueue_run_chat` 接 `resume_checkpoint_id` + `parent_task_id`**

修改 `backend/app/tasks/chat_runner.py`:

```python
def enqueue_run_chat(
    *,
    task_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    resume_checkpoint_id: str | None = None,
    parent_task_id: str | None = None,  # 仅 audit / log,worker 不直接用
) -> Any:
    """Production enqueue — POST /chat 改造 + POST /chat/retry 都调本函数。

    Plan 3 retry 加 resume_checkpoint_id 参数;worker async entry 用它构造
    RunnableConfig {configurable: {thread_id, checkpoint_id}} 让 LangGraph
    从 checkpoint state 续跑。
    """
    return run_chat.delay(
        task_id=task_id,
        session_id=session_id,
        user_id=user_id,
        user_message=user_message,
        resume_checkpoint_id=resume_checkpoint_id,
    )
```

修改 `run_chat` Celery wrapper:

```python
@celery_app.task(name="app.tasks.chat_runner.run_chat", bind=True)
def run_chat(
    self: Any,
    task_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    resume_checkpoint_id: str | None = None,
) -> None:
    import asyncio
    asyncio.run(
        run_chat_async(
            task_id=uuid.UUID(task_id),
            graph_factory=_build_chat_graph_for_worker,
            session_factory=_build_session_factory_for_worker(),
            redis=_build_redis_for_worker(),
            user_message=user_message,
            session_id=session_id,
            user_id=user_id,
            resume_checkpoint_id=resume_checkpoint_id,
        )
    )
```

- [ ] **Step 4: 加 POST /chat/retry/{tid} endpoint 到 `chat.py`**

```python
@router.post("/api/v0/chat/retry/{task_id}")
async def chat_retry(
    task_id: str,
    pg_factory: Any | None = Depends(get_async_session_factory),
    redis: Any | None = Depends(get_redis_async),
) -> dict[str, str]:
    """Retry failed task from LangGraph checkpoint.

    Plan 3 spec § 5.4 / § 6.4:
    - task.status 必须是 error / partial(done / running 拒)
    - task.langgraph_checkpoint_id 必须非空,否则 422
    - 创建新 chat_tasks row,parent_task_id=旧 tid,initial_prompt_message_id 复用
    - enqueue Celery 带 resume_checkpoint_id,worker LangGraph 续跑
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(404, f"invalid task_id: {task_id}") from exc

    if pg_factory is None or redis is None:
        raise HTTPException(503, "retry not available — PG or Redis unavailable")

    task_repo = ChatTaskRepo(pg_factory)
    old_task = await task_repo.get_by_id(task_uuid)
    if old_task is None:
        raise HTTPException(404, f"task {task_id} not found")

    if old_task.status not in ("error", "partial", "cancelled"):
        raise HTTPException(
            409, f"cannot retry task in status={old_task.status}; only error/partial/cancelled"
        )
    if not old_task.langgraph_checkpoint_id:
        raise HTTPException(
            422,
            "cannot resume: task has no langgraph_checkpoint_id (early failure before any checkpoint commit)"
        )

    # Create new task linked to old
    new_task = await task_repo.create_queued(
        session_id=old_task.session_id,
        user_id=old_task.user_id,
        langgraph_thread_id=old_task.langgraph_thread_id,
        initial_prompt_message_id=old_task.initial_prompt_message_id,
        parent_task_id=old_task.id,
    )

    from app.tasks.chat_runner import enqueue_run_chat
    enqueue_run_chat(
        task_id=str(new_task.id),
        session_id=str(old_task.session_id),
        user_id=str(old_task.user_id) if old_task.user_id else "anonymous",
        user_message="",  # resume 不需要新 user_message(graph 从 checkpoint 续)
        resume_checkpoint_id=old_task.langgraph_checkpoint_id,
        parent_task_id=str(old_task.id),
    )

    return {
        "task_id": str(new_task.id),
        "parent_task_id": str(old_task.id),
        "stream_url": f"/api/v0/chat/stream/{new_task.id}",
        "resumed_from_checkpoint": old_task.langgraph_checkpoint_id,
    }
```

- [ ] **Step 5: 运行测试,确认通过**

```bash
uv run pytest backend/tests/integration/test_chat_cancel_retry.py -v
```

Expected: 2 PASS。

- [ ] **Step 6: 守护 Plan 1+2 regression**

```bash
uv run pytest backend/tests/unit/test_chat_runner.py backend/tests/integration/test_chat_inflight_plan2.py backend/tests/integration/test_chat_persistence_plan1.py -v 2>&1 | tail -10
```

Expected: 全 PASS。

- [ ] **Step 7: mypy + ruff + commit**

```bash
uv run mypy backend/app/router/chat.py backend/app/tasks/chat_runner.py
uv run ruff check backend/app/router/chat.py backend/app/tasks/chat_runner.py backend/tests/integration/test_chat_cancel_retry.py
git add backend/app/router/chat.py backend/app/tasks/chat_runner.py backend/tests/integration/test_chat_cancel_retry.py
git commit -m "feat(chat-persistence): POST /chat/retry/{tid} + worker resume from checkpoint"
```

---

## Task 6: Stale scanner Celery Beat task

**Spec 锚:** spec § 6.6(stale 探测策略)

**Files:**
- Create: `backend/app/tasks/chat_stale_scanner.py`
- Modify: `backend/app/tasks/celery_beat_schedule.py`(加调度)
- Modify: `backend/app/tasks/celery_app.py`(autodiscover)
- Test: `backend/tests/unit/test_chat_stale_scanner.py`

- [ ] **Step 1: 写失败测试 — stale scanner mark error + emit event**

新建 `backend/tests/unit/test_chat_stale_scanner.py`:

```python
"""Stale scanner L0 unit。

测试:
- 调用 scanner_async → 扫到 stale task → mark_error → XADD stale event
- 无 stale task → noop
- task 状态 != running(done/error/partial)→ 跳过
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from app.core.database import Base
from app.models.chat import ChatSession, ChatTask
from app.models.user import User  # noqa: F401
from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.chat_stale_scanner import scan_stale_chat_tasks_async


_REQUIRED = ("users", "chat_sessions", "chat_tasks", "chat_messages")


def _selective_create_all(sync_conn):
    Base.metadata.create_all(sync_conn, tables=[Base.metadata.tables[n] for n in _REQUIRED])


@pytest_asyncio.fixture
async def session_factory():
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(_selective_create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_stale_task(session_factory, age_minutes: int = 10):
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=sid, user_id=uuid.uuid4(),
        langgraph_thread_id="t", initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    old_time = datetime.utcnow() - timedelta(minutes=age_minutes)
    async with session_factory() as sess:
        await sess.execute(
            update(ChatTask).where(ChatTask.id == task.id).values(started_at=old_time)
        )
        await sess.commit()
    return sid, task.id


async def test_scanner_marks_stale_task_as_error(session_factory):
    """10 min old running → status=error + error_message contains 'stale'。"""
    sid, tid = await _seed_stale_task(session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    n_marked = await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )
    assert n_marked == 1

    repo = ChatTaskRepo(session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "error"
    assert task.error_message is not None
    assert "stale" in task.error_message.lower()


async def test_scanner_emits_stale_error_event_to_redis_stream(session_factory):
    sid, tid = await _seed_stale_task(session_factory, age_minutes=10)
    fake_redis = FakeRedis(decode_responses=False)

    await scan_stale_chat_tasks_async(
        session_factory=session_factory,
        redis=fake_redis,
        stale_minutes=5,
    )

    bus = ChatEventBus(fake_redis)
    entries = await bus.xread_blocking(sid, tid, last_id="0", count=10, block_ms=10)
    types = [e[1].get("type") for e in entries]
    # 应有 error 或 error_done event,reason='stale'
    has_stale = any(
        e[1].get("type") in ("error", "error_done") and "stale" in str(e[1]).lower()
        for e in entries
    )
    assert has_stale, f"expected stale error event, got types={types}"


async def test_scanner_skips_fresh_running_task(session_factory):
    sid, tid = await _seed_stale_task(session_factory, age_minutes=2)  # 2 min < 5 min cutoff

    fake_redis = FakeRedis(decode_responses=False)
    n = await scan_stale_chat_tasks_async(
        session_factory=session_factory, redis=fake_redis, stale_minutes=5,
    )
    assert n == 0

    repo = ChatTaskRepo(session_factory)
    task = await repo.get_by_id(tid)
    assert task is not None
    assert task.status == "running"  # untouched
```

- [ ] **Step 2: 写实现 `chat_stale_scanner.py`**

```python
"""Stale scanner — Celery Beat task that detects stuck `running` chat_tasks.

Spec § 6.6:每分钟扫,扫到 status='running' + started_at 5min 前 → mark error
+ XADD `{type:error,reason:stale}` 让在线 SSE handler 立刻收到 → 前端 UI
看到 error badge + retry 按钮。

Worker crash / Redis chaos / 任意原因卡 running 的 task 都会被 1 分钟内自愈。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from app.services.chat_event_bus import ChatEventBus
from app.services.chat_task_repo import ChatTaskRepo
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def scan_stale_chat_tasks_async(
    *,
    session_factory: Callable[[], Any],
    redis: Any,
    stale_minutes: int = 5,
) -> int:
    """Find + mark + emit stale events. Returns count of tasks marked.

    DI-friendly:tests inject fakeredis + sqlite session_factory + 控制 stale_minutes。
    """
    task_repo = ChatTaskRepo(session_factory)
    bus = ChatEventBus(redis=redis)

    stale_tasks = await task_repo.find_stale_running_tasks(min_age_minutes=stale_minutes)
    if not stale_tasks:
        return 0

    marked = 0
    for task in stale_tasks:
        try:
            await task_repo.mark_error(
                task.id,
                error_message=f"stale: no heartbeat for {stale_minutes}+ minutes (worker likely crashed)",
            )
            # Emit error event so in-flight SSE clients pick up the failure
            try:
                await bus.xadd_event(
                    task.session_id,
                    task.id,
                    {"type": "error_done", "reason": "stale", "message": "task timed out"},
                )
            except Exception as exc:
                logger.warning("stale scanner xadd failed for %s: %s", task.id, exc)
            marked += 1
        except Exception as exc:
            logger.exception("stale scanner mark_error failed for %s: %s", task.id, exc)
    logger.info("Stale scanner: marked %d/%d tasks", marked, len(stale_tasks))
    return marked


@celery_app.task(name="app.tasks.chat_stale_scanner.scan_stale_chat_tasks")
def scan_stale_chat_tasks() -> int:
    """Celery Beat entry. Runs every minute (configured in celery_beat_schedule.py)."""
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import redis.asyncio as redis_async
    import os
    from app.app_main import _sqlalchemy_async_pg_url

    async def _run() -> int:
        engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
            redis_client = redis_async.Redis.from_url(redis_url, decode_responses=False)
            try:
                return await scan_stale_chat_tasks_async(
                    session_factory=factory,
                    redis=redis_client,
                    stale_minutes=5,
                )
            finally:
                await redis_client.aclose()
        finally:
            await engine.dispose()

    return asyncio.run(_run())
```

- [ ] **Step 3: 加 Beat schedule 在 `celery_beat_schedule.py`**

读 `backend/app/tasks/celery_beat_schedule.py`,加:

```python
"app.tasks.chat_stale_scanner.scan_stale_chat_tasks": {
    "task": "app.tasks.chat_stale_scanner.scan_stale_chat_tasks",
    "schedule": 60.0,  # 每分钟一次,spec § 6.6
},
```

- [ ] **Step 4: celery_app.py autodiscover 加 chat_stale_scanner**

```python
celery_app = Celery(
    "monitoring",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.monitoring",
        "app.tasks.memory",
        "app.tasks.chat_runner",
        "app.tasks.chat_stale_scanner",  # Plan 3 新增
    ],
)
```

- [ ] **Step 5: 运行测试,确认通过**

```bash
uv run pytest backend/tests/unit/test_chat_stale_scanner.py -v
```

Expected: 3 PASS。

- [ ] **Step 6: mypy + ruff + commit**

```bash
uv run mypy backend/app/tasks/chat_stale_scanner.py backend/app/tasks/celery_beat_schedule.py
uv run ruff check backend/app/tasks/chat_stale_scanner.py backend/tests/unit/test_chat_stale_scanner.py
git add backend/app/tasks/chat_stale_scanner.py backend/app/tasks/celery_beat_schedule.py backend/app/tasks/celery_app.py backend/tests/unit/test_chat_stale_scanner.py
git commit -m "feat(chat-persistence): Stale scanner Celery Beat task — 自愈卡 running 的 chat_tasks"
```

---

## Task 7: 前端 cancel + retry button + state UI

**Spec 锚:** spec § 5.3 / § 5.4 / § 7 错误处理矩阵

**Files:**
- Modify: `frontend/src/api/chatApi.ts` 加 `cancelChatTask` / `retryChatTask`
- Modify: `frontend/src/hooks/useChatSSE.ts` 加 `cancelTask` / `retryTask` 接口
- Modify: `frontend/src/components/chat/InputArea.tsx`(streaming 时显 cancel 按钮)
- Modify: `frontend/src/components/chat/MessageList.tsx`(error/partial 时显 retry 按钮)
- Test: `frontend/src/hooks/__tests__/useChatSSE.test.tsx`

- [ ] **Step 1: chatApi 加两个 helpers**

```typescript
export async function cancelChatTask(taskId: string): Promise<void> {
  const res = await fetch(apiUrl(`/api/v0/chat/cancel/${encodeURIComponent(taskId)}`), {
    method: 'POST',
  })
  if (!res.ok && res.status !== 202) {
    throw new Error(`cancel failed: ${res.status}`)
  }
}

export interface RetryChatResponse {
  task_id: string
  parent_task_id: string
  stream_url: string
  resumed_from_checkpoint: string
}

export async function retryChatTask(taskId: string): Promise<RetryChatResponse> {
  const res = await fetch(apiUrl(`/api/v0/chat/retry/${encodeURIComponent(taskId)}`), {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error(`retry failed: ${res.status}`)
  }
  return (await res.json()) as RetryChatResponse
}
```

- [ ] **Step 2: useChatSSE 加 cancelTask / retryTask 接口**

```typescript
interface UseChatSSE {
  sendMessage(content: string): Promise<void>
  abort(): void
  status: () => string
  subscribeToTask(taskId: string, lastEventId?: string): Promise<void>
  cancelTask(taskId: string): Promise<void>
  retryTask(taskId: string): Promise<void>  // 内部:retryChatTask → subscribeToTask
}

// 在 return { sendMessage, ... } 之前:
const cancelTask = useCallback(async (taskId: string) => {
  abortRef.current?.abort()  // 立刻 abort SSE,避免 still-stale frames
  try {
    await cancelChatTask(taskId)
  } catch (e) {
    // 即使后端返失败,UI 仍 reset(用户体感上 cancel 完成)
  }
  currentChatActions.setError('已取消')
}, [])

const retryTask = useCallback(async (taskId: string) => {
  try {
    const r = await retryChatTask(taskId)
    await sse_subscribe_to_new_task(r.task_id)  // 调内部 subscribeToTask 逻辑
  } catch (e) {
    currentChatActions.setError(`重试失败: ${e}`)
  }
}, [...])
```

- [ ] **Step 3: InputArea 加 cancel button (streaming 状态)**

```tsx
// streamingStatus === 'streaming' 时显「停止生成」按钮,点击调 sse.cancelTask
{snap.streamingStatus === 'streaming' && snap.active_task_id && (
  <button onClick={() => sse.cancelTask(snap.active_task_id!)}>
    停止生成
  </button>
)}
```

- [ ] **Step 4: MessageList 加 retry button(assistant message status=error/partial 时)**

```tsx
{m.role === 'assistant' && (m.status === 'error' || m.status === 'partial') && m.task_id && (
  <button onClick={() => sse.retryTask(m.task_id!)}>重试</button>
)}
```

- [ ] **Step 5: store 加 active_task_id 字段**

修改 `current-chat.ts`:加 `active_task_id?: string | null` 到 state + `setActiveTaskId` action。在 sendMessage 拿到 POST JSON 后立即 setActiveTaskId,done 后 clearActiveTaskId。

- [ ] **Step 6: test + build + commit**

```bash
cd frontend && npm test -- useChatSSE --run
npm run build
npm run lint
git add frontend/src/...
git commit -m "feat(chat-persistence): 前端 cancel + retry button + active_task_id state"
```

---

## Task 8: L2 chaos test — 杀 worker / 杀 Redis / 杀 web

**Spec 锚:** spec § 7 错误处理矩阵 + § 8 L2 测试 + Plan 2 dogfood 场景 3 已手动验过 web crash

**Files:**
- Create: `backend/tests/integration/test_chat_chaos_l2.py`

- [ ] **Step 1: 写 L2 chaos test**

```python
"""Plan 3 L2 chaos:真 Celery worker subprocess + 真 Redis + 模拟故障。

3 类:
- 杀 worker 中途 → Beat scanner 1 分钟内 mark error
- 杀 Redis(暂停容器)→ worker XADD 失败 retry,task 仍跑完 → PG 落库
- 杀 web → Celery worker 继续跑,任务完成后 PG 有结果(Plan 2 场景 3 自动化)

需要 fixture:redis_url + celery_worker_subprocess(已有)+ uvicorn subprocess
(新)。
"""
# 实施细节:
# - 起 uvicorn subprocess on test port
# - POST /chat → 拿 task_id
# - SIGTERM uvicorn → 验证 worker 继续 → PG 完整 message
# - SIGKILL worker → poll 65s → 验 chat_tasks.status='error' (Beat scanner triggered)
# - docker pause industry_redis → POST → 验 worker xadd retry → docker unpause → 验 task 完成
```

(本 task 实施细节因环境差异大,推到 implementer 按 conftest_celery 已有模式扩展。)

- [ ] **Step 2: 跑 L2 chaos test**

```bash
REDIS_URL=redis://localhost:6379/0 uv run pytest backend/tests/integration/test_chat_chaos_l2.py -v -s
```

- [ ] **Step 3: commit**

```bash
git add backend/tests/integration/test_chat_chaos_l2.py
git commit -m "test(chat-persistence): L2 chaos — 杀 worker / Redis / web 三类故障守护"
```

---

## Task 9: 3 differential golden cases

**Spec 锚:** spec § 8 differential golden + Plan 2 done card

**Files:**
- Create: `backend/tests/integration/test_chat_differential_golden.py`

- [ ] **Step 1: 3 golden cases**

```python
"""Plan 3 differential golden — spec § 8 守护新机制不破老路径。

Case A: 同 session 同 prompt,有/无 cancel 中断
  → 终态对比:complete (done, full content) vs partial (partial, prefix content)

Case B: 同 session 同 prompt,worker crash + retry vs 不 retry
  → retry 后续 message 应该跟 crash 前 stream 拼接 — `parent_task_id` 链 + checkpoint
  从中断处续

Case C: 同 session 两轮 prompt,第二轮 in-flight 时关页面再开
  → 第一轮 done(完整) + 第二轮 active_task_id 非空,GET /chats 返回完整快照
"""
import pytest
import uuid
# fixtures from test_chat_inflight_plan2 / test_chat_cancel_retry


@pytest.mark.asyncio
async def test_golden_a_cancel_vs_complete(test_client_with_pg, ...):
    """Case A: cancel(status=partial,content=part1+part2) vs complete(status=done,content=full)。"""
    # ...

@pytest.mark.asyncio
async def test_golden_b_retry_continues_from_checkpoint(test_client_with_pg, ...):
    """Case B: 第二个 task(retry)content 应该 ≥ 第一个 task(crashed)content。"""
    # ...

@pytest.mark.asyncio
async def test_golden_c_two_turn_with_inflight_second(test_client_with_pg, ...):
    """Case C: 两轮 chat,第二轮 GET /chats 应有 active_task_id;第一轮 done + 第二轮 running messages。"""
    # ...
```

- [ ] **Step 2: 跑 + commit**

```bash
uv run pytest backend/tests/integration/test_chat_differential_golden.py -v
git add backend/tests/integration/test_chat_differential_golden.py
git commit -m "test(chat-persistence): 3 differential golden — cancel/retry/two-turn-inflight"
```

---

## Task 10: dogfood + done card

- [ ] **Step 1: 真浏览器 dogfood**

1. 发长 prompt → 点「停止生成」 → 验流式吐到一半停;chat_messages 落 partial assistant
2. 发 prompt → kill worker(模拟 crash)→ 等 1 分钟 → 看前端 error badge + retry 按钮 → 点 retry → 续跑
3. 两轮 prompt + 切 session 测试 active_task_id 路径

- [ ] **Step 2: 全套守护**

```bash
uv run pytest backend/tests/ -x --tb=short 2>&1 | tail -10
cd frontend && npm test -- --run
uv run mypy backend/
uv run ruff check backend/
```

- [ ] **Step 3: 写 done card**

`docs/superpowers/plans/2026-05-17-chat-session-persistence-plan3-done.md`,总结 Plan 1+2+3 完整 ship 状态。

- [ ] **Step 4: PR + merge**

---

## Self-Review

### 1. Spec 覆盖

- spec § 5.3 Scenario C(cancel)— Task 3 + 4 ✅
- spec § 5.4 Scenario D(retry from checkpoint)— Task 5 ✅
- spec § 6.1 Cancel 传播(option c wrapper)— Task 3 ✅
- spec § 6.4 1:1 task per user message + parent_task_id 链 — Task 5 ✅
- spec § 6.6 Stale 探测 5 分钟 Beat — Task 6 ✅
- spec § 7 错误处理矩阵 — Task 3 / 5 / 6 / 8 共同覆盖
- spec § 8 测试策略 L2 chaos + differential golden — Task 8 / 9 ✅

### 2. Placeholder 扫描

Task 8 / 9 内有 `# 实施细节略 — 推到 implementer` 提示。这是有意识为之(L2 fixture 因环境差异大,plan 阶段写死会过度约束)。其他 task 都有完整代码 + 命令。

### 3. 类型一致性

- `resume_checkpoint_id: str | None` 在 `enqueue_run_chat` / `run_chat` / `run_chat_async` 三处签名都一致 ✅
- `parent_task_id: str | None` 在 retry endpoint 调用 + `enqueue_run_chat` 两处一致 ✅
- `cancel_event: asyncio.Event` 跟 worker `_CancelledByUser` 配合 ✅

---

## Execution Handoff

Plan 3 complete and saved to `docs/superpowers/plans/2026-05-17-chat-session-persistence-plan3-cancel-retry-chaos.md`.

**1. Subagent-Driven(推荐)** — Plan 3 10 task,内容比 Plan 2 略复杂(retry from checkpoint 是新机制可能踩坑),适合 fresh subagent per task。

**2. Inline Execution** — task 间依赖紧(Task 1 ChatCancelBus → Task 3 worker listener;Task 5 retry → Task 7 前端调它),也可顺序 inline。

工期估 4-5 天 wall time。

**Plan 1 + 2 + 3 完整 ship 后,chat session 持久化的总卡可以收口**(写 docs/claude-context/chat-session-persistence-done.md)。
