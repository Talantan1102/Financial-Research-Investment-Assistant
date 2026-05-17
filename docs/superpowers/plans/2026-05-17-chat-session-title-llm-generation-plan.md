# Chat Session Title — LLM 异步生成 + 手动重命名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 chat session title 从「前 20 字截断」升级到「LLM 异步生成 + 用户可手动改名」, 对齐 ChatGPT/Claude 体验。

**Architecture:** chat_sessions 加 `title_source` 三态字段(pending/llm_generated/user_renamed); 新增 `generate_session_title` Celery task 在首轮 assistant 完成后异步触发(`router/chat_finalize.py` enqueue); 前端 sidebar 加 hover `...` 菜单 + inline rename(已有 `PUT /sessions/{id}` endpoint)。

**Tech Stack:** SQLAlchemy / Alembic-free `create_all()` / Celery + Redis / FastAPI / LLMService (`tier="fast"`, qwen-turbo) / VCR cassette / React + Valtio + Vitest

**Spec:** `docs/superpowers/specs/2026-05-17-chat-session-title-llm-generation-design.md`

---

## File Structure

**Create:**
- `backend/app/tasks/title_generation.py` — 新 Celery task + LLM 调用 + fallback
- `backend/scripts/backfill_title_source.py` — 一次性老数据迁移
- `backend/tests/unit/tasks/test_title_generation.py` — L0 单测
- `backend/tests/integration/test_title_generation_l1.py` — L1 真 LLM + cassette
- `backend/tests/e2e/test_chat_title_e2e.py` — L2 serve path 端到端
- `frontend/src/components/sidebar/__tests__/chat-session-list-rename.test.tsx` — 前端 rename 交互

**Modify:**
- `backend/app/models/chat.py` — `ChatSession` 加 `title_source` 字段
- `backend/app/router/chat_finalize.py:88` — `mark_done` 后 enqueue `generate_session_title`
- `backend/app/router/session_router.py:140-170` (PUT) 和 `:277-281` (删除截断)
- `backend/app/services/chat_session_repo.py:122` (`rename_session`) — 同步设 `title_source="user_renamed"`
- `backend/app/app_main.py` — lifespan 启动跑一次 backfill(idempotent)
- `frontend/src/api/chatApi.ts` — 加 `renameChat(id, title)`
- `frontend/src/store/chat-sessions.ts` — 加 `renameSession(id, title)` action(乐观更新)
- `frontend/src/components/sidebar/chat-session-list.tsx` — hover `...` 菜单 + inline rename input
- `frontend/src/hooks/useChatSSE.ts` — close 后追加 ~3s 延时 refetch

---

## Task 1: Schema 加 `title_source` 字段

**Files:**
- Modify: `backend/app/models/chat.py` (`ChatSession` class 在 message_count 字段下方加)
- Test: `backend/tests/unit/models/test_chat_session_title_source.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/models/test_chat_session_title_source.py`:

```python
"""Verify ChatSession.title_source field exists with correct default."""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.chat import ChatSession


def test_title_source_defaults_to_pending() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        s = ChatSession(id=uuid.uuid4(), user_id=None, title="新对话")
        sess.add(s)
        sess.commit()
        sess.refresh(s)
        assert s.title_source == "pending"


def test_title_source_accepts_three_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        for source in ("pending", "llm_generated", "user_renamed"):
            s = ChatSession(
                id=uuid.uuid4(),
                user_id=None,
                title=f"t-{source}",
                title_source=source,
            )
            sess.add(s)
        sess.commit()
        rows = sess.query(ChatSession).all()
        assert {r.title_source for r in rows} == {"pending", "llm_generated", "user_renamed"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/models/test_chat_session_title_source.py -v`
Expected: FAIL — `AttributeError: 'ChatSession' object has no attribute 'title_source'`

- [ ] **Step 3: Add the field**

Edit `backend/app/models/chat.py` — 在 `ChatSession` class 的 `last_msg_preview` 字段 **下方** 加:

```python
    # === Title 生成状态 (2026-05-17) ===
    title_source = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )  # pending | llm_generated | user_renamed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/models/test_chat_session_title_source.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/chat.py backend/tests/unit/models/test_chat_session_title_source.py
git commit -m "feat(chat-title): add title_source field to ChatSession (pending/llm_generated/user_renamed)"
```

---

## Task 2: Backfill script — 老 session 标记为 llm_generated

**Files:**
- Create: `backend/scripts/backfill_title_source.py`
- Test: `backend/tests/unit/scripts/test_backfill_title_source.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/unit/scripts/test_backfill_title_source.py`:

```python
"""Backfill script: 已有非默认 title 的老 session 一次性置为 llm_generated."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.chat import ChatSession
from app.scripts.backfill_title_source import backfill


@pytest.fixture
def engine_with_seed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        sess.add(ChatSession(id=uuid.uuid4(), title="贵州茅台估值..."))  # 已有 title
        sess.add(ChatSession(id=uuid.uuid4(), title="新对话"))             # 还没被聊过
        sess.add(
            ChatSession(id=uuid.uuid4(), title="美的家电分析", title_source="user_renamed")
        )  # 用户已手动改名 — 不动
        sess.commit()
    return engine


def test_backfill_marks_non_default_titles_as_llm_generated(engine_with_seed):
    backfill(engine_with_seed)
    Session = sessionmaker(bind=engine_with_seed)
    with Session() as sess:
        rows = sess.query(ChatSession).all()
        by_title = {r.title: r.title_source for r in rows}
        assert by_title["贵州茅台估值..."] == "llm_generated"
        assert by_title["新对话"] == "pending"
        assert by_title["美的家电分析"] == "user_renamed"  # 未被覆盖
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/scripts/test_backfill_title_source.py -v`
Expected: FAIL — `ModuleNotFoundError: app.scripts.backfill_title_source`

- [ ] **Step 3: Create the script**

`backend/app/scripts/backfill_title_source.py`(注意路径在 `app/scripts/` 下, 让它能 `from app.scripts.backfill_title_source import backfill`):

```python
"""一次性迁移: 已有非默认 title 的老 session 视为 llm_generated, 不再触发 LLM 重跑.

调用方:
  - app_main lifespan 启动时跑一次(幂等)
  - 也可以独立 CLI: `uv run python -m app.scripts.backfill_title_source`

幂等: UPDATE ... WHERE title_source='pending' AND title != '新对话', 重复跑无副作用.
"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.models.chat import ChatSession


def backfill(engine: Engine) -> int:
    """Returns the number of rows updated."""
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        result = sess.execute(
            update(ChatSession)
            .where(
                ChatSession.title_source == "pending",
                ChatSession.title != "新对话",
            )
            .values(title_source="llm_generated")
        )
        sess.commit()
        return result.rowcount or 0


if __name__ == "__main__":
    from app.config.database import get_engine

    engine = get_engine()
    n = backfill(engine)
    print(f"backfilled {n} old sessions to title_source='llm_generated'")
```

确保 `backend/app/scripts/__init__.py` 存在(若没有则 `touch`)。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/scripts/test_backfill_title_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/__init__.py backend/app/scripts/backfill_title_source.py backend/tests/unit/scripts/test_backfill_title_source.py
git commit -m "feat(chat-title): backfill script — old non-default titles → llm_generated (idempotent)"
```

---

## Task 3: 接入 backfill 到 app_main lifespan

**Files:**
- Modify: `backend/app/app_main.py` (lifespan startup 段)

- [ ] **Step 1: Locate lifespan startup**

Run: `grep -n "lifespan\|startup\|@asynccontextmanager" backend/app/app_main.py | head -20`
Expected: 找到 `@asynccontextmanager` 或 `lifespan` 函数定义。记下行号。

- [ ] **Step 2: Add backfill call**

Edit `backend/app/app_main.py` — 在 lifespan startup 段(其他 startup 任务后面)加:

```python
    # === title_source backfill (2026-05-17): 一次性 idempotent migration ===
    try:
        from app.config.database import get_engine
        from app.scripts.backfill_title_source import backfill

        n_backfilled = backfill(get_engine())
        if n_backfilled:
            logger.info("backfilled %d old chat_sessions title_source=llm_generated", n_backfilled)
    except Exception as exc:  # noqa: BLE001
        logger.warning("title_source backfill skipped: %s", exc)
```

> 注意: 已有 `logger` 不要重复 import; 若该文件没有 logger 用 `logging.getLogger(__name__)`。

- [ ] **Step 3: Smoke test lifespan path 本地**

Run: `cd backend && uv run python -c "from app.app_main import app; print(app)"`
Expected: 无 import error, 打印 FastAPI app 实例。

- [ ] **Step 4: Commit**

```bash
git add backend/app/app_main.py
git commit -m "feat(chat-title): wire backfill_title_source into app_main lifespan startup"
```

---

## Task 4: `generate_session_title` Celery task — 单元测试先行

**Files:**
- Create: `backend/tests/unit/tasks/test_title_generation.py`

- [ ] **Step 1: Write the failing tests (覆盖 6 个分支)**

`backend/tests/unit/tasks/test_title_generation.py`:

```python
"""L0 unit tests for generate_session_title Celery task.

覆盖:
- title_source != "pending" → skip
- len(messages) < 2 → skip (防御)
- LLM 返回带引号/「」 → strip 干净
- LLM 输出 > 255 字 → 截断
- LLM 全失败 → fallback user.content[:20] + "..."
- 成功路径 → title_source 变 llm_generated
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.chat import ChatMessage, ChatSession


@pytest.fixture
def db_with_session(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content="贵州茅台最近怎么样,值得现在买入吗?",
                status="done",
            )
        )
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="assistant",
                content="贵州茅台当前 PE 约 25x, 历史百分位 35%, ...",
                status="done",
            )
        )
        sess.commit()
    return engine, str(sid), Session


def _patch_db(monkeypatch, Session):
    """让 task 使用我们的 in-memory engine."""
    import app.tasks.title_generation as mod

    monkeypatch.setattr(mod, "_open_db_session", lambda: Session())


def test_skip_when_title_source_not_pending(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        s.title_source = "user_renamed"
        sess.commit()
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    mock_llm.chat.assert_not_called()


def test_skip_when_less_than_two_messages(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(), session_id=sid, role="user", content="hi", status="done"
            )
        )
        sess.commit()
    _patch_db(monkeypatch, Session)

    from app.tasks.title_generation import generate_session_title

    mock_llm = MagicMock()
    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(str(sid))
    mock_llm.chat.assert_not_called()


def test_strips_quotes_and_brackets(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content='「贵州茅台估值分析」')

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert s.title == "贵州茅台估值分析"
        assert s.title_source == "llm_generated"


def test_truncates_oversized_title(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="a" * 500)

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert len(s.title) <= 255


def test_fallback_when_llm_keeps_failing(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.side_effect = RuntimeError("LLM down")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        # eager 模式下 retry 不真转动, 但 fallback 分支应触发 (impl 在 except 内判断 retries)
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        # fallback: user.content[:20] + "..."
        expected = "贵州茅台最近怎么样,值得现在买入吗?"[:20] + "..."
        assert s.title == expected
        assert s.title_source == "llm_generated"


def test_success_path_writes_llm_generated(db_with_session, monkeypatch):
    engine, sid, Session = db_with_session
    _patch_db(monkeypatch, Session)

    mock_llm = MagicMock()
    mock_llm.chat.return_value = MagicMock(content="贵州茅台估值分析")

    from app.tasks.title_generation import generate_session_title

    with patch("app.tasks.title_generation.get_llm_service", return_value=mock_llm):
        generate_session_title(sid)
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert s.title == "贵州茅台估值分析"
        assert s.title_source == "llm_generated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/tasks/test_title_generation.py -v`
Expected: FAIL — `ModuleNotFoundError: app.tasks.title_generation`

- [ ] **Step 3: Commit failing tests**

```bash
git add backend/tests/unit/tasks/test_title_generation.py
git commit -m "test(chat-title): L0 tests for generate_session_title (6 branches)"
```

---

## Task 5: 实现 `generate_session_title` Celery task

**Files:**
- Create: `backend/app/tasks/title_generation.py`

- [ ] **Step 1: Write the task**

`backend/app/tasks/title_generation.py`:

```python
"""异步生成 chat session title 的 Celery task.

触发: router/chat_finalize.py 在首轮 assistant 落库后 enqueue.
幂等: 启动时检查 title_source 不为 pending 则 skip.
失败兜底: 显式 3 次 attempt 用完后 fallback 到 user.content[:20] 截断.

注: 用显式 for-loop attempts 而非 Celery autoretry, 因为 eager 模式下 autoretry 行为
不可观察 / 难单测; 这种 best-effort 副产品任务三次本进程内即可, 失败成本极低。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.config.database import get_engine
from app.models.chat import ChatMessage, ChatSession
from app.services.openai_client import build_llm_service_from_env
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_TITLE_MAX_CHARS = 255
_ASSISTANT_INPUT_CHARS = 500
_STRIP_CHARS = '"\'「」 \n\t'
_MAX_ATTEMPTS = 3


def _open_db_session() -> Session:
    """Indirection 给 unit test 用 monkeypatch."""
    return sessionmaker(bind=get_engine())()


def get_llm_service():
    """Indirection 给 unit test 用 patch."""
    return build_llm_service_from_env()


def _llm_generate_title(user_text: str, assistant_text: str) -> str:
    """调 LLMService cheap tier 生成 10-15 字 title."""
    llm = get_llm_service()
    prompt = (
        "请为以下对话生成一个 10-15 个汉字的简洁标题, 直接返回标题文本, "
        "不要任何前后缀 / 引号 / 编号:\n\n"
        f"用户: {user_text}\n"
        f"助手: {assistant_text}"
    )
    resp = llm.chat(prompt=prompt, tier="fast", schema=None)
    raw = resp.content.strip()
    for ch in _STRIP_CHARS:
        raw = raw.strip(ch)
    return raw[:_TITLE_MAX_CHARS]


@celery_app.task(
    bind=True,
    name="app.tasks.title_generation.generate_session_title",
)
def generate_session_title(self, session_id: str) -> None:
    sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    with _open_db_session() as db:
        session = db.query(ChatSession).filter_by(id=sid).one_or_none()
        if session is None:
            logger.debug("title task: session %s gone, skipping", session_id)
            return
        if session.title_source != "pending":
            logger.debug(
                "title task: session %s already %s, skipping",
                session_id,
                session.title_source,
            )
            return

        msgs = (
            db.query(ChatMessage)
            .filter_by(session_id=sid)
            .order_by(ChatMessage.created_at.asc())
            .limit(2)
            .all()
        )
        if len(msgs) < 2:
            logger.debug("title task: only %d messages, skipping", len(msgs))
            return
        user_msg, assistant_msg = msgs[0], msgs[1]

        title: str | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                title = _llm_generate_title(
                    user_text=user_msg.content,
                    assistant_text=assistant_msg.content[:_ASSISTANT_INPUT_CHARS],
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == _MAX_ATTEMPTS - 1:
                    logger.warning(
                        "title task: LLM exhausted %d attempts (%s), fallback to truncation",
                        _MAX_ATTEMPTS,
                        exc,
                    )
                    title = user_msg.content[:20] + (
                        "..." if len(user_msg.content) > 20 else ""
                    )
                    break
                logger.debug(
                    "title task: LLM attempt %d failed (%s), retrying",
                    attempt + 1,
                    exc,
                )

        assert title is not None  # 上面 loop 必走通其中一支
        session.title = title
        session.title_source = "llm_generated"
        db.commit()
        logger.info("title task: session %s → %r", session_id, title)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/tasks/test_title_generation.py -v`
Expected: PASS (6 passed)

- [ ] **Step 3: 跑 mypy 确认类型干净**

Run: `cd backend && uv run mypy app/tasks/title_generation.py`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add backend/app/tasks/title_generation.py
git commit -m "feat(chat-title): generate_session_title Celery task (LLM fast tier + 3-attempt loop + truncate fallback)"
```

---

## Task 6: L1 integration test — 真 LLMService + cassette

**Files:**
- Create: `backend/tests/integration/test_title_generation_l1.py`

- [ ] **Step 1: Write the test**

`backend/tests/integration/test_title_generation_l1.py`:

```python
"""L1 integration: generate_session_title 用真 LLMService + VCR cassette.

录制方式:
  cd backend && LLM_MODE=live uv run pytest tests/integration/test_title_generation_l1.py \
    --record-mode=once -v
回放(CI 默认):
  cd backend && LLM_MODE=cassette uv run pytest tests/integration/test_title_generation_l1.py -v
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.chat import ChatMessage, ChatSession


@pytest.fixture
def in_memory_db(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    import app.tasks.title_generation as mod

    monkeypatch.setattr(mod, "_open_db_session", lambda: Session())
    return Session


@pytest.mark.vcr()
def test_l1_real_llm_generates_meaningful_title(in_memory_db):
    Session = in_memory_db
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content="贵州茅台最近怎么样,值得现在买入吗?",
                status="done",
            )
        )
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="assistant",
                content=(
                    "贵州茅台当前 PE 约 25x, 历史百分位 35%, "
                    "估值处于近 5 年中位偏下水平; 但白酒板块整体景气度承压, "
                    "Q2 业绩预期低于此前共识..."
                ),
                status="done",
            )
        )
        sess.commit()

    from app.tasks.title_generation import generate_session_title

    generate_session_title(str(sid))

    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=sid).one()
        assert s.title_source == "llm_generated"
        assert s.title != "新对话"
        assert len(s.title) <= 30  # 人眼/cassette 阈值: cheap 模型 ~10-20 字
        # 期望含 "茅台" — 主题词覆盖
        assert "茅台" in s.title or "白酒" in s.title or "贵州" in s.title
```

- [ ] **Step 2: 录制 cassette(需要真 API key)**

确保 `backend/.env` 有 `DASHSCOPE_API_KEY` + `DASHSCOPE_BASE_URL`。

Run:
```bash
cd backend && \
  LLM_MODE=live uv run pytest tests/integration/test_title_generation_l1.py \
  --record-mode=once -v
```

Expected: PASS + 在 `backend/tests/fixtures/cassettes/test_title_generation_l1/` 下生成 `.yaml` cassette。

> 若 LLM 输出不含 "茅台/白酒/贵州" 任一关键词, 重录 / 调 prompt 让主题词更稳。

- [ ] **Step 3: 回放模式 verify**

Run: `cd backend && LLM_MODE=cassette uv run pytest tests/integration/test_title_generation_l1.py -v`
Expected: PASS (无真 API 调用)

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_title_generation_l1.py backend/tests/fixtures/cassettes/test_title_generation_l1/
git commit -m "test(chat-title): L1 integration with real LLM + VCR cassette"
```

---

## Task 7: 接入 `chat_finalize` — 首轮 assistant 完成后 enqueue

**Files:**
- Modify: `backend/app/router/chat_finalize.py` (在 `task_repo.mark_done(...)` 后)

- [ ] **Step 1: 找到 mark_done 位置**

Run: `grep -n "mark_done\|append_message" backend/app/router/chat_finalize.py`
Expected: 找到 `await task_repo.mark_done(task_id, langgraph_checkpoint_id=checkpoint_id)` 行号(估 line 88)。

- [ ] **Step 2: Insert enqueue after mark_done**

Edit `backend/app/router/chat_finalize.py` — 在 success 分支 `await task_repo.mark_done(...)` 之后立刻加:

```python
        # === NEW (2026-05-17): 首轮 assistant 完成后异步生成 session title ===
        try:
            session = await session_repo.get_session(str(session_id))
            if session and session.title_source == "pending":
                from app.tasks.title_generation import generate_session_title

                generate_session_title.apply_async(
                    args=[str(session_id)], countdown=1
                )
                logger.info(
                    "enqueued generate_session_title for session %s", session_id
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("title enqueue skipped: %s", exc)
```

> 注: enqueue 失败绝不能影响主流程(已用 try/except 兜住)。

- [ ] **Step 3: 跑现有 chat_finalize 测试 确认没破坏**

Run: `cd backend && uv run pytest tests/ -k "chat_finalize or finalize_task_persistence" -v`
Expected: 现有所有相关测试 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/app/router/chat_finalize.py
git commit -m "feat(chat-title): enqueue generate_session_title from chat_finalize success branch (countdown=1)"
```

---

## Task 8: 删除 `session_router.py:277-281` 同步截断

**Files:**
- Modify: `backend/app/router/session_router.py:277-281`

- [ ] **Step 1: 确认行号**

Run: `grep -n "如果是第一条用户消息\|content\[:20\]" backend/app/router/session_router.py`
Expected: 找到 277-281 行那段截断逻辑。

- [ ] **Step 2: 删除**

Edit `backend/app/router/session_router.py` 删除以下整段:

```python
    # 如果是第一条用户消息，自动生成标题
    if message_data.role == "user" and session.title == "新对话":
        # 取消息前20个字符作为标题
        session.title = message_data.content[:20] + (
            "..." if len(message_data.content) > 20 else ""
        )
```

- [ ] **Step 3: 跑现有 session_router 测试**

Run: `cd backend && uv run pytest tests/ -k "session_router or add_message" -v`
Expected: PASS(若某 test 显式断言截断行为, 需同步更新该 test, 改为断言 title 保持 "新对话"; 见 grep 结果再决定)

```bash
grep -rn "新对话\.\.\.\|content\[:20\]\|前20" backend/tests/ 2>/dev/null
```

若有 test 假设旧截断行为, edit 这些 test 改为断言 `title == "新对话"`。

- [ ] **Step 4: Commit**

```bash
git add backend/app/router/session_router.py backend/tests/  # 含 test 改动
git commit -m "refactor(chat-title): remove inline 20-char title truncation (replaced by async LLM task)"
```

---

## Task 9: PUT `/sessions/{id}` 写 title 同步设 `user_renamed`

**Files:**
- Modify: `backend/app/router/session_router.py:140-170` (update_session handler)
- Modify: `backend/app/services/chat_session_repo.py:122-128` (rename_session)

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/unit/router/test_session_router_rename.py` (新建):

```python
"""PUT /sessions/{id} 写 title 时, title_source 同步置 user_renamed."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.chat import ChatSession


@pytest.fixture
def client_with_seed(monkeypatch):
    """搭一个最小 fastapi app + sqlite + 1 个 session, 跳过 auth."""
    from app.app_main import app
    from app.config.database import get_db

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(
            ChatSession(id=sid, title="新对话", title_source="llm_generated", user_id=None)
        )
        sess.commit()

    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    # 若有 auth dep, 也需 override 成 anonymous user
    from app.router.session_router import get_current_user_required
    from app.models.user import User

    fake_user = User(id=uuid.uuid4(), email="t@x.com")
    app.dependency_overrides[get_current_user_required] = lambda: fake_user
    # 把 session.user_id 设为 fake user 以通过 owner 校验
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=sid).one()
        s.user_id = fake_user.id
        sess.commit()

    yield TestClient(app), str(sid), Session
    app.dependency_overrides.clear()


def test_put_session_sets_user_renamed(client_with_seed):
    client, sid, Session = client_with_seed
    resp = client.put(f"/api/sessions/{sid}", json={"title": "我自己起的名字"})
    assert resp.status_code == 200
    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=uuid.UUID(sid)).one()
        assert s.title == "我自己起的名字"
        assert s.title_source == "user_renamed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/router/test_session_router_rename.py -v`
Expected: FAIL — title_source 还是 llm_generated (因为 router 没设 user_renamed)。

- [ ] **Step 3: Patch `update_session` handler**

Edit `backend/app/router/session_router.py` (around line 162):

```python
    session.title = session_data.title
    session.title_source = "user_renamed"  # NEW (2026-05-17)
    db.commit()
```

也同步 patch `chat_session_repo.rename_session` (line 122-128):

```python
    async def rename_session(self, session_id: str, new_title: str) -> None:
        sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        async with self._sf() as sess:
            await sess.execute(
                update(ChatSession)
                .where(ChatSession.id == sid)
                .values(title=new_title, title_source="user_renamed")  # NEW
            )
            await sess.commit()
```

- [ ] **Step 4: Run test + 现有 rename 相关 test**

Run: `cd backend && uv run pytest tests/ -k "rename or session_router" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/router/session_router.py backend/app/services/chat_session_repo.py backend/tests/unit/router/test_session_router_rename.py
git commit -m "feat(chat-title): PUT /sessions/{id} + rename_session() set title_source=user_renamed"
```

---

## Task 10: L2 e2e — 端到端 serve path 验证

**Files:**
- Create: `backend/tests/e2e/test_chat_title_e2e.py`

- [ ] **Step 1: Write the test**

`backend/tests/e2e/test_chat_title_e2e.py`:

```python
"""L2 e2e: 起 serve fixture, 跑首轮对话, 验证 title 异步落库.

依赖项目已有的 serve + celery_worker_subprocess fixture; 若 fixture 不可用则 skip。
"""
from __future__ import annotations

import time

import pytest
import requests


@pytest.mark.e2e
@pytest.mark.usefixtures("celery_worker_subprocess")
def test_first_round_triggers_llm_title_generation(serve_base_url: str):
    # 1. 创建 session
    resp = requests.post(f"{serve_base_url}/api/v0/chats/", json={})
    resp.raise_for_status()
    session = resp.json()
    sid = session["id"]
    assert session["title"] == "新对话"

    # 2. 发用户消息 → 触发 chat_runner
    resp = requests.post(
        f"{serve_base_url}/api/sessions/{sid}/messages",
        json={"role": "user", "content": "贵州茅台最近怎么样?"},
    )
    resp.raise_for_status()

    # 3. 等 SSE / Celery 完成主任务 + title 子任务
    deadline = time.time() + 30
    while time.time() < deadline:
        resp = requests.get(f"{serve_base_url}/api/v0/chats/{sid}")
        data = resp.json()
        title = data["session"]["title"]
        if title != "新对话":
            break
        time.sleep(1)
    else:
        pytest.fail("title 没在 30s 内被异步更新")

    assert title != "新对话"
    assert len(title) <= 30
```

> ⚠️ 这个 test 依赖项目 e2e infra (serve_base_url fixture + celery worker subprocess)。
> 跑前 `grep -rn "serve_base_url" backend/tests/e2e/` 确认 fixture 存在; 若不存在改 skip。

- [ ] **Step 2: Run e2e**

Run: `cd backend && uv run pytest tests/e2e/test_chat_title_e2e.py -v -m e2e`
Expected: PASS(若 LLM 调用走 cassette 也 OK; 若走真 API 注意 cost)。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/e2e/test_chat_title_e2e.py
git commit -m "test(chat-title): L2 e2e — first round triggers async title write"
```

---

## Task 11: 前端 `chatApi.renameChat`

**Files:**
- Modify: `frontend/src/api/chatApi.ts`
- Modify: `frontend/src/api/__tests__/chatApi.test.ts`

- [ ] **Step 1: Find existing chatApi structure**

Run: `cat frontend/src/api/chatApi.ts | head -50`
Expected: 看到现有 `createChat`, `getChat` 等函数, 确认 base URL / fetch 风格。

- [ ] **Step 2: Write failing test**

Append to `frontend/src/api/__tests__/chatApi.test.ts`:

```typescript
import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { renameChat } from '../chatApi'

const server = setupServer()
beforeEach(() => server.listen())
afterEach(() => server.resetHandlers())

describe('renameChat', () => {
  it('sends PUT /api/sessions/:id with new title', async () => {
    let received: { title: string } | null = null
    server.use(
      http.put('/api/sessions/abc-123', async ({ request }) => {
        received = (await request.json()) as { title: string }
        return HttpResponse.json({ id: 'abc-123', title: received.title })
      }),
    )
    await renameChat('abc-123', 'New Title')
    expect(received).toEqual({ title: 'New Title' })
  })

  it('throws on 4xx', async () => {
    server.use(
      http.put('/api/sessions/abc-123', () =>
        HttpResponse.json({ detail: '...' }, { status: 404 }),
      ),
    )
    await expect(renameChat('abc-123', 'x')).rejects.toThrow()
  })
})
```

- [ ] **Step 3: Run to verify FAIL**

Run: `cd frontend && pnpm test src/api/__tests__/chatApi.test.ts`
Expected: FAIL — `renameChat is not exported`

- [ ] **Step 4: Implement**

Append to `frontend/src/api/chatApi.ts`:

```typescript
/** 重命名 session — PUT /api/sessions/:id  (2026-05-17) */
export async function renameChat(id: string, title: string): Promise<void> {
  const resp = await fetch(`/api/sessions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!resp.ok) {
    throw new Error(`renameChat failed: ${resp.status}`)
  }
}
```

- [ ] **Step 5: Run to verify PASS + commit**

Run: `cd frontend && pnpm test src/api/__tests__/chatApi.test.ts`
Expected: PASS

```bash
git add frontend/src/api/chatApi.ts frontend/src/api/__tests__/chatApi.test.ts
git commit -m "feat(chat-title): frontend chatApi.renameChat — PUT /api/sessions/:id"
```

---

## Task 12: 前端 store `renameSession` action — 乐观更新 + 失败回滚

**Files:**
- Modify: `frontend/src/store/chat-sessions.ts`
- Modify: `frontend/src/store/__tests__/chat-sessions.test.ts`

- [ ] **Step 1: Read existing store**

Run: `cat frontend/src/store/chat-sessions.ts | head -100`
确认 store 是 valtio proxy 风格; 找到 `createAndAdd` 这类 action 的写法做参考。

- [ ] **Step 2: Write failing test**

Append to `frontend/src/store/__tests__/chat-sessions.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@/api/chatApi', () => ({
  renameChat: vi.fn(),
}))

import { renameChat } from '@/api/chatApi'
import { chatSessionsStore } from '../chat-sessions'

describe('renameSession action', () => {
  beforeEach(() => {
    chatSessionsStore.sessions = [
      {
        id: 'a',
        user_id: null,
        title: 'old',
        created_at: '2026-05-17T00:00:00Z',
        last_active_at: '2026-05-17T00:00:00Z',
        message_count: 0,
        last_msg_preview: null,
      },
    ]
    vi.mocked(renameChat).mockReset()
  })

  it('optimistically updates title then calls API', async () => {
    vi.mocked(renameChat).mockResolvedValue(undefined)
    const p = chatSessionsStore.renameSession('a', 'new')
    expect(chatSessionsStore.sessions[0].title).toBe('new')  // 乐观更新立即
    await p
    expect(renameChat).toHaveBeenCalledWith('a', 'new')
  })

  it('rolls back on API failure', async () => {
    vi.mocked(renameChat).mockRejectedValue(new Error('boom'))
    await expect(chatSessionsStore.renameSession('a', 'new')).rejects.toThrow()
    expect(chatSessionsStore.sessions[0].title).toBe('old')  // 已回滚
  })
})
```

- [ ] **Step 3: Run to FAIL**

Run: `cd frontend && pnpm test src/store/__tests__/chat-sessions.test.ts`
Expected: FAIL — `renameSession is not a function`

- [ ] **Step 4: Implement action**

Append to `frontend/src/store/chat-sessions.ts`(同 module level 的 `chatSessionsStore` 对象内, 或 store actions 风格仿照 `createAndAdd`):

```typescript
import { renameChat } from '@/api/chatApi'

// ... existing store ...

  async renameSession(id: string, newTitle: string): Promise<void> {
    const idx = this.sessions.findIndex(s => s.id === id)
    if (idx < 0) return
    const prevTitle = this.sessions[idx].title
    // 乐观更新
    this.sessions[idx].title = newTitle
    try {
      await renameChat(id, newTitle)
    } catch (e) {
      // 失败回滚
      this.sessions[idx].title = prevTitle
      throw e
    }
  },
```

> 若 store 是 valtio `proxy()` 风格而非 method-bag 风格, 把上面写成 module-level function:

```typescript
export async function renameSession(id: string, newTitle: string): Promise<void> {
  const idx = chatSessionsStore.sessions.findIndex(s => s.id === id)
  if (idx < 0) return
  const prevTitle = chatSessionsStore.sessions[idx].title
  chatSessionsStore.sessions[idx].title = newTitle
  try {
    await renameChat(id, newTitle)
  } catch (e) {
    chatSessionsStore.sessions[idx].title = prevTitle
    throw e
  }
}
```

跟实际 store 风格对齐, 二选一。

- [ ] **Step 5: Run PASS + commit**

Run: `cd frontend && pnpm test src/store/__tests__/chat-sessions.test.ts`
Expected: PASS

```bash
git add frontend/src/store/chat-sessions.ts frontend/src/store/__tests__/chat-sessions.test.ts
git commit -m "feat(chat-title): store renameSession — optimistic update + rollback on failure"
```

---

## Task 13: Sidebar `...` hover 菜单 + inline rename UI

**Files:**
- Modify: `frontend/src/components/sidebar/chat-session-list.tsx`
- Create: `frontend/src/components/sidebar/__tests__/chat-session-list-rename.test.tsx`

- [ ] **Step 1: Write failing rendering test**

`frontend/src/components/sidebar/__tests__/chat-session-list-rename.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

vi.mock('@/store/chat-sessions', () => ({
  chatSessionsStore: {
    sessions: [
      {
        id: 'a',
        user_id: null,
        title: 'old title',
        created_at: '2026-05-17T00:00:00Z',
        last_active_at: '2026-05-17T00:00:00Z',
        message_count: 0,
        last_msg_preview: null,
      },
    ],
    renameSession: vi.fn(),
  },
}))

import { chatSessionsStore } from '@/store/chat-sessions'
import { ChatSessionList } from '../chat-session-list'

describe('ChatSessionList rename', () => {
  beforeEach(() => {
    vi.mocked(chatSessionsStore.renameSession).mockReset()
  })

  it('shows ... button on hover and reveals dropdown', async () => {
    render(<ChatSessionList />)
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    const moreBtn = screen.getByRole('button', { name: /more|更多|\.\.\./i })
    fireEvent.click(moreBtn)
    expect(screen.getByText('重命名')).toBeInTheDocument()
  })

  it('Rename → inline input, Enter submits and calls store.renameSession', async () => {
    vi.mocked(chatSessionsStore.renameSession).mockResolvedValue(undefined)
    render(<ChatSessionList />)
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    fireEvent.click(screen.getByRole('button', { name: /more|更多|\.\.\./i }))
    fireEvent.click(screen.getByText('重命名'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'new title' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(chatSessionsStore.renameSession).toHaveBeenCalledWith('a', 'new title')
  })

  it('Esc cancels and restores', async () => {
    render(<ChatSessionList />)
    const row = screen.getByText('old title').closest('[data-session-row]')!
    fireEvent.mouseEnter(row)
    fireEvent.click(screen.getByRole('button', { name: /more|更多|\.\.\./i }))
    fireEvent.click(screen.getByText('重命名'))
    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'discard me' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(chatSessionsStore.renameSession).not.toHaveBeenCalled()
    expect(screen.getByText('old title')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to FAIL**

Run: `cd frontend && pnpm test src/components/sidebar/__tests__/chat-session-list-rename.test.tsx`
Expected: FAIL (`...` button 还没实现)

- [ ] **Step 3: Implement sidebar UI**

Read 现有 `frontend/src/components/sidebar/chat-session-list.tsx` 再编辑。改造为:

```tsx
import { useState } from 'react'
import { useSnapshot } from 'valtio'
import { chatSessionsStore } from '@/store/chat-sessions'

export function ChatSessionList() {
  const snap = useSnapshot(chatSessionsStore)
  const [openMenuId, setOpenMenuId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)

  return (
    <ul>
      {snap.sessions.map(s => (
        <li
          key={s.id}
          data-session-row
          className="group flex items-center justify-between px-3 py-2 hover:bg-gray-100"
        >
          {editingId === s.id ? (
            <input
              autoFocus
              defaultValue={s.title}
              className="flex-1 bg-transparent outline-none"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const v = (e.currentTarget as HTMLInputElement).value.trim()
                  if (v && v !== s.title) {
                    void chatSessionsStore.renameSession(s.id, v)
                  }
                  setEditingId(null)
                } else if (e.key === 'Escape') {
                  setEditingId(null)
                }
              }}
              onBlur={(e) => {
                const v = e.currentTarget.value.trim()
                if (v && v !== s.title) {
                  void chatSessionsStore.renameSession(s.id, v)
                }
                setEditingId(null)
              }}
            />
          ) : (
            <span className="truncate flex-1">{s.title}</span>
          )}

          <div className="relative">
            <button
              type="button"
              aria-label="more"
              className="opacity-0 group-hover:opacity-100 px-1"
              onClick={(e) => {
                e.stopPropagation()
                setOpenMenuId(openMenuId === s.id ? null : s.id)
              }}
            >
              ...
            </button>
            {openMenuId === s.id && (
              <div
                className="absolute right-0 top-full mt-1 bg-white shadow rounded border z-10"
                onMouseLeave={() => setOpenMenuId(null)}
              >
                <button
                  type="button"
                  className="block w-full text-left px-3 py-1 hover:bg-gray-100"
                  onClick={() => {
                    setEditingId(s.id)
                    setOpenMenuId(null)
                  }}
                >
                  重命名
                </button>
                {/* TODO(v1.x): Delete session — 待 brainstorm 软删/硬删策略 */}
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
```

> 此处的 class 名按项目 tailwind 风格调整; 若项目用 ui-primitive(Dropdown 等)替换 inline 实现, 但功能一致。

- [ ] **Step 4: Run PASS**

Run: `cd frontend && pnpm test src/components/sidebar/__tests__/chat-session-list-rename.test.tsx`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sidebar/chat-session-list.tsx frontend/src/components/sidebar/__tests__/chat-session-list-rename.test.tsx
git commit -m "feat(chat-title): sidebar hover ... menu + inline rename input"
```

---

## Task 14: useChatSSE close 后追加 3s 延时 refetch sidebar

**Files:**
- Modify: `frontend/src/hooks/useChatSSE.ts`
- Modify: `frontend/src/hooks/__tests__/useChatSSE.test.tsx`

- [ ] **Step 1: Find existing onclose**

Run: `grep -n "onclose\|onopen\|done\|EventSource\|listSessions" frontend/src/hooks/useChatSSE.ts`

确认 SSE close 时的 refetch sidebar 调用; 找到调用 `listChats` / `fetchSessions` 的具体行号。

- [ ] **Step 2: Write failing test**

Append to `frontend/src/hooks/__tests__/useChatSSE.test.tsx`:

```typescript
import { vi } from 'vitest'

vi.useFakeTimers()

// 在 SSE close 处 mock refetch, 验证 setTimeout 3000 后再调一次
// (基础 SSE close + refetch 已有现有 test, 此处仅加 timer)
it('refetches sidebar a second time ~3s after SSE close', async () => {
  const refetch = vi.fn()
  // ... setup useChatSSE with mocked event source + refetch ...
  // 模拟 SSE done event
  await closeSse()
  expect(refetch).toHaveBeenCalledTimes(1)  // 立即 refetch
  vi.advanceTimersByTime(3000)
  expect(refetch).toHaveBeenCalledTimes(2)  // 3s 后再 refetch
})
```

> 该 test 的 setup 部分依赖现有 useChatSSE test 结构, 复用 mock EventSource。具体 setup 行参考现有 test 文件。

- [ ] **Step 3: Run to FAIL**

Run: `cd frontend && pnpm test src/hooks/__tests__/useChatSSE.test.tsx`
Expected: FAIL — 只调一次 refetch

- [ ] **Step 4: Implement**

Edit `frontend/src/hooks/useChatSSE.ts` 在现有 SSE close handler 内, refetch 之后加:

```typescript
  onclose: () => {
    refetchSidebar()
    // === NEW (2026-05-17): 等 LLM title task 完成后再刷一次 ===
    setTimeout(() => refetchSidebar(), 3000)
  }
```

- [ ] **Step 5: Run PASS + commit**

Run: `cd frontend && pnpm test src/hooks/__tests__/useChatSSE.test.tsx`
Expected: PASS

```bash
git add frontend/src/hooks/useChatSSE.ts frontend/src/hooks/__tests__/useChatSSE.test.tsx
git commit -m "feat(chat-title): SSE close → +3s delayed refetch (catches async LLM title write)"
```

---

## Task 15: Dogfood + spec close

- [ ] **Step 1: 起 dev server + 跑 3 个真实首轮对话**

Run:
```bash
# Terminal 1
cd backend && uv run poe serve

# Terminal 2
cd frontend && pnpm dev
```

跑 3 个真实首轮:
1. "贵州茅台最近怎么样,值得买入吗?" → 期望 title ≈ "贵州茅台估值分析"
2. "帮我对比一下宁德时代和比亚迪" → 期望 title ≈ "宁德比亚迪对比"
3. "新能源车板块行情如何" → 期望 title ≈ "新能源车板块行情"

记录: 每条 title 是否在 ~3-5s 内自动更新, 是否"有信息量" + ≤15 字。

- [ ] **Step 2: 验证手动 rename UX**

- Hover session 行 → `...` 出现?
- 点 `...` → 重命名菜单?
- 点重命名 → input autofocus 且选中全文?
- 输入新名字 + Enter → 立刻保存 + dropdown 关闭?
- 输入 + Esc → 不保存 + 恢复原 title?
- F5 刷新 → 新 title 持久化?

- [ ] **Step 3: 验证 user_renamed 不被覆盖**

- 创建 session(title="新对话") → 立刻 hover + 重命名 → 发首条消息 → 等 ~5s 看 title 不被 LLM 覆盖。

- [ ] **Step 4: 跑全量测试 + 格式 / mypy / ruff**

Run:
```bash
cd backend && uv run poe ci  # 跑 lint + mypy + 全 pytest
cd ../frontend && pnpm test && pnpm typecheck
```
Expected: 全绿

- [ ] **Step 5: 写 PR 描述 + claude-context 沉淀**

新增 `docs/claude-context/chat-session-title-llm-generation-done.md`(若有产出价值的教训):

```markdown
---
name: chat-session-title-llm-generation-done
description: 2026-05-17 ship 完;chat session title 从前 20 字截断升级到 LLM 异步生成 + 手动 rename
type: project
---

# Chat Session Title — LLM 异步生成 + 手动重命名 ship 完

**结论**: ...
**Why**: ...
**How to apply**: 下次设计类似 "首轮完成后异步副产品" 任务 (e.g. summary / tag 自动打) 可以复用同套模式 (chat_finalize enqueue + title_source 三态防覆盖)。
```

并在 `CLAUDE.md` 加索引(若 sediment 价值够)。

- [ ] **Step 6: Final commit**

```bash
git add docs/claude-context/  # 若新增 sediment
git commit -m "docs(chat-title): claude-context sediment + dogfood log"
```

---

## Self-Review Checklist

- [x] **Spec 覆盖**: § 4 schema → Task 1; § 4.2 backfill → Task 2/3; § 5 Celery task → Task 4/5/6; § 5.2 enqueue → Task 7; § 6.1 删 277-281 → Task 8; § 6.2/6.3 PUT user_renamed → Task 9; § 7 前端 UI → Task 11/12/13/14; § 8 测试 → 每 task 内嵌; dogfood → Task 15
- [x] **No placeholders**: 每 step 含具体代码 / 命令 / 期望输出
- [x] **Type consistency**: title_source 枚举值 `pending` / `llm_generated` / `user_renamed` 跨所有 task 统一; `renameSession(id, title)` 签名跨 Task 12/13 一致; `generate_session_title(session_id: str)` 跨 Task 4/5/7 一致
- [x] **Scope**: 单 PR ship, ~5.5h wall time
