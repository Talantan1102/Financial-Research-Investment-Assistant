# Chat 子系统用户隔离 实施计划

> 设计见 `docs/superpowers/specs/2026-06-12-chat-user-isolation-design.md`。在隔离 worktree `feat/chat-user-isolation`(off origin/main,含 #156 真 auth)实施。TDD,频繁提交。

**Goal:** chats.py / chat.py / escalate.py 全部强制 `get_current_user_required` + 按 `user.id` 过滤 + 资源归属校验;清 NULL 用户老会话。照搬 reports/memory 已验证范式。

**统一 import(三 router 共用)**
```python
from typing import Annotated
from app.models.user import User
from app.router.auth_router import get_current_user_required
```

**统一归属校验范式**
- 会话型:`s = await repo.get_session(session_id); if s is None or str(s.user_id) != str(user.id): raise HTTPException(404, "session not found")`
- 任务型:`task = await task_repo.get_by_id(task_uuid); if task is None or str(task.user_id) != str(user.id): raise HTTPException(404, "task not found")`
- 用 404(不区分"不存在"与"非己",防枚举);`str()` 两侧兜 UUID/str 混用。

---

### Task 1: chats.py 5 端点加 auth + scope

**Files:** Modify `backend/app/router/chats.py`;Test `backend/tests/unit/router/test_chats_isolation.py`(新)

- [ ] **Step 1: 写失败集成测试**(用 TestClient + override `get_current_user_required` 为 user A / B)

```python
"""chats.py 用户隔离:无 token 401 / A·B 各看各 / 越权 404。"""
from __future__ import annotations
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.router.chats import router as chats_router, get_repo
from app.router.auth_router import get_current_user_required
from app.services.chat_session_repo import ChatSessionRepo


class _U:
    def __init__(self, uid: uuid.UUID) -> None:
        self.id = uid


def _client(repo: ChatSessionRepo, user: _U | None) -> TestClient:
    app = FastAPI()
    app.include_router(chats_router)
    app.dependency_overrides[get_repo] = lambda: repo
    if user is not None:
        app.dependency_overrides[get_current_user_required] = lambda: user
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.asyncio
async def test_list_isolated_per_user(pg_async_session_factory) -> None:
    repo = ChatSessionRepo(pg_async_session_factory)
    a, b = _U(uuid.uuid4()), _U(uuid.uuid4())
    # 需先在 users 表插 A/B(FK);沿用现有 test helper 或 raw insert
    # ... insert users a.id, b.id ...
    ca = _client(repo, a)
    sid_a = ca.post("/api/v0/chats", json={"title": "A的会话"}).json()["id"]
    assert any(s["id"] == sid_a for s in ca.get("/api/v0/chats").json())
    cb = _client(repo, b)
    assert all(s["id"] != sid_a for s in cb.get("/api/v0/chats").json())  # B 看不到 A 的
    # 越权:B 读/删 A 的 → 404
    assert cb.get(f"/api/v0/chats/{sid_a}").status_code == 404
    assert cb.delete(f"/api/v0/chats/{sid_a}").status_code == 404
```

- [ ] **Step 2: 跑测确认失败**(当前 list 硬编码 anonymous、无 user dep → 断言挂)
Run: `pytest tests/unit/router/test_chats_isolation.py -q -p no:langsmith_plugin -o addopts=''`

- [ ] **Step 3: 改 chats.py**

每个端点签名加 `user: Annotated[User, Depends(get_current_user_required)]`,改 user_id 来源 + 加归属校验:
```python
@router.get("")
@router.get("/")
async def list_chats(
    user: Annotated[User, Depends(get_current_user_required)],
    repo: ChatSessionRepo = Depends(get_repo),
) -> list[ChatSessionView]:
    sessions = await repo.list_for_user(str(user.id))
    return [_to_view(s) for s in sessions]


@router.post("")
@router.post("/")
async def create_chat(
    req: CreateChatRequest,
    user: Annotated[User, Depends(get_current_user_required)],
    repo: ChatSessionRepo = Depends(get_repo),
) -> ChatSessionView:
    s = await repo.create_session(user_id=str(user.id), title=req.title)
    return _to_view(s)
```
`get_chat` / `rename_chat` / `delete_chat`:取 session 后插入归属校验(范式见上),再继续原逻辑。

- [ ] **Step 4: 跑测确认通过** + Commit

---

### Task 2: chat.py 5 端点加 auth + 归属

**Files:** Modify `backend/app/router/chat.py`

- [ ] **Step 1**:`chat`(212)签名 `get_current_user` → `get_current_user_required`;落消息/建 task 前加会话归属校验(`req.session_id` 的 session.user_id==user.id);`user_id=_coerce_user_uuid(user.id)`→`user_id=user.id`、`user_id=str(user.id)` 保留(已是真 UUID)。
- [ ] **Step 2**:`chat_stream`(294)/`chat_cancel`(384)/`chat_steer`(439)/`chat_retry`(505)各加 `user: Annotated[User, Depends(get_current_user_required)]`;`task = await task_repo.get_by_id(...)` 后加任务型归属校验(范式见上)。
- [ ] **Step 3**:`chat_retry` 内 `user_id=str(old_task.user_id) if old_task.user_id else "anonymous"`(580)→ 既然归属校验已确保 `old_task.user_id==user.id`,改 `user_id=str(user.id)`。
- [ ] **Step 4**:`_maybe_populate_persona_on_session_start`(158)与 `_coerce_user_uuid`(187):删匿名容错(`user.id` 恒真 UUID);persona 直接 `user_id=user.id`。
- [ ] **Step 5**:跑现有 chat 单测(本文件相关)+ Commit

---

### Task 3: escalate.py 加 auth + scope

**Files:** Modify `backend/app/router/escalate.py`

- [ ] `escalate`(163)加 `get_current_user_required`;`user_id="anonymous"`(125)→`str(user.id)`;若有 `chat_session_id` 入参,加会话归属校验。Commit。

---

### Task 4: 迁移现有 chat 集成测试到 required-auth

**Files:** Modify `test_chat_inflight_plan2.py` / `test_chat_cancel_retry.py` / `test_chat_differential_golden.py` / `tests/unit/router/test_auth_helpers.py`(若涉及)

- [ ] **Step 1**:`_StubUser.id` 从 `"test-user"` 改为固定真 UUID(如 `uuid.UUID("00000000-0000-0000-0000-0000000000aa")`);在用到的 PG 里插对应 users 行(FK)。
- [ ] **Step 2**:`app.dependency_overrides[get_current_user]` → `[get_current_user_required]`(import 换 `auth_router.get_current_user_required`)。
- [ ] **Step 3**:`seeded_running_task` 等 fixture 建 ChatSession/ChatTask 时 `user_id=` 改成该 stub UUID(原 `None`),使归属校验通过。
- [ ] **Step 4**:跑这三个文件全绿 + Commit。

---

### Task 5: 新增隔离回归测试

**Files:** `test_chats_isolation.py`(Task 1 已建,补全)+ chat.py 任务型越权用例

- [ ] 补:无 token → chat/chats/stream/cancel/retry 各 401;B 拿 A 的 task_id cancel/stream → 404。Commit。

---

### Task 6: 清理 NULL 用户老会话

**Files:** `backend/app/scripts/cleanup_anonymous_chat_sessions.py`(新,一次性)

- [ ] **Step 1**:脚本(事务内,删前打印计数,顺序 episodes→messages→tasks→sessions):
```python
"""一次性:删 user_id IS NULL 的 chat_sessions 及级联(C.6 隔离上线前清匿名池)。"""
import os, psycopg2
conn = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
    user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"], dbname=os.environ["POSTGRES_DB"])
cur = conn.cursor()
cur.execute("SELECT id FROM chat_sessions WHERE user_id IS NULL")
sids = [r[0] for r in cur.fetchall()]
print(f"NULL-user sessions to delete: {len(sids)}")
if sids:
    cur.execute("DELETE FROM chat_memory_episodes WHERE session_id = ANY(%s)", (sids,))
    print("  episodes:", cur.rowcount)
    cur.execute("DELETE FROM chat_messages WHERE session_id = ANY(%s)", (sids,))
    print("  messages:", cur.rowcount)
    cur.execute("DELETE FROM chat_tasks WHERE session_id = ANY(%s)", (sids,))
    print("  tasks:", cur.rowcount)
    cur.execute("DELETE FROM chat_sessions WHERE id = ANY(%s)", (sids,))
    print("  sessions:", cur.rowcount)
conn.commit(); conn.close()
```
- [ ] **Step 2**:对真 PG 跑(删前确认计数合理);记录删除数。**注:实际运行放到浏览器验证前**(运行后老会话从所有人列表消失)。

---

### Task 7: 改动面全回归 + ruff + mypy

- [ ] `pytest tests/integration/test_chat_*.py tests/unit/router/ -q -p no:langsmith_plugin -o addopts=''` 全绿
- [ ] `ruff format --check` + `ruff check` + `mypy` 改动文件全绿
- [ ] Commit

---

## Self-Review
- Spec 覆盖:auth+scope(Task1-3)/ 测试迁移(Task4)/ 隔离回归(Task5)/ 数据清理(Task6)/ 回归(Task7)。✓
- 类型:`get_current_user_required` 返回 `User`,`user.id` 为 UUID;归属校验 `str()` 两侧兜混用。✓
- 无占位:范式 + 关键端点给了实码;机械套用点(get/rename/delete、4 任务型端点)枚举到具体行号。✓
