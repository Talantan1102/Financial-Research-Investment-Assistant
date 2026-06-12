# Chat 端点接真 JWT 认证(C.6 wiring)实施计划

> 设计见 `docs/superpowers/specs/2026-06-12-chat-endpoint-real-auth-design.md`。

**Goal:** `auth_helpers.get_current_user` 由「恒匿名」改为「委托真 `auth_router.get_current_user` + 无 token 回退匿名」,使登录用户的 chat 轮带真 `user_id` → #7 episode 写入生效;chat.py 不动。

**Architecture:** 单文件改 `backend/app/router/auth_helpers.py`。符号身份不变(仅换函数体 + 加 `Depends` 子依赖),现有测试 override 与匿名路径不受影响。

---

### Task 1: auth_helpers.get_current_user 委托真 auth + 匿名回退(TDD)

**Files:**
- Test: `backend/tests/unit/test_auth_helpers_real_auth.py`(新建)
- Modify: `backend/app/router/auth_helpers.py`

- [ ] **Step 1: 写失败单测**

```python
"""L0 — auth_helpers.get_current_user:真 User 直通 / 无 token 回退匿名。"""
from __future__ import annotations

import pytest
from app.router.auth_helpers import _AnonUser, get_current_user


class _RealUser:
    def __init__(self, uid: str) -> None:
        self.id = uid


@pytest.mark.asyncio
async def test_real_user_passes_through() -> None:
    u = _RealUser("8b76068b-bcaf-4aac-80cd-1266cade1442")
    out = await get_current_user(real_user=u)
    assert out is u
    assert out.id == "8b76068b-bcaf-4aac-80cd-1266cade1442"


@pytest.mark.asyncio
async def test_no_token_falls_back_to_anonymous() -> None:
    out = await get_current_user(real_user=None)
    assert isinstance(out, _AnonUser)
    assert out.id == "anonymous"
```

- [ ] **Step 2: 跑测确认失败**

Run: `~/fria-venv/bin/python -m pytest tests/unit/test_auth_helpers_real_auth.py -q`
Expected: FAIL —— 现 `get_current_user()` 不收 `real_user` 参数(TypeError)。

- [ ] **Step 3: 实现**

把 `auth_helpers.py` 的 `get_current_user` 改为(保留 `_AnonUser` 类不变):

```python
from __future__ import annotations

from typing import Any

from fastapi import Depends

from app.router.auth_router import get_current_user as _jwt_get_current_user

# ... _AnonUser 类不变 ...


async def get_current_user(real_user: Any = Depends(_jwt_get_current_user)) -> Any:
    """真 JWT 认证 + 匿名回退(C.6 wiring)。

    登录(有效 Bearer token)→ 真 User(真 UUID id);
    无 / 无效 token → _AnonUser(id="anonymous")——保持 v0 匿名行为。
    `_jwt_get_current_user`(auth_router)校验 token 返回 User | None。
    """
    return real_user if real_user is not None else _AnonUser()
```

并把模块 docstring / `_AnonUser` 注释里的「every request is treated as anonymous」更新为「真 JWT + 匿名回退」。

- [ ] **Step 4: 跑测确认通过**

Run: `~/fria-venv/bin/python -m pytest tests/unit/test_auth_helpers_real_auth.py -q`
Expected: PASS(2 passed)。

- [ ] **Step 5: 验无循环 import**

Run: `~/fria-venv/bin/python -c "import app.router.chat; import app.router.auth_helpers; print('import ok')"`
Expected: `import ok`(auth_helpers→auth_router 单向,无环)。

- [ ] **Step 6: Commit**

```bash
git add backend/app/router/auth_helpers.py backend/tests/unit/test_auth_helpers_real_auth.py
git commit -m "feat(auth): chat 端点接真 JWT 认证 + 匿名回退(C.6 wiring)"
```

---

### Task 2: 回归 — chat 套件 + ruff + mypy 全绿

**Files:** 无改动,仅验证。

- [ ] **Step 1: chat 集成 + 单测全跑**

Run: `set -a; . ./.env; set +a; ~/fria-venv/bin/python -m pytest tests/integration/test_chat_*.py tests/unit/test_auth_helpers_real_auth.py -q -p no:langsmith_plugin -o addopts=''`
Expected: 全 PASS(匿名路径不变:测试 override `get_current_user`→`_StubUser`,符号身份未变仍命中;`_StubUser.id="test-user"` 非 UUID → 仍走匿名)。

- [ ] **Step 2: ruff + mypy**

Run: `~/fria-venv/bin/python -m ruff format --check app/router/auth_helpers.py tests/unit/test_auth_helpers_real_auth.py; ~/fria-venv/bin/python -m ruff check app/router/auth_helpers.py tests/unit/test_auth_helpers_real_auth.py; ~/fria-venv/bin/python -m mypy app/router/auth_helpers.py`
Expected: 全绿。

---

### Task 3: 浏览器 e2e — 登录用户真写 episode

**前置:** uvicorn(:8000,本分支代码)+ celery worker(`default,llm,memory_llm`)+ 前端(:5183,testuser 已登录)全在。

- [ ] **Step 1:** 取基线 `chat_memory_episodes` 计数。
- [ ] **Step 2:** 浏览器 testuser 新会话发一轮(自然散户口吻、可持久化偏好),等回复完成。
- [ ] **Step 3:** 查 PG:该 session 出现 1 条 `source_kind=chat_turn` 且 **`user_id`=testuser 真 UUID** 的 episode(对比基线 +1);worker 日志见 `extract_session_episodes_async` 被触发消费。
- [ ] **Step 4:** 截图 + 数据双证。

---

## Self-Review

- **Spec 覆盖**:决策(委托+回退)→ Task 1;兼容/回归(匿名不变)→ Task 2;happy-path 真写 → Task 3。✓
- **无占位**:每步含真实代码/命令/期望。✓
- **类型一致**:`get_current_user(real_user=...)` 签名 Task 1 定义,Task 2 引用一致。✓
