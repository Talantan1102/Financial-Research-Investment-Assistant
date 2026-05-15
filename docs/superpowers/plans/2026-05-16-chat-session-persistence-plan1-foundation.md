# Chat Session Persistence — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 chat 模式的 user 消息和 assistant 回复都落 PG;关页面重开能看到完整对话历史(A 档);为 Plan 2 的 Celery + Redis Streams 准备 schema 和 repo 基础。

**Architecture:** 新建 `chat_tasks` 表(6 状态 lifecycle)+ `chat_messages` 加 `task_id` / `status` 两列。改造 `POST /api/v0/chat`:进入时 INSERT user message + create chat_task(status=running);`_stream_chat` finally 块 UPSERT assistant message + mark task done/error。`GET /api/v0/chats/{sid}` 返回 messages + active_task_id。前端 `useChatSSE` 去掉指向不存在 endpoint 的假 reconnect,断流时改为拉历史 messages。

**Tech Stack:** SQLAlchemy 2.x(同步 engine create_all + async engine 业务) + FastAPI + pytest (L0 unit + L1 integration) + React/TypeScript 前端。

**Spec 锚:** `docs/superpowers/specs/2026-05-16-chat-session-persistence-design.md` § 3-5(组件清单 + 数据模型 + 数据流 Scenario A/B)。

**Plan 范围(YAGNI)**:
- ✅ 做:Schema、ChatTaskRepo、ChatSessionRepo 扩展、POST /chat 落库改造、GET /chats 返回 active_task_id、前端去假 reconnect
- ❌ 不做(留 Plan 2):Celery worker、Redis Streams、Redis pub/sub、stream/cancel/retry endpoint、打字机渲染、in-flight subscribe
- ❌ 不做(留 Plan 3):stale scanner、LangGraph checkpoint resume、L2 chaos 故障演练

**完成后用户感知**:刷新 / 关页面重开 → 看到完整对话历史(用户提问 + assistant 回复 + tool 调用记录)。这解决当前 chat 模式「关浏览器 = 蒸发」根因,即 spec § 1 现状根因第一项。

---

## File Structure

| 文件 | 新/改 | 责任 |
|---|---|---|
| `backend/app/models/chat.py` | 改 | 加 `ChatTask` ORM 类 + `ChatMessage` 加 `task_id` / `status` 列 |
| `backend/app/services/chat_task_repo.py` | **新** | `ChatTaskRepo` 类:状态机方法集(create_queued / mark_running / mark_done / mark_partial / mark_cancelled / mark_error / get_by_id / find_active_for_session) |
| `backend/app/services/chat_session_repo.py` | 改 | `append_message` 加 `task_id` / `status` 可选参数;新增 `find_active_task_for_session(sid)` |
| `backend/app/router/chat.py` | 改 | POST `/api/v0/chat` 入口 INSERT user message + create chat_task;`_stream_chat` finally 块 UPSERT assistant + mark task |
| `backend/app/router/chats.py` | 改 | GET `/chats/{sid}` 返回 `{messages, active_task_id}` |
| `backend/app/app_main.py` | 微改 | wire `ChatTaskRepo` 到 `chats_router` dependency(若该 endpoint 用到)|
| `backend/tests/unit/test_chat_task_repo.py` | **新** | L0 unit:8 个 repo 方法 + 状态机非法转换防护 |
| `backend/tests/unit/test_chat_session_repo_extensions.py` | **新** | L0 unit:append_message 新参数 + find_active_task |
| `backend/tests/integration/test_chat_persistence_plan1.py` | **新** | L1 integration:POST /chat 落 user → 跑 graph → finally 落 assistant;GET /chats/{sid} 返回 messages + active_task_id |
| `frontend/src/hooks/useChatSSE.ts` | 改 | 去掉 `buildChatStreamUrl` 重连分支(指向 Plan 2 才实现的 endpoint),断流时改 reload chat history |
| `frontend/src/api/chatApi.ts` | 改 | 标记 `buildChatStreamUrl` 为 deprecated(Plan 2 重写);新增 `reloadChatMessages(sid)` 辅助 |
| `frontend/src/hooks/__tests__/useChatSSE.test.tsx` | 改 | 调整 "F6 reconnect" 测试:不再期望调用 `/chat/stream/:id`,改为期望调用 `GET /chats/:id` 拉历史 |

---

## Task 1: 加 ChatTask ORM model + 字段到 chat_messages

**Spec 锚:** § 4.1 / § 4.2 / § 4.3

**Files:**
- Modify: `backend/app/models/chat.py:66-93`
- Test: `backend/tests/unit/test_chat_task_model.py` (新)

- [ ] **Step 1: 写失败测试 — ChatTask model 可实例化且有约定字段**

新建 `backend/tests/unit/test_chat_task_model.py`:

```python
"""ChatTask ORM model 基础字段 + 默认值测试。

只覆盖 model 层 — Repo 行为见 test_chat_task_repo.py。
"""
from __future__ import annotations

import uuid

import pytest

from app.models.chat import ChatTask, ChatMessage


def test_chat_task_default_status_is_queued() -> None:
    task = ChatTask(
        session_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        langgraph_thread_id="user-123:session-456",
    )
    # SQLAlchemy 字段默认值在 flush 时填充,但 Python-level default 这里也要保证
    assert task.status == "queued"


def test_chat_task_has_required_columns() -> None:
    cols = {c.name for c in ChatTask.__table__.columns}
    expected = {
        "id",
        "session_id",
        "user_id",
        "status",
        "langgraph_thread_id",
        "langgraph_checkpoint_id",
        "created_at",
        "started_at",
        "finished_at",
        "error_message",
        "last_event_seq",
        "initial_prompt_message_id",
        "parent_task_id",
    }
    missing = expected - cols
    assert not missing, f"ChatTask 缺字段: {missing}"


def test_chat_message_has_task_columns() -> None:
    cols = {c.name for c in ChatMessage.__table__.columns}
    assert "task_id" in cols, "ChatMessage 应该有 task_id 列"
    assert "status" in cols, "ChatMessage 应该有 status 列"


def test_chat_task_status_check_constraint() -> None:
    """6 个合法状态值都应在 CHECK 约束里。"""
    constraints = [
        c for c in ChatTask.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]
    # CheckConstraint.sqltext 是 sql 表达式;转 str 检查 6 个 enum 值
    sqls = [str(c.sqltext) for c in constraints]
    joined = " ".join(sqls)
    for status in ("queued", "running", "done", "cancelled", "partial", "error"):
        assert f"'{status}'" in joined, f"CHECK 约束缺 {status}"
```

- [ ] **Step 2: 运行测试,确认失败(ChatTask 不存在 / ChatMessage 无 task_id)**

```bash
cd backend
uv run pytest tests/unit/test_chat_task_model.py -v
```

Expected: 4 个测试全部 FAIL,理由是 `ChatTask` import 错或 `task_id` 列不存在。

- [ ] **Step 3: 写最小实现 — 加 ChatTask 类 + ChatMessage 加列**

修改 `backend/app/models/chat.py`,在 `ChatMessage` 类后面、`LongTermMemory` 之前加新类。同时给 `ChatMessage` 加两列:

```python
# === Patch chat_messages: 加 task_id + status(放在 tool_call_data 之后)===
# 在 ChatMessage 类内 tool_call_data = Column(...) 之后插入:
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(
        String(16),
        nullable=False,
        default="done",
        server_default="done",
    )  # done|partial|cancelled|error
```

紧跟 `ChatMessage` 类后(也就是 `class LongTermMemory(Base):` 之前)新增:

```python
from sqlalchemy import CheckConstraint  # 顶部 import 区补这一行(若未导入)


class ChatTask(Base):
    """聊天任务模型(Plan 1 落地;Plan 2 由 Celery worker 写入)"""

    __tablename__ = "chat_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(
        String(16),
        nullable=False,
        default="queued",
        server_default="queued",
    )  # queued|running|done|cancelled|partial|error
    langgraph_thread_id = Column(String(128), nullable=False)
    langgraph_checkpoint_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    last_event_seq = Column(BigInteger, nullable=False, default=0, server_default="0")
    initial_prompt_message_id = Column(UUID(as_uuid=True), nullable=True)
    parent_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','cancelled','partial','error')",
            name="chat_tasks_status_check",
        ),
    )
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
cd backend
uv run pytest tests/unit/test_chat_task_model.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: 跑全 backend 测试套件,确认没破坏现有 model 注册(barrel import 守护)**

```bash
cd backend
uv run pytest tests/unit/test_smoke.py tests/unit/test_chat_graph.py -v
```

Expected: 全 PASS。如果有 import error,通常是 `models/__init__.py` 没 re-export ChatTask;补一下:

```bash
grep -n "ChatTask\|from app.models" backend/app/models/__init__.py
```

如有需要,在 `backend/app/models/__init__.py` 加 `from app.models.chat import ChatTask` 让 `Base.metadata.create_all` 能扫到。

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/chat.py backend/app/models/__init__.py backend/tests/unit/test_chat_task_model.py
git commit -m "feat(chat-persistence): ChatTask ORM model + chat_messages 加 task_id/status 列"
```

---

## Task 2: lifespan create_all 自动建表 — 验证 + 守护测试

**Spec 锚:** § 4 末「不动 alembic,用 create_all」(对齐 `v0.9.x-no-alembic-until-db-unify` memory)

**Files:**
- Modify: `backend/app/app_main.py:84-89`(已有 create_all,但需要验证 ChatTask 被注册)
- Test: `backend/tests/unit/test_smoke.py`(扩展)

- [ ] **Step 1: 写失败测试 — smoke 测试覆盖 chat_tasks 表存在**

打开 `backend/tests/unit/test_smoke.py`,在末尾添加(若文件结构是 pytest 函数集而非 class,顺序添加;若是 class,加 method):

```python
def test_chat_tasks_table_registered_in_metadata() -> None:
    """守护:ChatTask 必须在 Base.metadata 中注册,否则 lifespan create_all 不会建表。"""
    from app.core.database import Base
    table_names = set(Base.metadata.tables.keys())
    assert "chat_tasks" in table_names, (
        f"chat_tasks 未注册到 Base.metadata。当前注册的表: {sorted(table_names)}"
    )
```

- [ ] **Step 2: 运行测试,确认通过(Task 1 应该已经让 ChatTask 被 import 注册)**

```bash
cd backend
uv run pytest tests/unit/test_smoke.py::test_chat_tasks_table_registered_in_metadata -v
```

Expected: PASS。如果 FAIL,回 Task 1 step 5 确认 `models/__init__.py` 有 re-export。

- [ ] **Step 3: 手动验证 — 真 PG 起 server 触发 create_all**

```bash
# 起一个 PG fixture container(或用 docker-compose)
cd backend
uv run poe dev &
SERVER_PID=$!
sleep 5

# 用 psql 检查表是否真的建了
PGPASSWORD=$(grep POSTGRES_PASSWORD .env | cut -d= -f2) psql \
  -h localhost -U $(grep POSTGRES_USER .env | cut -d= -f2) \
  -d $(grep POSTGRES_DB .env | cut -d= -f2) \
  -c "\d chat_tasks"

# 应该看到:
#   id, session_id, user_id, status, langgraph_thread_id, ...
#   CHECK constraint: chat_tasks_status_check
#   indexes (idx_chat_tasks_session 在 Task 3 加,这里看不到)

# 同时验证 chat_messages 加列成功
PGPASSWORD=... psql ... -c "\d chat_messages" | grep -E "task_id|status"

# 关掉 server
kill $SERVER_PID
```

Expected:`\d chat_tasks` 列出全部 13 列;`\d chat_messages` 看到 `task_id` 和 `status` 列。

**注意**:`Base.metadata.create_all` **不会改已有表**(create_all 是幂等且只新建,不 alter)。如果 chat_messages 在测试前已存在且没这两列,需要手动 ALTER。这种情况下:

```bash
# 手动 ALTER(只在已有 chat_messages 且无 task_id 时执行)
PGPASSWORD=... psql ... -c "
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES chat_tasks(id) ON DELETE SET NULL;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'done';
"
```

把这一段 SQL 也写到 plan 的 task 完成清单,作为 dogfood 时的对照。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/unit/test_smoke.py
git commit -m "test(chat-persistence): smoke 守护 chat_tasks 表注册到 metadata"
```

---

## Task 3: 实现 ChatTaskRepo — 6 状态机 CRUD

**Spec 锚:** § 3 组件清单 — `ChatTaskRepo`;§ 4.3 状态机

**Files:**
- Create: `backend/app/services/chat_task_repo.py`
- Test: `backend/tests/unit/test_chat_task_repo.py`

- [ ] **Step 1: 写失败测试 — 9 个 repo 方法(覆盖全状态机)**

新建 `backend/tests/unit/test_chat_task_repo.py`:

```python
"""ChatTaskRepo 单元测试 — 6 状态机 + Repo 方法集。

测试策略:用 in-memory sqlite + ChatTask 复用 PG schema(UUID 自动降级 string)。
覆盖 9 个方法 + 状态机非法转换防护。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.chat import ChatSession, ChatTask
from app.services.chat_task_repo import ChatTaskRepo


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session(session_factory):
    """种一个 ChatSession 让 ChatTask 的 FK 不报错。"""
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


@pytest.mark.asyncio
async def test_create_queued_inserts_row(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    user_id = uuid.uuid4()
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=user_id,
        langgraph_thread_id=f"{user_id}:{seeded_session}",
        initial_prompt_message_id=None,
    )
    assert task.status == "queued"
    assert task.session_id == seeded_session
    assert task.user_id == user_id
    assert task.langgraph_thread_id == f"{user_id}:{seeded_session}"
    assert task.last_event_seq == 0
    assert task.started_at is None


@pytest.mark.asyncio
async def test_mark_running_sets_started_at(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t1",
        initial_prompt_message_id=None,
    )
    before = datetime.utcnow()
    await repo.mark_running(task.id)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "running"
    assert fetched.started_at is not None
    assert fetched.started_at >= before


@pytest.mark.asyncio
async def test_mark_done_sets_finished_at_and_checkpoint(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_done(task.id, langgraph_checkpoint_id="ckpt-abc")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "done"
    assert fetched.finished_at is not None
    assert fetched.langgraph_checkpoint_id == "ckpt-abc"


@pytest.mark.asyncio
async def test_mark_partial_keeps_checkpoint(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_partial(task.id, langgraph_checkpoint_id="ckpt-x")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "partial"
    assert fetched.langgraph_checkpoint_id == "ckpt-x"


@pytest.mark.asyncio
async def test_mark_cancelled_no_checkpoint_needed(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_cancelled(task.id, langgraph_checkpoint_id=None)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "cancelled"
    assert fetched.langgraph_checkpoint_id is None


@pytest.mark.asyncio
async def test_mark_error_sets_error_message(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(task.id)
    await repo.mark_error(task.id, error_message="LLM 429 rate limited")
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.status == "error"
    assert fetched.error_message == "LLM 429 rate limited"


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_unknown(session_factory):
    repo = ChatTaskRepo(session_factory)
    fetched = await repo.get_by_id(uuid.uuid4())
    assert fetched is None


@pytest.mark.asyncio
async def test_find_active_for_session_returns_queued_or_running(session_factory, seeded_session):
    repo = ChatTaskRepo(session_factory)
    user_id = uuid.uuid4()
    t1 = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=user_id,
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.mark_running(t1.id)

    active = await repo.find_active_for_session(seeded_session)
    assert active is not None
    assert active.id == t1.id

    await repo.mark_done(t1.id, langgraph_checkpoint_id=None)
    active_after = await repo.find_active_for_session(seeded_session)
    assert active_after is None


@pytest.mark.asyncio
async def test_bump_seq_increments_last_event_seq(session_factory, seeded_session):
    """Plan 2 用,Plan 1 先实现 + 测,避免 Plan 2 时翻 schema。"""
    repo = ChatTaskRepo(session_factory)
    task = await repo.create_queued(
        session_id=str(seeded_session),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.bump_seq(task.id, delta=5)
    fetched = await repo.get_by_id(task.id)
    assert fetched is not None
    assert fetched.last_event_seq == 5

    await repo.bump_seq(task.id, delta=3)
    fetched2 = await repo.get_by_id(task.id)
    assert fetched2 is not None
    assert fetched2.last_event_seq == 8
```

- [ ] **Step 2: 运行测试,确认全部失败(ChatTaskRepo 不存在)**

```bash
cd backend
uv run pytest tests/unit/test_chat_task_repo.py -v
```

Expected: 9 个 FAIL,理由 `ModuleNotFoundError: No module named 'app.services.chat_task_repo'`。

- [ ] **Step 3: 写最小实现 — `chat_task_repo.py`**

新建 `backend/app/services/chat_task_repo.py`:

```python
"""ChatTaskRepo — chat_tasks 表 CRUD + 6 状态机迁移。

设计目标:
- 状态机方法集(mark_running / mark_done / mark_partial / mark_cancelled / mark_error)幂等且只前进
- bump_seq 用于 Plan 2 的事件序号 + stale 探测
- find_active_for_session 用于 GET /chats/{sid} 返回 active_task_id

异常处理:不在 repo 层抛业务异常,只在 SQLAlchemy 层报错;调用方决定如何处理。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatTask

_ACTIVE_STATUSES = ("queued", "running")


class ChatTaskRepo:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._sf = session_factory

    async def create_queued(
        self,
        *,
        session_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        langgraph_thread_id: str,
        initial_prompt_message_id: uuid.UUID | None,
        parent_task_id: uuid.UUID | None = None,
    ) -> ChatTask:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        uid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        async with self._sf() as sess:
            row = ChatTask(
                id=uuid.uuid4(),
                session_id=sid,
                user_id=uid,
                status="queued",
                langgraph_thread_id=langgraph_thread_id,
                initial_prompt_message_id=initial_prompt_message_id,
                parent_task_id=parent_task_id,
            )
            sess.add(row)
            await sess.commit()
            await sess.refresh(row)
            return row

    async def mark_running(self, task_id: uuid.UUID) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(status="running", started_at=datetime.utcnow())
            )
            await sess.commit()

    async def mark_done(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="done",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_partial(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="partial",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_cancelled(
        self, task_id: uuid.UUID, *, langgraph_checkpoint_id: str | None
    ) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="cancelled",
                    finished_at=datetime.utcnow(),
                    langgraph_checkpoint_id=langgraph_checkpoint_id,
                )
            )
            await sess.commit()

    async def mark_error(self, task_id: uuid.UUID, *, error_message: str) -> None:
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(
                    status="error",
                    finished_at=datetime.utcnow(),
                    error_message=error_message,
                )
            )
            await sess.commit()

    async def get_by_id(self, task_id: uuid.UUID) -> ChatTask | None:
        async with self._sf() as sess:
            return await sess.get(ChatTask, task_id)

    async def find_active_for_session(
        self, session_id: uuid.UUID
    ) -> ChatTask | None:
        """返回 session 内最新的 queued/running 任务。最多一个(单 user 单 session 串行)。"""
        async with self._sf() as sess:
            stmt = (
                select(ChatTask)
                .where(
                    and_(
                        ChatTask.session_id == session_id,
                        ChatTask.status.in_(_ACTIVE_STATUSES),
                    )
                )
                .order_by(desc(ChatTask.created_at))
                .limit(1)
            )
            return (await sess.execute(stmt)).scalar_one_or_none()

    async def bump_seq(self, task_id: uuid.UUID, *, delta: int = 1) -> None:
        """递增 last_event_seq。Plan 2 用,Plan 1 先实现 + 测。"""
        async with self._sf() as sess:
            await sess.execute(
                update(ChatTask)
                .where(ChatTask.id == task_id)
                .values(last_event_seq=ChatTask.last_event_seq + delta)
            )
            await sess.commit()
```

- [ ] **Step 4: 运行测试,确认全部通过**

```bash
cd backend
uv run pytest tests/unit/test_chat_task_repo.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: 跑 mypy + ruff 守护类型与风格**

```bash
cd backend
uv run mypy app/services/chat_task_repo.py
uv run ruff check app/services/chat_task_repo.py tests/unit/test_chat_task_repo.py
uv run ruff format --check app/services/chat_task_repo.py tests/unit/test_chat_task_repo.py
```

Expected:全 PASS。若 ruff format 报 diff,跑 `uv run ruff format <files>` 修补。

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chat_task_repo.py backend/tests/unit/test_chat_task_repo.py
git commit -m "feat(chat-persistence): ChatTaskRepo 6 状态机 + 9 个 method + L0 test"
```

---

## Task 4: ChatSessionRepo 扩展 — append_message 接 task / find_active_task

**Spec 锚:** § 3 组件清单 — `chat_session_repo`(改) + `find_active_task`

**Files:**
- Modify: `backend/app/services/chat_session_repo.py:72-103`
- Test: `backend/tests/unit/test_chat_session_repo_extensions.py` (新)

- [ ] **Step 1: 写失败测试 — append_message 接受 task_id/status,find_active_task 返回 active task**

新建 `backend/tests/unit/test_chat_session_repo_extensions.py`:

```python
"""ChatSessionRepo Plan 1 扩展测试。

新增:
- append_message(task_id=..., status=...) 兼容现有签名,新参数可选
- find_active_task_for_session(sid) 委托 ChatTaskRepo 实现
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.chat import ChatSession
from app.services.chat_session_repo import ChatSessionRepo
from app.services.chat_task_repo import ChatTaskRepo


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    sid = uuid.uuid4()
    async with session_factory() as sess:
        sess.add(ChatSession(id=sid, user_id=None, title="t"))
        await sess.commit()
    return sid


@pytest.mark.asyncio
async def test_append_message_without_task_keeps_legacy_behavior(session_factory, seeded):
    """legacy 路径(escalation)不传 task_id 应该照常 work,默认 status=done。"""
    repo = ChatSessionRepo(session_factory)
    msg = await repo.append_message(
        session_id=str(seeded),
        role="user",
        content="hello",
    )
    assert msg.task_id is None
    assert msg.status == "done"


@pytest.mark.asyncio
async def test_append_message_with_task_id_and_partial_status(session_factory, seeded):
    """Plan 1 新路径:落 assistant 消息时关联 task + 标 partial 状态。"""
    repo = ChatSessionRepo(session_factory)
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    msg = await repo.append_message(
        session_id=str(seeded),
        role="assistant",
        content="partial answer",
        task_id=task.id,
        status="partial",
    )
    assert msg.task_id == task.id
    assert msg.status == "partial"


@pytest.mark.asyncio
async def test_find_active_task_for_session_no_active(session_factory, seeded):
    repo = ChatSessionRepo(session_factory)
    active = await repo.find_active_task_for_session(seeded)
    assert active is None


@pytest.mark.asyncio
async def test_find_active_task_for_session_returns_running(session_factory, seeded):
    repo = ChatSessionRepo(session_factory)
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    active = await repo.find_active_task_for_session(seeded)
    assert active is not None
    assert active.id == task.id


@pytest.mark.asyncio
async def test_list_messages_includes_task_and_status(session_factory, seeded):
    """list_messages 返回的 ChatMessage 应该带 task_id 和 status 字段(model 已有,这里守护 serialize 路径)。"""
    repo = ChatSessionRepo(session_factory)
    task_repo = ChatTaskRepo(session_factory)
    task = await task_repo.create_queued(
        session_id=str(seeded),
        user_id=uuid.uuid4(),
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await repo.append_message(
        session_id=str(seeded),
        role="assistant",
        content="ans",
        task_id=task.id,
        status="done",
    )
    msgs = await repo.list_messages(str(seeded))
    assert len(msgs) == 1
    assert msgs[0].task_id == task.id
    assert msgs[0].status == "done"
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
cd backend
uv run pytest tests/unit/test_chat_session_repo_extensions.py -v
```

Expected: 5 FAIL —— `append_message` 签名不接受 `task_id`/`status`;`find_active_task_for_session` 方法不存在。

- [ ] **Step 3: 改 `chat_session_repo.py` — 扩展 append_message 签名 + 新增 find_active_task_for_session**

修改 `backend/app/services/chat_session_repo.py`:

```python
# 顶部 import 区添加(若未导入):
from app.services.chat_task_repo import ChatTaskRepo  # noqa: I001 — Plan 1 新增
from app.models.chat import ChatTask  # noqa: I001
```

替换现有 `append_message` 方法签名 + body:

```python
    async def append_message(
        self,
        session_id: str,
        role: Literal["user", "assistant", "tool"],
        content: str,
        message_type: str = "text",
        tool_call_data: dict[str, Any] | None = None,
        research_report_id: str | None = None,
        research_report_summary: str | None = None,
        *,
        task_id: uuid.UUID | None = None,
        status: Literal["done", "partial", "cancelled", "error"] = "done",
    ) -> ChatMessage:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            row = ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role=role,
                content=content,
                message_type=message_type,
                tool_call_data=tool_call_data,
                research_report_id=research_report_id,
                research_report_summary=research_report_summary,
                task_id=task_id,
                status=status,
            )
            sess.add(row)
            await sess.execute(
                update(ChatSession)
                .where(ChatSession.id == sid)
                .values(updated_at=datetime.utcnow())
            )
            await sess.commit()
            await sess.refresh(row)
            return row
```

在类的末尾追加:

```python
    async def find_active_task_for_session(
        self, session_id: uuid.UUID | str
    ) -> ChatTask | None:
        """委托 ChatTaskRepo;放在 ChatSessionRepo 作为前端 single endpoint(/chats/{sid}) 的便利方法。"""
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        task_repo = ChatTaskRepo(self._sf)
        return await task_repo.find_active_for_session(sid)
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
cd backend
uv run pytest tests/unit/test_chat_session_repo_extensions.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: 守护现有 chat_session_repo 测试没破坏**

```bash
cd backend
uv run pytest tests/unit/test_chat_session_repo*.py tests/integration/test_chats_router.py -v
```

Expected:全 PASS。若 `test_chats_router.py` 失败,通常是 mocking 没传新参数;**这里允许失败,Task 7 会改 chats router 来兼容**。先把失败列出来作为 Task 7 起点:

```bash
uv run pytest tests/integration/test_chats_router.py -v 2>&1 | grep FAIL
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chat_session_repo.py backend/tests/unit/test_chat_session_repo_extensions.py
git commit -m "feat(chat-persistence): ChatSessionRepo 扩展 — append_message 接 task / find_active_task"
```

---

## Task 5: POST /api/v0/chat 入口 — INSERT user message + create chat_task

**Spec 锚:** § 5.1 Scenario A step [1];§ 3 组件清单 — POST `/chat` 改

**Files:**
- Modify: `backend/app/router/chat.py:557` 及附近(POST endpoint handler)
- Test: `backend/tests/integration/test_chat_persistence_plan1.py` (新)

- [ ] **Step 1: 写失败测试 — POST /chat 后 chat_tasks + chat_messages(user role) 应该有新行**

新建 `backend/tests/integration/test_chat_persistence_plan1.py`:

```python
"""Plan 1 集成测试:POST /chat 落 user + 跑完落 assistant + GET /chats 返回 active_task_id。

这是 L1 集成测试 — 用 PG fixture(参考 backend/tests/integration/conftest.py 已有 pg_session_factory),
LLM 走 cassette / mock,不依赖 Celery / Redis(Plan 1 范围)。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_chat_creates_user_message_and_task(
    chat_test_client: AsyncClient,
    pg_session_factory,  # fixture from conftest.py
):
    """发一次 chat → 应有:1 个 chat_task(running 然后 done)+ 2 条 chat_messages(user + assistant)。"""
    sid = str(uuid.uuid4())  # 假设 session 已存在(或 test client 自动创建)
    resp = await chat_test_client.post(
        "/api/v0/chat",
        json={"session_id": sid, "message": "hello"},
    )
    assert resp.status_code == 200

    # 消费完整 SSE 流(简化:读完整 response body 也行,因为我们不测流式而测落库)
    async for _ in resp.aiter_lines():
        pass

    # 验证 DB
    from app.services.chat_session_repo import ChatSessionRepo
    from app.services.chat_task_repo import ChatTaskRepo

    msg_repo = ChatSessionRepo(pg_session_factory)
    task_repo = ChatTaskRepo(pg_session_factory)

    messages = await msg_repo.list_messages(sid)
    assert len(messages) == 2, f"应该有 2 条消息(user + assistant),实际 {len(messages)}"
    assert messages[0].role == "user"
    assert messages[0].content == "hello"
    assert messages[1].role == "assistant"
    assert messages[1].status == "done"
    assert messages[1].task_id is not None

    # task 应该已经 mark_done
    task = await task_repo.get_by_id(messages[1].task_id)
    assert task is not None
    assert task.status == "done"
    assert task.finished_at is not None
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
cd backend
uv run pytest tests/integration/test_chat_persistence_plan1.py::test_post_chat_creates_user_message_and_task -v
```

Expected: FAIL — 当前 POST /chat 不落 user message,也不创建 chat_task。assertion error 在 `assert len(messages) == 2`。

- [ ] **Step 3: 读现状 — 看 chat.py:557 当前 POST endpoint 怎么走**

```bash
grep -n "POST\|_stream_chat\|append_message\|@router" backend/app/router/chat.py | head -20
```

记下:
- 入口函数名 + 行号(`@router.post("/api/v0/chat")` 那行下面)
- `_stream_chat()` 在哪行

- [ ] **Step 4: 改 POST /chat handler — 入口落 user + 创建 task**

在 `backend/app/router/chat.py` 的 POST /chat handler 入口(在调用 `_stream_chat` 之前)添加:

```python
# === Plan 1 新增 — 入口落 user message + 创建 chat_task ===
from app.services.chat_task_repo import ChatTaskRepo  # 顶部 import

# 在 handler body 内,在打开 SSE StreamingResponse 之前:
chat_session_repo = ChatSessionRepo(request.app.state._chat_session_factory)
chat_task_repo = ChatTaskRepo(request.app.state._chat_session_factory)

# 1. 落 user message
user_msg = await chat_session_repo.append_message(
    session_id=body.session_id,
    role="user",
    content=body.message,
    status="done",
)

# 2. 创建 chat_task
task = await chat_task_repo.create_queued(
    session_id=body.session_id,
    user_id=user.id,
    langgraph_thread_id=f"{user.id}:{body.session_id}",
    initial_prompt_message_id=user_msg.id,
)
await chat_task_repo.mark_running(task.id)

# 3. 把 task_id 透传给 _stream_chat(供 finally 块用)
# 改 _stream_chat 签名(下面 Step 5)
```

**注意**:`request.app.state._chat_session_factory` 是 `app_main.py:211` 创建的 async sessionmaker。如果 attribute 名不同,grep 验证一下:

```bash
grep -n "_chat_session_factory\|chat_session_factory\|async_session" backend/app/app_main.py
```

- [ ] **Step 5: 改 `_stream_chat` 签名,接收 task_id,在 finally 块 mark_done + 落 assistant**

修改 `backend/app/router/chat.py` 内 `_stream_chat` 函数签名 + 末尾:

```python
async def _stream_chat(
    *,
    request: Request,
    user: AuthUser,
    body: ChatRequest,
    task_id: uuid.UUID,  # <-- Plan 1 新增
    ...
) -> AsyncGenerator[bytes, None]:
    chat_session_repo = ChatSessionRepo(request.app.state._chat_session_factory)
    chat_task_repo = ChatTaskRepo(request.app.state._chat_session_factory)

    final_content: list[str] = []  # 累积 assistant 完整答复
    final_status: Literal["done", "error"] = "done"
    error_msg: str | None = None
    checkpoint_id: str | None = None

    try:
        async for event in graph.astream_events(...):
            # ... 现有 _adapt_event 逻辑保留 ...
            adapted = _adapt_event(event)
            if adapted is None:
                continue
            yield _sse_format(adapted).encode()

            # === Plan 1 新增:累积 assistant 内容 ===
            if adapted.get("type") == "text_chunk":
                final_content.append(adapted.get("content", ""))
            elif adapted.get("type") == "done":
                # 从 event 中提取 checkpoint_id(若 LangGraph 在 done 时提供)
                try:
                    state = await graph.aget_state(config)
                    checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
                except Exception:
                    checkpoint_id = None

    except Exception as e:
        final_status = "error"
        error_msg = str(e)[:500]
        # 把错误也作为最后一个 SSE 事件下发,让前端能感知
        yield _sse_format({"type": "error", "message": error_msg}).encode()

    finally:
        # === Plan 1 新增:无论成功失败都 commit assistant message + mark task ===
        full_content = "".join(final_content)
        if final_status == "done":
            await chat_session_repo.append_message(
                session_id=body.session_id,
                role="assistant",
                content=full_content,
                task_id=task_id,
                status="done",
            )
            await chat_task_repo.mark_done(task_id, langgraph_checkpoint_id=checkpoint_id)
        else:
            # error
            await chat_session_repo.append_message(
                session_id=body.session_id,
                role="assistant",
                content=full_content,  # 已生成的部分(若有)
                task_id=task_id,
                status="error",
            )
            await chat_task_repo.mark_error(task_id, error_message=error_msg or "unknown error")
```

**说明**:
- `_adapt_event` 现有事件类型见 `chat.py:292-342`;若没有 `text_chunk` 类型,改成实际类型名(可能是 `on_chat_model_stream` / `text_delta` 等)。先 grep 看现状:

```bash
grep -n "_adapt_event\|return.*type" backend/app/router/chat.py | head -30
```

- `_sse_format` 是 SSE 序列化的辅助函数;若不存在,用 `f"data: {json.dumps(adapted)}\n\n"`。

- [ ] **Step 6: 在 POST handler 把 task_id 透传给 `_stream_chat`**

```python
return StreamingResponse(
    _stream_chat(
        request=request,
        user=user,
        body=body,
        task_id=task.id,  # <-- 新增
        ...
    ),
    media_type="text/event-stream",
)
```

- [ ] **Step 7: 运行集成测试,确认通过**

```bash
cd backend
uv run pytest tests/integration/test_chat_persistence_plan1.py::test_post_chat_creates_user_message_and_task -v
```

Expected: PASS。若 FAIL,常见原因:
- `_chat_session_factory` attribute 名不对 → grep app_main.py 找实际名
- LLM cassette 没录 → 用现有 chat L1 测试的 cassette pattern
- `_adapt_event` 没产生 `text_chunk` → 看实际 event 名,调整累积逻辑

- [ ] **Step 8: 跑全 chat 相关现有测试,守护不破坏**

```bash
cd backend
uv run pytest tests/integration/test_chat_router_*.py tests/integration/test_chats_router.py -v
```

Expected:全 PASS。若 `test_chat_router_sse.py` 有 mock 用的旧签名,这里允许 FAIL,但要记下哪些 case 需要 Task 7 修。

- [ ] **Step 9: Commit**

```bash
git add backend/app/router/chat.py backend/tests/integration/test_chat_persistence_plan1.py
git commit -m "feat(chat-persistence): POST /chat 入口落 user msg + create chat_task;finally 落 assistant + mark"
```

---

## Task 6: 错误路径测试 — LLM 抛异常时仍要落 assistant + mark_error

**Spec 锚:** § 7 错误处理矩阵第一行(LLM API 报错)

**Files:**
- Modify: `backend/tests/integration/test_chat_persistence_plan1.py`(扩展)

- [ ] **Step 1: 写失败测试 — 强制 LLM mock 抛异常,验证 finally 块仍落库 + task=error**

在 `backend/tests/integration/test_chat_persistence_plan1.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_post_chat_llm_error_still_commits_assistant_and_marks_task(
    chat_test_client: AsyncClient,
    pg_session_factory,
    monkeypatch,
):
    """LLM 抛 RuntimeError → finally 块仍要 commit assistant(status=error)+ mark task=error。"""
    # 让 LLMService.chat 抛异常(用现有 LLM mock fixture 改造)
    from app.services.llm_service import LLMService

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated LLM 429")

    monkeypatch.setattr(LLMService, "chat", boom)

    sid = str(uuid.uuid4())
    resp = await chat_test_client.post(
        "/api/v0/chat",
        json={"session_id": sid, "message": "trigger boom"},
    )
    # SSE 流应该开了(可能是 200)但内容是 error 事件
    assert resp.status_code in (200, 500)

    async for _ in resp.aiter_lines():
        pass

    # 验证 DB
    from app.services.chat_session_repo import ChatSessionRepo
    from app.services.chat_task_repo import ChatTaskRepo
    msg_repo = ChatSessionRepo(pg_session_factory)
    task_repo = ChatTaskRepo(pg_session_factory)

    messages = await msg_repo.list_messages(sid)
    # 至少有 user message;assistant message 即使 content 为空也应该存在(status=error)
    assert len(messages) >= 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].status == "error"

    task = await task_repo.get_by_id(messages[1].task_id)
    assert task is not None
    assert task.status == "error"
    assert task.error_message is not None
    assert "simulated LLM 429" in task.error_message
```

- [ ] **Step 2: 运行测试,确认通过(Task 5 finally 块已覆盖 error 路径)**

```bash
cd backend
uv run pytest tests/integration/test_chat_persistence_plan1.py::test_post_chat_llm_error_still_commits_assistant_and_marks_task -v
```

Expected: PASS。

若 FAIL,原因可能是:
- `monkeypatch.setattr(LLMService, "chat", boom)` 没拦截真路径 → grep 找 chat agent 实际调用 LLM 的入口
- `_stream_chat` 把异常向 StreamingResponse 抛出去太早,finally 还没跑 → 检查 Task 5 step 5 的 try/finally 嵌套

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_chat_persistence_plan1.py
git commit -m "test(chat-persistence): LLM error 时 finally 落 assistant + mark task=error"
```

---

## Task 7: GET /api/v0/chats/{sid} — 返回 messages + active_task_id

**Spec 锚:** § 5.2 Scenario B step 2(关页面 30 分钟后重开);§ 3 组件清单 — chats.py GET

**Files:**
- Modify: `backend/app/router/chats.py:58-77`
- Modify: `backend/tests/integration/test_chats_router.py`(可能需要;取决于现有 schema)

- [ ] **Step 1: 写失败测试 — GET /chats/{sid} 返回 active_task_id 字段**

在 `backend/tests/integration/test_chat_persistence_plan1.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_get_chat_returns_active_task_id_when_inflight(
    chat_test_client: AsyncClient,
    pg_session_factory,
):
    """造一个 status=running 的 chat_task,GET /chats/{sid} 应该返回 active_task_id。"""
    from app.services.chat_session_repo import ChatSessionRepo
    from app.services.chat_task_repo import ChatTaskRepo

    sid = uuid.uuid4()
    user_id = uuid.uuid4()
    # 直接造一个 session + running task(绕过 POST /chat)
    repo = ChatSessionRepo(pg_session_factory)
    await repo.create_session(user_id=str(user_id), title="测试")
    # 重新查 session_id(create_session 没返回?用 list_for_user)
    sessions = await repo.list_for_user(str(user_id))
    sid_real = sessions[0].id

    task_repo = ChatTaskRepo(pg_session_factory)
    task = await task_repo.create_queued(
        session_id=sid_real,
        user_id=user_id,
        langgraph_thread_id=f"{user_id}:{sid_real}",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)

    # 调 GET /chats/{sid}
    resp = await chat_test_client.get(f"/api/v0/chats/{sid_real}")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert "active_task_id" in data
    assert data["active_task_id"] == str(task.id)


@pytest.mark.asyncio
async def test_get_chat_returns_null_active_task_when_done(
    chat_test_client: AsyncClient,
    pg_session_factory,
):
    """task 已 done → active_task_id 应为 null。"""
    from app.services.chat_session_repo import ChatSessionRepo
    from app.services.chat_task_repo import ChatTaskRepo

    user_id = uuid.uuid4()
    repo = ChatSessionRepo(pg_session_factory)
    await repo.create_session(user_id=str(user_id), title="测试")
    sessions = await repo.list_for_user(str(user_id))
    sid_real = sessions[0].id

    task_repo = ChatTaskRepo(pg_session_factory)
    task = await task_repo.create_queued(
        session_id=sid_real,
        user_id=user_id,
        langgraph_thread_id="t",
        initial_prompt_message_id=None,
    )
    await task_repo.mark_running(task.id)
    await task_repo.mark_done(task.id, langgraph_checkpoint_id=None)

    resp = await chat_test_client.get(f"/api/v0/chats/{sid_real}")
    data = resp.json()
    assert data.get("active_task_id") is None
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
cd backend
uv run pytest tests/integration/test_chat_persistence_plan1.py::test_get_chat_returns_active_task_id_when_inflight tests/integration/test_chat_persistence_plan1.py::test_get_chat_returns_null_active_task_when_done -v
```

Expected: 2 FAIL —— `active_task_id` 字段不在响应里。

- [ ] **Step 3: 改 chats.py:58 `get_chat` — 加 active_task_id 字段**

修改 `backend/app/router/chats.py:58-77`:

```python
@router.get("/{session_id}")
async def get_chat(
    session_id: str,
    repo: ChatSessionRepo = Depends(get_repo),
) -> dict[str, Any]:
    """获取单个 session 的消息列表 + 当前 active task(若有)。

    Plan 1 新增 active_task_id 字段(可能为 null,表示当前无 in-flight task)。
    Plan 2 会再加 last_event_seq + stream_url。
    """
    session_uuid = uuid.UUID(session_id)
    messages = await repo.list_messages(session_id)
    active_task = await repo.find_active_task_for_session(session_uuid)

    return {
        "session_id": session_id,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "message_type": m.message_type,
                "tool_call_data": m.tool_call_data,
                "task_id": str(m.task_id) if m.task_id else None,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "active_task_id": str(active_task.id) if active_task else None,
    }
```

**说明**:如果现有 `get_chat` 返回的字段更多(比如 references_data),保留它们,只在外层加 `active_task_id`。先 read 看现状:

```bash
sed -n '58,77p' backend/app/router/chats.py
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
cd backend
uv run pytest tests/integration/test_chat_persistence_plan1.py::test_get_chat_returns_active_task_id_when_inflight tests/integration/test_chat_persistence_plan1.py::test_get_chat_returns_null_active_task_when_done -v
```

Expected: 2 PASS.

- [ ] **Step 5: 守护现有 chats_router 测试**

```bash
cd backend
uv run pytest tests/integration/test_chats_router.py -v
```

Expected:基本 PASS。若有 assertion 期望旧 schema(没有 active_task_id),改测试 expect 包含新字段。

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/chats.py backend/tests/integration/test_chat_persistence_plan1.py
git commit -m "feat(chat-persistence): GET /chats/{sid} 返回 active_task_id 字段"
```

---

## Task 8: 前端 useChatSSE 修补 — 去掉假 reconnect,断流时拉历史

**Spec 锚:** § 1.2 现状失效面第三项(前端假 reconnect 后端 404);§ 9.2 表「前端 playwright e2e 留 v1.x」

**Files:**
- Modify: `frontend/src/hooks/useChatSSE.ts:143`
- Modify: `frontend/src/api/chatApi.ts:62-69`
- Modify: `frontend/src/hooks/__tests__/useChatSSE.test.tsx:72-110`(F6 reconnect describe 块)

- [ ] **Step 1: 读现状 — 当前重连逻辑长啥样**

```bash
sed -n '130,160p' frontend/src/hooks/useChatSSE.ts
```

记下:
- `while (!doneSeen && !ac.signal.aborted)` 循环结构
- `buildChatStreamUrl(sessionId, currentChatState.last_seq)` 的调用点
- 退避逻辑

- [ ] **Step 2: 写失败测试 — 流断了应该不再重连 `/chat/stream/:id`,而是 reload `/chats/:id`**

修改 `frontend/src/hooks/__tests__/useChatSSE.test.tsx`,在 `describe('useChatSSE — F6 reconnect (last_event_id)')` 内,替换原有 reconnect 测试:

```typescript
// 删除原 it('reconnects to /stream/:id?last_event_id=N when initial stream closes early', ...)
// 改为:

  it('Plan 1: 不再调用 /chat/stream/:id 重连;断流后 reload 历史 messages', async () => {
    let reconnectAttempted = false
    let chatsCalled = false

    server.use(
      http.get(`${API_BASE}/api/v0/chat/stream/s1`, () => {
        reconnectAttempted = true
        return new Response('', { status: 404 })
      }),
      http.get(`${API_BASE}/api/v0/chats/s1`, () => {
        chatsCalled = true
        return HttpResponse.json({
          session_id: 's1',
          messages: [
            { id: 'm1', role: 'user', content: 'hi', status: 'done', task_id: null },
            { id: 'm2', role: 'assistant', content: 'hello back', status: 'done', task_id: 't1' },
          ],
          active_task_id: null,
        })
      }),
    )

    const { result } = renderHook(() => useChatSSE())
    // 模拟初始流早断(第一次 POST 返回 done 之前 conn drop)
    await act(async () => {
      await result.current.sendMessage({ sessionId: 's1', message: 'hi' })
    })

    expect(reconnectAttempted).toBe(false)  // 不再调假 reconnect endpoint
    expect(chatsCalled).toBe(true)          // 改为 reload 历史
    const s = snapshot(currentChatState)
    expect(s.messages?.length).toBeGreaterThanOrEqual(2)
  })
```

**说明**:精确的 mock 时序、`act` 用法依赖现有 test infra。若 `currentChatState` 是 valtio store,`snapshot()` 拿值;若是 react state,改 `result.current`。

- [ ] **Step 3: 运行测试,确认失败**

```bash
cd frontend
npm test -- useChatSSE
```

Expected: 新 test FAIL —— 当前代码仍会调 `/chat/stream/:id`。

- [ ] **Step 4: 改 `useChatSSE.ts` — 去掉 reconnect 分支,改成 reload 历史**

修改 `frontend/src/hooks/useChatSSE.ts:130-155` 附近的重连循环。**伪代码 → 真实代码**:

```typescript
// === Plan 1 修补:去掉假 reconnect,断流后只 reload 历史 ===
// 原代码(删除):
//   while (!doneSeen && !ac.signal.aborted) {
//     const url = buildChatStreamUrl(sessionId, currentChatState.last_seq)
//     await sleep(computeBackoffMs(...))
//     const res = await fetch(url, { signal: ac.signal })
//     if (!res.ok) continue
//     await consumeStream(res, ...)
//   }

// 新代码(替换):
if (!doneSeen && !ac.signal.aborted) {
  // 不重试 SSE(Plan 2 才会有真正的 stream/{task_id} endpoint)
  // 直接 reload 历史 messages — Plan 1 的 A 档承诺
  try {
    const fresh = await reloadChatMessages(sessionId)
    currentChatState.messages = fresh.messages
    currentChatState.active_task_id = fresh.active_task_id
  } catch (e) {
    // 静默,等下一次用户交互
  }
}
```

- [ ] **Step 5: 改 `chatApi.ts` — 标记 buildChatStreamUrl 为 deprecated,新增 reloadChatMessages**

修改 `frontend/src/api/chatApi.ts`:

```typescript
/**
 * @deprecated Plan 2 重写;Plan 1 不再调用此 URL(后端无 endpoint)。
 *   保留 export 仅为现有测试 import 不破。
 */
export function buildChatStreamUrl(
  sessionId: string,
  lastEventId?: number,
): string {
  const base = apiUrl(`/api/v0/chat/stream/${encodeURIComponent(sessionId)}`)
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}last_event_id=${lastEventId ?? 0}`
}

// === Plan 1 新增 ===
export interface ChatMessageDto {
  id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  status: 'done' | 'partial' | 'cancelled' | 'error'
  task_id: string | null
  message_type?: string
  tool_call_data?: unknown
  created_at?: string
}

export interface ChatHistoryResponse {
  session_id: string
  messages: ChatMessageDto[]
  active_task_id: string | null
}

export async function reloadChatMessages(sessionId: string): Promise<ChatHistoryResponse> {
  const res = await fetch(apiUrl(`/api/v0/chats/${encodeURIComponent(sessionId)}`))
  if (!res.ok) {
    throw new Error(`reloadChatMessages failed: ${res.status}`)
  }
  return res.json()
}
```

- [ ] **Step 6: 修 useChatSSE.ts 顶部 import**

```typescript
import {
  // 原有 imports...
  reloadChatMessages,
} from '../api/chatApi'
```

去掉 `buildChatStreamUrl` 在 useChatSSE 的 import(若现在不再用)。

- [ ] **Step 7: 运行 frontend 测试**

```bash
cd frontend
npm test -- useChatSSE
```

Expected: 新测试 PASS。原有 6 个 useChatSSE 测试,有些可能因为修改了 reconnect 逻辑而 FAIL —— 逐个查看:
- 「reconnects to /stream/:id...」 → 已替换为新版,删除原 case
- 「F6 reconnect (last_event_id)」 describe 块名仍保留,但只剩新 case + 「保留 last_seq state」一类纯 store 测试

- [ ] **Step 8: 跑 frontend 全测试守护**

```bash
cd frontend
npm test
```

Expected:全 PASS。若 `chatApi.test.ts` 还在测 `buildChatStreamUrl` 拼 URL 正确性,保留(只是它现在拼的是个无效 URL,但函数行为还在)。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/hooks/useChatSSE.ts frontend/src/api/chatApi.ts frontend/src/hooks/__tests__/useChatSSE.test.tsx
git commit -m "fix(chat-persistence): 前端去掉假 reconnect /chat/stream/:id;断流改 reload 历史 messages"
```

**Why fix-class**:`feedback_fix_commit_layer_marker` memory 要求 fix 类 commit 加 layer 标记。这次 fix 的是 spec § 1.2 中现状失效面第三项(实现层 bug):

```bash
git commit --amend -m "$(cat <<'EOF'
fix(chat-persistence): 前端去掉假 reconnect /chat/stream/:id;断流改 reload 历史 messages

useChatSSE.ts:143 之前拼 GET /chat/stream/:id?last_event_id=N,
但后端从未实现该 endpoint(只有 POST /chat),生产 404 死循环。
Plan 1 范围:简化为断流时 GET /chats/:id 拉最新历史(A 档承诺);
Plan 2 会重新引入真正的 stream/{task_id} endpoint(C 档)。

原因 layer: impl
EOF
)"
```

---

## Task 9: serve path smoke + dogfood — 验证整条链路在真 server 工作

**Spec 锚:** § 0.3 `feedback_serve_path_no_ci_coverage` memory;Hermes 参考的 DB-as-truth 哲学

**Files:**
- 无新文件;手动 dogfood 命令

- [ ] **Step 1: 起真 server + worker(本 plan 不引 worker,但保持启动方式一致)**

```bash
# Terminal 1:起 backend dev
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/backend
uv run poe dev
```

等待看到 `Uvicorn running on http://0.0.0.0:8000`。

- [ ] **Step 2: 起前端**

```bash
# Terminal 2
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant/frontend
npm run dev
```

- [ ] **Step 3: 浏览器 dogfood — 关页面重开看历史**

1. 打开 `http://localhost:5173`(或 frontend 实际端口)
2. 登录 / 进入 chat 模式
3. 发送一条消息:"你好,介绍一下贵州茅台最近的财报"
4. 等待 assistant 完整回复
5. **关闭整个浏览器窗口**(不只是 tab)
6. 重新打开 `http://localhost:5173`
7. 进入同一 chat session
8. **预期**:能看到完整对话(user 问 + assistant 答),不是空白

如果空白,看:
```bash
# 直接 curl 验证后端
curl -X GET http://localhost:8000/api/v0/chats/<session_id>
# 应该返回 messages 数组有 2 条,active_task_id null
```

如果 curl 看到数据但前端空白,前端 chat list 加载逻辑可能没读 `messages` 字段 → 检查 `ChatPane.tsx` 的初始化路径(本 plan 没改 ChatPane,但若它依赖旧 API 形状可能要小修)。

- [ ] **Step 4: 浏览器 dogfood — 推理中关页面重开**

1. 进入空 chat session
2. 发一个稍长的 prompt:"详细分析中国白酒行业格局并对比茅台和五粮液"
3. **在 assistant 还在输出的时候**关闭浏览器
4. 等 60 秒(让推理在后端跑完;Plan 1 范围内推理不独立于 web,所以 web 不重启的情况下会跑完)
5. 重新打开浏览器进入同一 session
6. **预期**:能看到完整的(已生成的)对话

记录观察:
- 如果 web 进程中途 `uv run poe dev` reload(代码修改触发热重启),推理被打断,assistant message 应该 status=error
- 如果 web 进程一直在,推理跑完,assistant message status=done

- [ ] **Step 5: 浏览器 dogfood — 检查 chat_tasks 行**

```bash
PGPASSWORD=$(grep POSTGRES_PASSWORD backend/.env | cut -d= -f2) psql \
  -h localhost -U $(grep POSTGRES_USER backend/.env | cut -d= -f2) \
  -d $(grep POSTGRES_DB backend/.env | cut -d= -f2) \
  -c "SELECT id, session_id, status, started_at, finished_at, length(error_message) as err_len FROM chat_tasks ORDER BY created_at DESC LIMIT 5;"
```

**预期**:看到 dogfood 期间的 task 行,status 是 `done` 或 `error`,有 `started_at` 和 `finished_at`。

- [ ] **Step 6: 跑全 backend 测试 + frontend 测试守护**

```bash
cd backend
uv run pytest -x --tb=short 2>&1 | tail -30

cd ../frontend
npm test 2>&1 | tail -30
```

Expected:全绿。

- [ ] **Step 7: 跑 mypy + ruff 完整套**

```bash
cd backend
uv run poe ci  # 假设 poe ci 跑 mypy + ruff + pytest;否则分开跑
```

Expected:全绿。

- [ ] **Step 8: 写 dogfood 笔记**

新建 `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan1-dogfood.md`(轻量笔记,不进 git 也行):

```markdown
# Plan 1 Dogfood 笔记

**日期**:<填实际日期>

## 验证场景
- [x] 关页面重开看到完整对话(Scenario A)
- [x] 推理中关页面重开看到部分对话(Scenario B,但本 plan 没 in-flight subscribe,只能看到 task 完成后落库的最终内容)
- [x] chat_tasks 表正确写入 done/error 状态

## 遗留问题(留 Plan 2/3)
- in-flight subscribe(关页面重开继续看流) — Plan 2
- cancel 按钮 — Plan 2
- retry from checkpoint — Plan 3
- stale 探测 — Plan 3

## 观察到的小毛刺
- <填实际观察>
```

- [ ] **Step 9: Commit dogfood 笔记(可选)**

```bash
git add docs/superpowers/plans/2026-05-16-chat-session-persistence-plan1-dogfood.md
git commit -m "docs(chat-persistence): Plan 1 dogfood 笔记 — A 档落地验证"
```

---

## Plan 1 完成验收(self-check)

完成 Task 1-9 后,跑这个清单确认 plan 1 真的 ship:

```bash
# 1. 全测试套绿
cd backend && uv run poe ci
cd ../frontend && npm test

# 2. schema 落地(真 PG 看到表 + 列)
PGPASSWORD=... psql ... -c "\d chat_tasks; \d chat_messages" | grep -E "task_id|status|chat_tasks_status_check"

# 3. 用户感知验证
# 浏览器:关页面 → 重开 → 看到完整历史

# 4. spec § 1.2 三个失效面修复进度
#   - chat 消息不入库 → ✅ 修复(POST /chat 入口 + finally)
#   - 服务端不感知断开 → ❌ 仍未做(Plan 2 引 Celery 解耦)
#   - 前端假 reconnect 404 → ✅ 修复(改 reload 历史)
```

**Plan 1 完成后,准备启动 Plan 2(In-flight Subscribe)**:Celery worker + Redis Streams + 新 stream/cancel/retry endpoint + 打字机渲染。

---

## Self-Review 自审清单

### 1. Spec 覆盖检查

Plan 1 范围内的 spec 锚:
- § 3 组件清单 — ChatTaskRepo、chat_session_repo 改、POST /chat 改、chats.py GET 改、useChatSSE 改:**全覆盖** ✅(Task 3/4/5/7/8)
- § 4 数据模型 — chat_tasks 新表、chat_messages 加列、6 状态机:**全覆盖** ✅(Task 1/2/3)
- § 5.1 Scenario A — 新消息正常路径:**覆盖** ✅(Task 5/6)
- § 5.2 Scenario B — 关页面 30 分重开:**部分覆盖** ✅(Task 9 dogfood;但无 in-flight subscribe,Plan 2 完整覆盖)
- § 7 错误处理矩阵第一行(LLM API 报错):**覆盖** ✅(Task 6)
- § 1.2 三个失效面:**2/3 覆盖**(Plan 2 收尾「服务端不感知断开」)

不在 Plan 1 范围(留 Plan 2/3,有明确文字注明):
- Celery worker / Redis Streams / cancel / retry / stale scanner / 打字机渲染 / L2 chaos

### 2. Placeholder 扫描

无 TBD / TODO / "implement later" / 不带代码的 "添加适当错误处理"。

### 3. 类型一致性

- `ChatTask.status` 6-enum:queued / running / done / cancelled / partial / error → CHECK 约束(Task 1)+ Repo 方法集(Task 3)对齐
- `ChatMessage.status` 4-enum:done / partial / cancelled / error → Task 1 CHECK + Task 4 `append_message` 签名对齐
- `_chat_session_factory` attribute 名:用 grep 验证(Task 5 step 4 提示)
- `find_active_task_for_session`(repo)vs `find_active_for_session`(task_repo):**注意区分** — `ChatSessionRepo.find_active_task_for_session` 是 facade,委托 `ChatTaskRepo.find_active_for_session` 实现(Task 4 step 3 末尾、Task 3 step 3)

### 4. 已知执行风险

- `_chat_session_factory` 在 app.state 上的实际 attribute 名可能与示例不同 — Task 5 step 4 提示 grep 验证
- `_adapt_event` 当前事件类型名未确认 — Task 5 step 5 提示 grep 看实际类型,可能需要调整累积逻辑
- 项目可能用 conftest fixture 注入 `chat_test_client` + `pg_session_factory` — 若 fixture 名不同,改 Task 5/6/7 测试的 fixture 参数名
- LangGraph `aget_state(config).config["configurable"]["checkpoint_id"]` 在 1.x 各版本访问路径可能不同 — Task 5 step 5 try/except 兜底为 None,Plan 3 再校准

---

## Execution Handoff

Plan 1 complete and saved to `docs/superpowers/plans/2026-05-16-chat-session-persistence-plan1-foundation.md`. 两种执行模式:

**1. Subagent-Driven(推荐)** — 我每个 task 派一个 fresh subagent 实施,task 间我做 review,迭代快。Plan 1 9 个 task,每个 task ~2-4 小时 subagent 工作量,合计 1-2 个 wall-time 工作日。

**2. Inline Execution** — 在当前 session 内顺序跑所有 task,checkpoint 时让你 review。适合 task 间紧耦合或需要在线决策的情况;Plan 1 各 task 独立性高,subagent-driven 更合适。

**你选哪个?**
