# Persona Editable UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Tier 1 persona block 加 ChatGPT 风列表式可编辑 UI，挂在 `/memory` 页"画像"默认 tab，物理分"你声明的 / agent 观察到的"双 section；user 区 agent 只读，agent 区用户改了自动升级到 user 区。

**Architecture:** 持久化层 markdown blob → `chat_memory_persona_items` (row-per-item with stable UUID + source enum) 升级；agent 的 `core_memory_append/replace` 加 PersonaService 转译层 + 服务层硬 enforce 双轨保护；`working_blocks.persona.content` 仍由 PersonaService 渲染回写以保 ChatPlanner / prefix cache 兼容。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2 sync Session + PostgreSQL（asyncpg）/ React 19 + antd 5 + valtio + vitest 4 + msw 2 + Playwright 1.59

**Spec:** `docs/superpowers/specs/2026-05-17-persona-editable-ui-design.md`

---

## File Structure

### Backend（新建 / 修改）

| 路径 | 类型 | 责任 |
|------|------|------|
| `backend/app/memory/models.py` | Modify | 加 `ChatMemoryPersonaItem` ORM model |
| `backend/app/memory/persona_items_md.py` | Create | 纯函数 markdown ↔ items roundtrip |
| `backend/app/memory/persona_service.py` | Create | PersonaService（list/add/update/delete + apply_agent_* + render） |
| `backend/app/router/persona_router.py` | Create | 4 REST endpoints |
| `backend/app/router/_persona_schemas.py` | Create | Pydantic schemas |
| `backend/app/app_main.py` | Modify | include persona_router + lifespan migration hook |
| `backend/app/memory/hierarchical.py` | Modify | core_memory_append/replace persona block 走 PersonaService |
| `backend/app/agents/chat/prompts/memory_tool_usage.md` | Modify | 加 "❌ 不要修改 [你声明的] 区" 段 |
| `backend/scripts/migrate_persona_blob_to_items.py` | Create | 一次性 backfill 老 persona blob → items |
| `backend/tests/unit/memory/test_persona_items_md.py` | Create | markdown ↔ items roundtrip |
| `backend/tests/unit/memory/test_persona_service.py` | Create | service 单元 + MagicMock |
| `backend/tests/unit/memory/test_persona_router.py` | Create | router schema + validation |
| `backend/tests/unit/memory/test_migrate_persona_blob.py` | Create | migration 单元 |
| `backend/tests/unit/agents/chat/test_system_prompt_template.py` | Modify | 既有文件加 1 个 assertion |
| `backend/tests/integration/memory/test_persona_e2e.py` | Create | 真 PG e2e |
| `backend/tests/integration/memory/test_persona_chat_planner_e2e.py` | Create | 端到端 prompt 注入验证 |
| `backend/tests/integration/memory/test_agent_double_track_protection.py` | Create | agent 试改 user 区被拦截 |

### Frontend（新建 / 修改）

| 路径 | 类型 | 责任 |
|------|------|------|
| `frontend/src/api/personaApi.ts` | Create | typed REST client |
| `frontend/src/components/memory/MemoryPersona.tsx` | Create | 主组件（双 section + 操作） |
| `frontend/src/components/memory/MemoryPersona.styles.ts` | Create | 样式（升级高亮动画 keyframes） |
| `frontend/src/pages/memory/index.tsx` | Modify | 加 'persona' tab 作默认 |
| `frontend/src/pages/chat/index.tsx` | Modify | 顶角加"我的画像"快捷入口（如目录不同则改实际 chat landing） |
| `frontend/src/components/memory/__tests__/MemoryPersona.test.tsx` | Create | vitest 单元 |
| `frontend/src/api/__tests__/personaApi.test.ts` | Create | client vitest |
| `frontend/tests/e2e/memory-persona.spec.ts` | Create | Playwright e2e |

---

## Phase 1 — Schema, Migration, PersonaService（Tasks 1–6）

### Task 1: 新表 `chat_memory_persona_items` ORM model + create_all 验证

**Files:**
- Modify: `backend/app/memory/models.py` (行 176-194 之后追加)
- Test: `backend/tests/unit/memory/test_persona_service.py`（新建，先放最小 schema 冒烟）

- [ ] **Step 1: 在 models.py 追加新表 ORM**

在 `backend/app/memory/models.py` 现有 `class ChatMemoryWorkingBlock` 之后（约行 195 后）追加：

```python
class ChatMemoryPersonaItem(Base):
    """Tier 1 persona items, row-per-item with stable UUID.

    spec § 4.1 — 替换 ChatMemoryWorkingBlock.persona 的单段 markdown blob
    形态，每条 bullet 独立 row 以支持 atomic UI 操作。
    """

    __tablename__ = "chat_memory_persona_items"

    item_id = Column(_UUID, primary_key=True, default=uuid4)
    user_id = Column(_UUID, ForeignKey("users.id"), nullable=False)
    source = Column(String(8), nullable=False)  # 'user' / 'agent'
    text = Column(String(500), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(_TS, nullable=False, server_default=func.now())
    updated_at = Column(
        _TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "ix_persona_items_user_source_pos",
            "user_id",
            "source",
            "position",
        ),
    )
```

如果 `Index` 未 import，在文件顶部 `from sqlalchemy import ...` 处加 `Index`。

- [ ] **Step 2: 新建 test 文件验证 schema 可创建**

新建 `backend/tests/unit/memory/test_persona_service.py`：

```python
"""PersonaService 单元测试 — Plan Phase 1.

L0 unit: 全 MagicMock，不触 DB。schema 完整性由 L1 integration 验。
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.memory.models import ChatMemoryPersonaItem


@pytest.mark.unit
def test_persona_item_model_basic_fields() -> None:
    """ChatMemoryPersonaItem 字段齐全 + Index 注册."""
    item = ChatMemoryPersonaItem(
        user_id=uuid4(),
        source="user",
        text="测试条目",
        position=0,
    )
    assert item.source == "user"
    assert item.text == "测试条目"
    assert item.position == 0

    table = ChatMemoryPersonaItem.__table__
    assert "chat_memory_persona_items" == table.name
    index_names = {idx.name for idx in table.indexes}
    assert "ix_persona_items_user_source_pos" in index_names
```

- [ ] **Step 3: 运行 test 确认 PASS**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 1 passed.

- [ ] **Step 4: mypy + ruff strict check**

```bash
uv run mypy backend/app/memory/models.py
uv run ruff check backend/app/memory/models.py backend/tests/unit/memory/test_persona_service.py
```

Expected: 全绿，零 issues。

- [ ] **Step 5: Commit**

```bash
git add backend/app/memory/models.py backend/tests/unit/memory/test_persona_service.py
git commit -m "feat(persona-ui): add ChatMemoryPersonaItem schema (Plan Task 1)"
```

---

### Task 2: markdown ↔ items 纯函数转换层

**Files:**
- Create: `backend/app/memory/persona_items_md.py`
- Create: `backend/tests/unit/memory/test_persona_items_md.py`

- [ ] **Step 1: 写失败的 roundtrip 测试**

新建 `backend/tests/unit/memory/test_persona_items_md.py`：

```python
"""markdown ↔ persona items 纯函数测试 — Plan Task 2.

spec § 4.3 渲染契约：固定中文 H2 `## 你声明的` / `## agent 观察到的`，
section 内 `- bullet` 一行一 item。
"""

from __future__ import annotations

import pytest

from app.memory.persona_items_md import ItemDraft, parse_markdown_to_drafts, render_items_to_markdown


@pytest.mark.unit
def test_render_empty_sections() -> None:
    md = render_items_to_markdown(user_items=[], agent_items=[])
    assert "## 你声明的" in md
    assert "## agent 观察到的" in md
    assert "_（暂无）_" in md  # 空 section 占位


@pytest.mark.unit
def test_render_only_user_items() -> None:
    md = render_items_to_markdown(
        user_items=["金融研究员", "保守稳健"],
        agent_items=[],
    )
    assert "- 金融研究员" in md
    assert "- 保守稳健" in md
    user_idx = md.index("## 你声明的")
    agent_idx = md.index("## agent 观察到的")
    assert user_idx < agent_idx


@pytest.mark.unit
def test_render_only_agent_items() -> None:
    md = render_items_to_markdown(
        user_items=[],
        agent_items=["关注新能源"],
    )
    assert "- 关注新能源" in md


@pytest.mark.unit
def test_parse_legacy_blob_no_headers() -> None:
    """老 blob 无 H2 → 全部当 agent 区."""
    blob = "- 持有茅台 2000 股\n- 关注高股息板块\n"
    drafts = parse_markdown_to_drafts(blob)
    assert len(drafts) == 2
    assert all(d.source == "agent" for d in drafts)
    assert drafts[0].text == "持有茅台 2000 股"
    assert drafts[1].text == "关注高股息板块"


@pytest.mark.unit
def test_parse_with_headers() -> None:
    blob = (
        "## 你声明的\n"
        "- 金融研究员\n"
        "\n"
        "## agent 观察到的\n"
        "- 关注新能源\n"
        "- 偏好高股息\n"
    )
    drafts = parse_markdown_to_drafts(blob)
    assert [d.source for d in drafts] == ["user", "agent", "agent"]
    assert [d.text for d in drafts] == [
        "金融研究员",
        "关注新能源",
        "偏好高股息",
    ]


@pytest.mark.unit
def test_parse_empty_blob() -> None:
    assert parse_markdown_to_drafts("") == []
    assert parse_markdown_to_drafts("   \n  ") == []


@pytest.mark.unit
def test_parse_skips_blank_lines_and_non_bullets() -> None:
    blob = "## 你声明的\n\n备注内容（不是 bullet）\n- 风险偏好稳健\n"
    drafts = parse_markdown_to_drafts(blob)
    assert len(drafts) == 1
    assert drafts[0].source == "user"
    assert drafts[0].text == "风险偏好稳健"


@pytest.mark.unit
def test_render_text_with_special_chars() -> None:
    md = render_items_to_markdown(
        user_items=["持仓: 茅台 (2000股) - 2026/03"],
        agent_items=[],
    )
    assert "持仓: 茅台 (2000股) - 2026/03" in md


@pytest.mark.unit
def test_parse_bullet_with_prefix_star() -> None:
    """支持 `* ` prefix（agent 可能输出 * 而非 -）."""
    blob = "* 看好科技股"
    drafts = parse_markdown_to_drafts(blob)
    assert drafts[0].text == "看好科技股"
    assert drafts[0].source == "agent"  # 无 H2 默认 agent
```

- [ ] **Step 2: 运行确认全 FAIL（module 不存在）**

```bash
uv run pytest backend/tests/unit/memory/test_persona_items_md.py -v
```

Expected: 9 errors，import 失败 "No module named 'app.memory.persona_items_md'"。

- [ ] **Step 3: 实现 `persona_items_md.py`**

新建 `backend/app/memory/persona_items_md.py`：

```python
"""markdown ↔ persona items 纯函数转换层.

spec § 4.3 渲染契约：固定中文 H2 `## 你声明的` / `## agent 观察到的`，
section 内 `- bullet` 一行一 item。

无 DB / DI 依赖 — PersonaService 用此层做 render_to_markdown 同步 working_block，
migration script 用 parse_markdown_to_drafts 把老 blob 拆成 items。
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER_USER = "## 你声明的"
HEADER_AGENT = "## agent 观察到的"
_EMPTY_PLACEHOLDER = "_（暂无）_"


@dataclass(frozen=True)
class ItemDraft:
    """parse 结果，不带 id（migration / 首次写入由 PersonaService 分配 UUID）."""

    text: str
    source: str  # 'user' / 'agent'
    position: int


def render_items_to_markdown(
    *, user_items: list[str], agent_items: list[str]
) -> str:
    """渲染两个 section 为固定格式 markdown。

    空 section 仍渲染 heading + `_（暂无）_` 占位（让 ChatPlanner prompt
    看到稳定结构，prefix cache 友好）。
    """

    def _section(header: str, items: list[str]) -> str:
        if not items:
            return f"{header}\n{_EMPTY_PLACEHOLDER}"
        bullet_lines = "\n".join(f"- {t}" for t in items)
        return f"{header}\n{bullet_lines}"

    return _section(HEADER_USER, user_items) + "\n\n" + _section(HEADER_AGENT, agent_items)


def parse_markdown_to_drafts(blob: str) -> list[ItemDraft]:
    """解析老 blob 为 drafts；无 H2 → 全部 source='agent'.

    rules:
    - 仅识别 `- ` 或 `* ` 开头的 bullet；其他行（heading / 空行 / 备注）跳过
    - position 在每个 section 内独立从 0 起编
    - placeholder `_（暂无）_` 不算 item
    """

    if not blob or not blob.strip():
        return []

    drafts: list[ItemDraft] = []
    current_source = "agent"
    user_pos = 0
    agent_pos = 0
    saw_any_header = False

    for raw_line in blob.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == HEADER_USER:
            current_source = "user"
            saw_any_header = True
            continue
        if line == HEADER_AGENT:
            current_source = "agent"
            saw_any_header = True
            continue

        if line == _EMPTY_PLACEHOLDER:
            continue

        if line.startswith("- "):
            text = line[2:].strip()
        elif line.startswith("* "):
            text = line[2:].strip()
        else:
            continue

        if not text:
            continue

        if saw_any_header and current_source == "user":
            drafts.append(ItemDraft(text=text, source="user", position=user_pos))
            user_pos += 1
        else:
            drafts.append(ItemDraft(text=text, source="agent", position=agent_pos))
            agent_pos += 1

    return drafts
```

- [ ] **Step 4: 运行 test 全 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_items_md.py -v
```

Expected: 9 passed。

- [ ] **Step 5: strict check + Commit**

```bash
uv run mypy backend/app/memory/persona_items_md.py
uv run ruff check backend/app/memory/persona_items_md.py backend/tests/unit/memory/test_persona_items_md.py
git add backend/app/memory/persona_items_md.py backend/tests/unit/memory/test_persona_items_md.py
git commit -m "feat(persona-ui): markdown<->items roundtrip pure funcs (Plan Task 2)"
```

---

### Task 3: PersonaService — list / add / update / delete

**Files:**
- Create: `backend/app/memory/persona_service.py`
- Modify: `backend/tests/unit/memory/test_persona_service.py`（追加测试）

- [ ] **Step 1: 追加 CRUD 测试到 test_persona_service.py**

打开 `backend/tests/unit/memory/test_persona_service.py`，文件末尾追加：

```python
from unittest.mock import MagicMock, patch

from app.memory.persona_service import PersonaService


def _mk_session_factory() -> tuple[MagicMock, MagicMock]:
    """构造 mock session_factory 跟 mock session，方便测试 commit/rollback 调用."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.first.return_value = None
    factory = MagicMock(return_value=session)
    return factory, session


@pytest.mark.unit
def test_list_items_empty() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    result = service.list_items(user_id=uuid4())

    assert result == {"user_declared": [], "agent_inferred": []}
    session.close.assert_called_once()


@pytest.mark.unit
def test_add_item_user_section() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)
    user_id = uuid4()

    item = service.add_item(user_id=user_id, text="保守稳健", target_section="user")

    assert item.source == "user"
    assert item.text == "保守稳健"
    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.unit
def test_add_item_strips_and_validates_length() -> None:
    factory, _ = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(ValueError, match="empty"):
        service.add_item(user_id=uuid4(), text="   ", target_section="user")

    with pytest.raises(ValueError, match="too long"):
        service.add_item(user_id=uuid4(), text="a" * 501, target_section="user")


@pytest.mark.unit
def test_update_item_text_keeps_source() -> None:
    """改 source='user' 的 item，source 不变."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="原文",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    updated = service.update_item(
        user_id=existing.user_id, item_id=existing.item_id, text="新内容"
    )

    assert updated.source == "user"
    assert updated.text == "新内容"
    session.commit.assert_called_once()


@pytest.mark.unit
def test_update_item_agent_source_upgrades_to_user() -> None:
    """改 agent 区条目自动升级到 user 区 — spec 决策 3."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="agent",
        text="原 agent 推断",
        position=5,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    # 模拟查 user 区当前 max position
    max_query = MagicMock()
    max_query.scalar.return_value = 2
    session.query.return_value.filter_by.return_value.with_entities.return_value = max_query
    service = PersonaService(pg_session_factory=factory)

    updated = service.update_item(
        user_id=existing.user_id, item_id=existing.item_id, text="改后内容"
    )

    assert updated.source == "user"
    assert updated.position == 3  # max(2) + 1


@pytest.mark.unit
def test_update_item_not_found_raises() -> None:
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(LookupError):
        service.update_item(user_id=uuid4(), item_id=uuid4(), text="x")


@pytest.mark.unit
def test_delete_item_calls_delete_and_commit() -> None:
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="待删",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    service.delete_item(user_id=existing.user_id, item_id=existing.item_id)

    session.delete.assert_called_once_with(existing)
    session.commit.assert_called_once()


@pytest.mark.unit
def test_delete_item_not_found_raises() -> None:
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.first.return_value = None
    service = PersonaService(pg_session_factory=factory)

    with pytest.raises(LookupError):
        service.delete_item(user_id=uuid4(), item_id=uuid4())
```

- [ ] **Step 2: 运行 test 全 FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 8 new tests 失败 / errors（PersonaService 未定义）。

- [ ] **Step 3: 实现 PersonaService（最小覆盖 CRUD）**

新建 `backend/app/memory/persona_service.py`：

```python
"""PersonaService — Tier 1 persona block 的 atomic 持久化层.

spec § 3 / § 7.x：暴露 list/add/update/delete + apply_agent_append/replace + render_to_markdown。

CRUD 由 UI REST endpoint 调；apply_agent_* 由 HierarchicalMemory.core_memory_*
转译；render_to_markdown 由 _sync_to_working_block 写回 ChatMemoryWorkingBlock
保 ChatPlanner / prefix cache 兼容。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, TypedDict
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryPersonaItem
from app.memory.persona_items_md import render_items_to_markdown

logger = logging.getLogger(__name__)

_TEXT_MAX = 500
TargetSection = Literal["user", "agent"]


class PersonaListResult(TypedDict):
    user_declared: list[ChatMemoryPersonaItem]
    agent_inferred: list[ChatMemoryPersonaItem]


class PersonaService:
    def __init__(self, pg_session_factory: Callable[[], Session]) -> None:
        self._session_factory = pg_session_factory

    # ----- CRUD -----

    def list_items(self, *, user_id: UUID) -> PersonaListResult:
        session = self._session_factory()
        try:
            user_items = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="user")
                .order_by(ChatMemoryPersonaItem.position.asc())
                .all()
            )
            agent_items = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="agent")
                .order_by(ChatMemoryPersonaItem.position.asc())
                .all()
            )
            return {"user_declared": list(user_items), "agent_inferred": list(agent_items)}
        finally:
            session.close()

    def add_item(
        self,
        *,
        user_id: UUID,
        text: str,
        target_section: TargetSection,
    ) -> ChatMemoryPersonaItem:
        normalized = self._validate_text(text)
        session = self._session_factory()
        try:
            position = self._next_position(session, user_id=user_id, source=target_section)
            item = ChatMemoryPersonaItem(
                item_id=uuid4(),
                user_id=user_id,
                source=target_section,
                text=normalized,
                position=position,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            self._sync_to_working_block(session=None, user_id=user_id)
            return item
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_item(
        self, *, user_id: UUID, item_id: UUID, text: str
    ) -> ChatMemoryPersonaItem:
        normalized = self._validate_text(text)
        session = self._session_factory()
        try:
            item = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(item_id=item_id, user_id=user_id)
                .first()
            )
            if item is None:
                raise LookupError(f"persona item {item_id} not found for user {user_id}")

            item.text = normalized

            if item.source == "agent":
                # spec 决策 3: 改 agent 区条 → 升级到 user 区，position 改为 user max+1
                item.source = "user"
                item.position = self._next_position(session, user_id=user_id, source="user")

            session.commit()
            session.refresh(item)
            session.expunge(item)
            self._sync_to_working_block(session=None, user_id=user_id)
            return item
        except LookupError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_item(self, *, user_id: UUID, item_id: UUID) -> None:
        session = self._session_factory()
        try:
            item = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(item_id=item_id, user_id=user_id)
                .first()
            )
            if item is None:
                raise LookupError(f"persona item {item_id} not found for user {user_id}")
            session.delete(item)
            session.commit()
            self._sync_to_working_block(session=None, user_id=user_id)
        except LookupError:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ----- internal helpers -----

    @staticmethod
    def _validate_text(text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("persona item text empty")
        if len(normalized) > _TEXT_MAX:
            raise ValueError(f"persona item text too long (max {_TEXT_MAX})")
        return normalized

    @staticmethod
    def _next_position(session: Session, *, user_id: UUID, source: TargetSection) -> int:
        max_pos = (
            session.query(ChatMemoryPersonaItem)
            .filter_by(user_id=user_id, source=source)
            .with_entities(ChatMemoryPersonaItem.position)
            .order_by(ChatMemoryPersonaItem.position.desc())
            .first()
        )
        if max_pos is None:
            return 0
        # mock scenarios may return scalar via different path; tolerate both
        if isinstance(max_pos, tuple):
            value = int(max_pos[0])
        elif hasattr(max_pos, "scalar"):
            value = int(max_pos.scalar() or 0)
        else:
            try:
                value = int(max_pos[0])
            except Exception:
                value = int(max_pos.position)
        return value + 1

    def _sync_to_working_block(self, *, session: Session | None, user_id: UUID) -> None:
        """渲染 items → markdown → 写回 ChatMemoryWorkingBlock.persona.content.

        Task 5 才接通真正的写回逻辑；此 Task 仅保留 hook，确保 caller 调用点稳定。
        """
        logger.debug("persona _sync_to_working_block hook for user=%s (Task 5 wires writer)", user_id)
```

- [ ] **Step 4: 运行 test 全 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 9 passed (1 schema + 8 CRUD).

- [ ] **Step 5: strict check + commit**

```bash
uv run mypy backend/app/memory/persona_service.py
uv run ruff check backend/app/memory/persona_service.py backend/tests/unit/memory/test_persona_service.py
git add backend/app/memory/persona_service.py backend/tests/unit/memory/test_persona_service.py
git commit -m "feat(persona-ui): PersonaService CRUD + UUID/source/position semantics (Plan Task 3)"
```

---

### Task 4: PersonaService.apply_agent_append / apply_agent_replace（agent 转译层 + 双轨保护）

**Files:**
- Modify: `backend/app/memory/persona_service.py`
- Modify: `backend/tests/unit/memory/test_persona_service.py`

- [ ] **Step 1: 追加 agent 转译测试**

打开 `test_persona_service.py` 末尾追加：

```python
@pytest.mark.unit
def test_apply_agent_append_splits_lines() -> None:
    """多行 content 切多条；prefix `- ` / `* ` 自动去除."""
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_append(
        user_id=uuid4(), content="- 看好新能源\n* 关注高股息\n空行不算\n"
    )

    assert [i.text for i in items] == ["看好新能源", "关注高股息", "空行不算"]
    assert all(i.source == "agent" for i in items)
    assert session.add.call_count == 3
    session.commit.assert_called_once()


@pytest.mark.unit
def test_apply_agent_append_empty_noop() -> None:
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)
    items = service.apply_agent_append(user_id=uuid4(), content="   \n  ")
    assert items == []
    session.add.assert_not_called()


@pytest.mark.unit
def test_apply_agent_replace_match_agent_item() -> None:
    """命中 source='agent' 的 item → 改 text，source 保持 agent."""
    factory, session = _mk_session_factory()
    target = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="agent",
        text="保守",
        position=0,
    )
    session.query.return_value.filter_by.return_value.all.return_value = [target]
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(
        user_id=target.user_id, old_content="保守", new_content="偏成长"
    )

    assert items[0].text == "偏成长"
    assert items[0].source == "agent"
    session.commit.assert_called_once()


@pytest.mark.unit
def test_apply_agent_replace_never_match_user_item() -> None:
    """即使 text 一致也不能动 source='user' 的 item — 双轨保护."""
    factory, session = _mk_session_factory()
    user_item = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="保守稳健",
        position=0,
    )
    # filter_by(source='agent') 应返回空
    session.query.return_value.filter_by.return_value.all.return_value = []
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(
        user_id=user_item.user_id, old_content="保守稳健", new_content="激进"
    )

    # fallback: 没匹配到 → append 一条新 agent item
    assert len(items) == 1
    assert items[0].source == "agent"
    assert items[0].text == "激进"


@pytest.mark.unit
def test_apply_agent_replace_no_match_falls_back_to_append() -> None:
    """spec § 8.2: 未找到 → 降级为 apply_agent_append + log warn."""
    factory, session = _mk_session_factory()
    session.query.return_value.filter_by.return_value.all.return_value = []
    service = PersonaService(pg_session_factory=factory)

    items = service.apply_agent_replace(
        user_id=uuid4(), old_content="不存在的", new_content="新条"
    )

    assert len(items) == 1
    assert items[0].text == "新条"
    assert items[0].source == "agent"
```

- [ ] **Step 2: 运行 test FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 5 new tests 失败（apply_agent_* 方法未实现）。

- [ ] **Step 3: 在 PersonaService 类内追加 apply_agent_* 方法**

打开 `backend/app/memory/persona_service.py`，在 `delete_item` 之后、`_validate_text` 之前追加：

```python
    # ----- agent write API (HierarchicalMemory.core_memory_* 转译) -----

    def apply_agent_append(
        self, *, user_id: UUID, content: str
    ) -> list[ChatMemoryPersonaItem]:
        """append 多行 content 为 agent 区 items.

        prefix `- ` / `* ` 自动去除；空行跳过；每行一 item。
        """

        normalized_lines = self._normalize_agent_lines(content)
        if not normalized_lines:
            return []

        session = self._session_factory()
        try:
            base_pos = self._next_position(session, user_id=user_id, source="agent")
            new_items: list[ChatMemoryPersonaItem] = []
            for offset, text in enumerate(normalized_lines):
                item = ChatMemoryPersonaItem(
                    item_id=uuid4(),
                    user_id=user_id,
                    source="agent",
                    text=text,
                    position=base_pos + offset,
                )
                session.add(item)
                new_items.append(item)
            session.commit()
            for item in new_items:
                session.refresh(item)
                session.expunge(item)
            self._sync_to_working_block(session=None, user_id=user_id)
            return new_items
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def apply_agent_replace(
        self, *, user_id: UUID, old_content: str, new_content: str
    ) -> list[ChatMemoryPersonaItem]:
        """agent 区 match → 改 text；未匹配（含 user 区命中）→ fallback append.

        双轨保护：filter_by(source='agent') 永远不会扫到 user 区行 — 即使 text
        完全一致也不会被改。
        """

        old_normalized = old_content.strip()
        new_normalized = new_content.strip()
        if not new_normalized:
            logger.warning("apply_agent_replace: new_content empty after strip, no-op")
            return []

        session = self._session_factory()
        try:
            candidates = (
                session.query(ChatMemoryPersonaItem)
                .filter_by(user_id=user_id, source="agent")
                .all()
            )
            matched = [c for c in candidates if c.text.strip() == old_normalized]
            if matched:
                target = matched[0]
                target.text = new_normalized
                session.commit()
                session.refresh(target)
                session.expunge(target)
                self._sync_to_working_block(session=None, user_id=user_id)
                return [target]
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        # fallback: 没命中 → append 一条新 agent item（含命中 user 区也走这）
        logger.warning(
            "apply_agent_replace: old_content not matched in agent section "
            "(user_id=%s, old_len=%d) — falling back to append",
            user_id,
            len(old_normalized),
        )
        return self.apply_agent_append(user_id=user_id, content=new_normalized)

    @staticmethod
    def _normalize_agent_lines(content: str) -> list[str]:
        out: list[str] = []
        for raw in content.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("- "):
                line = line[2:].strip()
            elif line.startswith("* "):
                line = line[2:].strip()
            if line:
                out.append(line)
        return out
```

- [ ] **Step 4: 运行 test 全 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 14 passed（9 + 5 新）。

- [ ] **Step 5: strict + commit**

```bash
uv run mypy backend/app/memory/persona_service.py
uv run ruff check backend/app/memory/persona_service.py
git add backend/app/memory/persona_service.py backend/tests/unit/memory/test_persona_service.py
git commit -m "feat(persona-ui): PersonaService.apply_agent_append/replace with double-track guard (Plan Task 4)"
```

---

### Task 5: render_to_markdown + _sync_to_working_block 接通 ChatMemoryWorkingBlock

**Files:**
- Modify: `backend/app/memory/persona_service.py`
- Modify: `backend/tests/unit/memory/test_persona_service.py`

- [ ] **Step 1: 追加 render + sync 测试**

`test_persona_service.py` 末尾追加：

```python
from app.memory.models import ChatMemoryWorkingBlock


@pytest.mark.unit
def test_render_to_markdown_uses_items() -> None:
    """render_to_markdown 接 persona_items_md.render_items_to_markdown."""
    factory, session = _mk_session_factory()
    user_id = uuid4()
    user_rows = [
        ChatMemoryPersonaItem(user_id=user_id, source="user", text="A", position=0),
    ]
    agent_rows = [
        ChatMemoryPersonaItem(user_id=user_id, source="agent", text="B", position=0),
        ChatMemoryPersonaItem(user_id=user_id, source="agent", text="C", position=1),
    ]

    def _query_dispatch(*_a, **_kw):  # type: ignore[no-untyped-def]
        m = MagicMock()
        # 简化：分别针对 user / agent filter_by 返回不同 mock
        m.filter_by.side_effect = lambda **kw: {
            "user": MagicMock(order_by=lambda *_a, **_kw: MagicMock(all=lambda: user_rows)),
            "agent": MagicMock(order_by=lambda *_a, **_kw: MagicMock(all=lambda: agent_rows)),
        }[kw["source"]]
        return m

    session.query.side_effect = _query_dispatch
    service = PersonaService(pg_session_factory=factory)

    md = service.render_to_markdown(user_id=user_id)

    assert "- A" in md
    assert "- B" in md
    assert "- C" in md
    assert md.index("- A") < md.index("- B")  # user 区先于 agent 区


@pytest.mark.unit
def test_sync_to_working_block_upserts_existing() -> None:
    """已有 persona working_block → 更新 content."""
    factory, session = _mk_session_factory()
    user_id = uuid4()
    existing_block = ChatMemoryWorkingBlock(
        user_id=user_id, block_name="persona", content="old", max_tokens=500, token_count=0
    )

    def _block_query(*_a, **_kw):  # type: ignore[no-untyped-def]
        m = MagicMock()
        m.filter_by.return_value.first.return_value = existing_block
        return m

    def _items_query(*_a, **_kw):  # type: ignore[no-untyped-def]
        m = MagicMock()
        m.filter_by.return_value.order_by.return_value.all.return_value = []
        return m

    call_count = {"n": 0}

    def _dispatch(model_cls):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if model_cls is ChatMemoryWorkingBlock:
            return _block_query()
        return _items_query()

    session.query.side_effect = _dispatch
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(session=None, user_id=user_id)

    assert "## 你声明的" in existing_block.content
    session.commit.assert_called()


@pytest.mark.unit
def test_sync_to_working_block_inserts_new() -> None:
    """无既有 persona block → insert."""
    factory, session = _mk_session_factory()

    def _block_query(*_a, **_kw):  # type: ignore[no-untyped-def]
        m = MagicMock()
        m.filter_by.return_value.first.return_value = None  # 不存在
        return m

    def _items_query(*_a, **_kw):  # type: ignore[no-untyped-def]
        m = MagicMock()
        m.filter_by.return_value.order_by.return_value.all.return_value = []
        return m

    def _dispatch(model_cls):  # type: ignore[no-untyped-def]
        if model_cls is ChatMemoryWorkingBlock:
            return _block_query()
        return _items_query()

    session.query.side_effect = _dispatch
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(session=None, user_id=uuid4())

    session.add.assert_called()
    session.commit.assert_called()
```

- [ ] **Step 2: 运行 FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v -k "render_to_markdown or sync_to_working_block"
```

Expected: 3 fail（render_to_markdown 未实现 / _sync_to_working_block 仅 hook）。

- [ ] **Step 3: 实现 render_to_markdown + 改写 _sync_to_working_block**

打开 `backend/app/memory/persona_service.py`，在 import 段追加：

```python
from app.memory.models import ChatMemoryWorkingBlock
from app.memory.persona_items_md import render_items_to_markdown
```

（如已 import `render_items_to_markdown` 则只补 `ChatMemoryWorkingBlock`。）

在 class 内、`apply_agent_*` 之后、`_validate_text` 之前追加：

```python
    # ----- render / sync -----

    def render_to_markdown(self, *, user_id: UUID) -> str:
        result = self.list_items(user_id=user_id)
        return render_items_to_markdown(
            user_items=[i.text for i in result["user_declared"]],
            agent_items=[i.text for i in result["agent_inferred"]],
        )
```

替换原 `_sync_to_working_block` 方法为：

```python
    def _sync_to_working_block(self, *, session: Session | None, user_id: UUID) -> None:
        """渲染 items → markdown → 写回 ChatMemoryWorkingBlock.persona.content.

        保 ChatPlanner Phase 1 render_persona_markdown 路径不变；下次 session
        起手 frozen snapshot 时自动拿最新值。
        """

        markdown = self.render_to_markdown(user_id=user_id)
        own_session = session is None
        sess = session or self._session_factory()
        try:
            block = (
                sess.query(ChatMemoryWorkingBlock)
                .filter_by(user_id=user_id, block_name="persona")
                .first()
            )
            if block is None:
                block = ChatMemoryWorkingBlock(
                    user_id=user_id,
                    block_name="persona",
                    content=markdown,
                    max_tokens=500,
                    token_count=0,
                )
                sess.add(block)
            else:
                block.content = markdown
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            if own_session:
                sess.close()
```

- [ ] **Step 4: 运行 test 全 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_service.py -v
```

Expected: 17 passed (14 + 3 新)。

- [ ] **Step 5: strict + commit**

```bash
uv run mypy backend/app/memory/persona_service.py
uv run ruff check backend/app/memory/persona_service.py
git add backend/app/memory/persona_service.py backend/tests/unit/memory/test_persona_service.py
git commit -m "feat(persona-ui): render_to_markdown + sync to ChatMemoryWorkingBlock (Plan Task 5)"
```

---

### Task 6: Migration script + lifespan hook

**Files:**
- Create: `backend/scripts/migrate_persona_blob_to_items.py`
- Create: `backend/tests/unit/memory/test_migrate_persona_blob.py`
- Modify: `backend/app/app_main.py`

- [ ] **Step 1: 写 migration 单元测试**

新建 `backend/tests/unit/memory/test_migrate_persona_blob.py`：

```python
"""Migration 单元 — Plan Task 6.

spec § 9: 一次性 backfill 老 persona blob → items 表，全部标 source='agent'.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from scripts.migrate_persona_blob_to_items import migrate_user_persona, parse_existing_blob_for_user


@pytest.mark.unit
def test_parse_existing_blob_no_blob_returns_empty() -> None:
    drafts = parse_existing_blob_for_user(
        existing_blob=None,
    )
    assert drafts == []


@pytest.mark.unit
def test_parse_existing_blob_marks_all_agent() -> None:
    """老 blob 没有 H2 → 全部 source='agent'."""
    blob = "- 持有茅台\n- 关注新能源\n"
    drafts = parse_existing_blob_for_user(existing_blob=blob)
    assert len(drafts) == 2
    assert all(d.source == "agent" for d in drafts)


@pytest.mark.unit
def test_migrate_user_persona_skips_if_already_has_items() -> None:
    """已经有 persona_items → skip（避免重复跑）."""
    session = MagicMock()
    user_id = uuid4()
    session.query.return_value.filter_by.return_value.count.return_value = 3

    result = migrate_user_persona(session=session, user_id=user_id)

    assert result == {"status": "skipped", "reason": "items already present"}
    session.add.assert_not_called()


@pytest.mark.unit
def test_migrate_user_persona_inserts_items_from_blob() -> None:
    session = MagicMock()
    user_id = uuid4()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    block = ChatMemoryWorkingBlock(
        user_id=user_id,
        block_name="persona",
        content="- 关注高股息\n- 偏好长期持有\n",
        max_tokens=500,
        token_count=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = block

    result = migrate_user_persona(session=session, user_id=user_id)

    assert result["status"] == "migrated"
    assert result["count"] == 2
    assert session.add.call_count == 2
    added_objects = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(o, ChatMemoryPersonaItem) for o in added_objects)
    session.commit.assert_called_once()


@pytest.mark.unit
def test_migrate_user_persona_no_block_no_op() -> None:
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    session.query.return_value.filter_by.return_value.first.return_value = None

    result = migrate_user_persona(session=session, user_id=uuid4())

    assert result == {"status": "noop", "reason": "no persona block"}
```

- [ ] **Step 2: 运行 test FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_migrate_persona_blob.py -v
```

Expected: 5 errors（module 不存在）。

- [ ] **Step 3: 写 migration script**

新建 `backend/scripts/migrate_persona_blob_to_items.py`：

```python
"""一次性 backfill: 老 persona blob → chat_memory_persona_items (Plan Task 6).

调用时机：app_main lifespan startup 时检测一次。
跑过的标记位记在每个 user 的 working_block.token_count 字段（向后兼容方案），
而是用 "if 该 user 已有 persona_items 则 skip" 做幂等判断。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_items_md import ItemDraft, parse_markdown_to_drafts

logger = logging.getLogger(__name__)


def parse_existing_blob_for_user(existing_blob: str | None) -> list[ItemDraft]:
    """老 blob 无 H2 → drafts 全部 source='agent'（parse_markdown_to_drafts 默认行为）."""
    if not existing_blob:
        return []
    return parse_markdown_to_drafts(existing_blob)


def migrate_user_persona(*, session: Session, user_id: UUID) -> dict[str, Any]:
    """迁移单用户 — 幂等。"""

    existing_count = (
        session.query(ChatMemoryPersonaItem).filter_by(user_id=user_id).count()
    )
    if existing_count > 0:
        return {"status": "skipped", "reason": "items already present"}

    block = (
        session.query(ChatMemoryWorkingBlock)
        .filter_by(user_id=user_id, block_name="persona")
        .first()
    )
    if block is None:
        return {"status": "noop", "reason": "no persona block"}

    drafts = parse_existing_blob_for_user(existing_blob=str(block.content))
    if not drafts:
        return {"status": "noop", "reason": "empty blob"}

    for d in drafts:
        item = ChatMemoryPersonaItem(
            item_id=uuid4(),
            user_id=user_id,
            source=d.source,
            text=d.text,
            position=d.position,
        )
        session.add(item)

    session.commit()
    return {"status": "migrated", "count": len(drafts)}


def migrate_all(session_factory: Any) -> dict[str, int]:
    """遍历所有有 persona block 的 user 跑一次."""
    stats = {"migrated": 0, "skipped": 0, "noop": 0, "errors": 0}
    session = session_factory()
    try:
        users = (
            session.query(ChatMemoryWorkingBlock.user_id)
            .filter_by(block_name="persona")
            .distinct()
            .all()
        )
        user_ids = [row[0] for row in users]
    finally:
        session.close()

    for uid in user_ids:
        per_user_session = session_factory()
        try:
            result = migrate_user_persona(session=per_user_session, user_id=uid)
            stats[result["status"]] = stats.get(result["status"], 0) + 1
        except Exception as exc:
            logger.warning("persona migration failed user=%s: %s", uid, exc)
            stats["errors"] += 1
        finally:
            per_user_session.close()

    return stats
```

- [ ] **Step 4: 运行 test PASS**

```bash
uv run pytest backend/tests/unit/memory/test_migrate_persona_blob.py -v
```

Expected: 5 passed。

- [ ] **Step 5: 在 app_main.py lifespan 注册 migration**

打开 `backend/app/app_main.py`，找到 lifespan 函数（约行 76 起），在 startup 段（任何已有 `# 启动时执行` 之后、`yield` 之前）追加：

```python
    # Persona Editable UI Plan Task 6 — 一次性 backfill (幂等)
    try:
        from scripts.migrate_persona_blob_to_items import migrate_all
        from app.memory.session_factory import get_persona_session_factory  # 若文件不存在，用既有 PG factory

        stats = migrate_all(get_persona_session_factory())
        logger.info("persona migration stats: %s", stats)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persona migration startup hook failed: %s", exc)
```

**注意**: `get_persona_session_factory` 是占位名 — 在实际项目中应复用 `app.memory.di` 或 `app.memory.session_factory` 已暴露的同步 session factory。Subagent 实施时**先 grep 找到现有的 sync session factory 入口**（如 `from app.db.session import SessionLocal` 之类），改成正确 import。如找不到，新建 `backend/app/memory/session_factory.py` 暴露：

```python
from sqlalchemy.orm import sessionmaker
from app.db.engine import engine_sync  # 项目 PG sync engine

_SessionLocal = sessionmaker(bind=engine_sync, expire_on_commit=False, future=True)

def get_persona_session_factory():
    return _SessionLocal
```

并跑 `grep -r "sessionmaker\|SessionLocal" backend/app/ -l` 验证项目里同步 session 入口的真正路径。

- [ ] **Step 6: import smoke test**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
uv run python -c "from app.app_main import app; print('ok')"
```

Expected: print "ok" 无 ImportError。

- [ ] **Step 7: strict + commit**

```bash
uv run mypy backend/app/app_main.py backend/scripts/migrate_persona_blob_to_items.py
uv run ruff check backend/app/app_main.py backend/scripts/migrate_persona_blob_to_items.py backend/tests/unit/memory/test_migrate_persona_blob.py
git add backend/app/app_main.py backend/scripts/migrate_persona_blob_to_items.py backend/tests/unit/memory/test_migrate_persona_blob.py
git commit -m "feat(persona-ui): backfill migration script + lifespan hook (Plan Task 6)"
```

---

## Phase 2 — REST endpoints + L1 e2e（Tasks 7–10）

### Task 7: Pydantic schemas

**Files:**
- Create: `backend/app/router/_persona_schemas.py`
- Create: `backend/tests/unit/memory/test_persona_router.py`（最小 schema 测试，行为测试在 Task 8）

- [ ] **Step 1: 写 schema 测试**

新建 `backend/tests/unit/memory/test_persona_router.py`：

```python
"""persona_router Pydantic schema + 路由行为测试 (Plan Tasks 7-8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.router._persona_schemas import (
    PersonaItemOut,
    PersonaListResponse,
    PersonaPatchRequest,
    PersonaPostRequest,
)


@pytest.mark.unit
def test_post_request_strips_text() -> None:
    req = PersonaPostRequest(text="  保守稳健  ", target_section="user")
    assert req.text == "保守稳健"


@pytest.mark.unit
def test_post_request_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="   ", target_section="user")


@pytest.mark.unit
def test_post_request_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="a" * 501, target_section="user")


@pytest.mark.unit
def test_post_request_target_section_enum() -> None:
    with pytest.raises(ValidationError):
        PersonaPostRequest(text="x", target_section="other")  # type: ignore[arg-type]


@pytest.mark.unit
def test_patch_request_validates_text() -> None:
    PersonaPatchRequest(text="updated")
    with pytest.raises(ValidationError):
        PersonaPatchRequest(text="")
    with pytest.raises(ValidationError):
        PersonaPatchRequest(text="a" * 501)


@pytest.mark.unit
def test_list_response_serializes() -> None:
    resp = PersonaListResponse(user_declared=[], agent_inferred=[])
    assert resp.model_dump() == {"user_declared": [], "agent_inferred": []}


@pytest.mark.unit
def test_item_out_extra_forbid() -> None:
    with pytest.raises(ValidationError):
        PersonaItemOut(  # type: ignore[call-arg]
            id="00000000-0000-0000-0000-000000000000",
            text="x",
            source="user",
            position=0,
            created_at="2026-05-17T00:00:00+00:00",
            updated_at="2026-05-17T00:00:00+00:00",
            extra_field="boom",
        )
```

- [ ] **Step 2: 运行 FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_persona_router.py -v
```

Expected: 7 errors（module 不存在）。

- [ ] **Step 3: 写 schemas**

新建 `backend/app/router/_persona_schemas.py`：

```python
"""persona_router Pydantic schemas (Plan Task 7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TargetSection = Literal["user", "agent"]


class PersonaItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    text: str
    source: TargetSection
    position: int
    created_at: datetime
    updated_at: datetime


class PersonaListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_declared: list[PersonaItemOut] = Field(default_factory=list)
    agent_inferred: list[PersonaItemOut] = Field(default_factory=list)


class PersonaPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    target_section: TargetSection

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty after strip")
        if len(stripped) > 500:
            raise ValueError("text too long")
        return stripped


class PersonaPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def _strip_and_check(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty after strip")
        if len(stripped) > 500:
            raise ValueError("text too long")
        return stripped
```

- [ ] **Step 4: 运行 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_router.py -v
```

Expected: 7 passed。

- [ ] **Step 5: strict + commit**

```bash
uv run mypy backend/app/router/_persona_schemas.py
uv run ruff check backend/app/router/_persona_schemas.py backend/tests/unit/memory/test_persona_router.py
git add backend/app/router/_persona_schemas.py backend/tests/unit/memory/test_persona_router.py
git commit -m "feat(persona-ui): Pydantic schemas for persona_router (Plan Task 7)"
```

---

### Task 8: persona_router 4 endpoints

**Files:**
- Create: `backend/app/router/persona_router.py`
- Modify: `backend/tests/unit/memory/test_persona_router.py`

- [ ] **Step 1: 追加 router 行为测试**

打开 `test_persona_router.py` 末尾追加：

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.memory.models import ChatMemoryPersonaItem
from app.router.persona_router import get_persona_service, router as persona_router


def _fake_item(**overrides: object) -> ChatMemoryPersonaItem:
    item = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="测试",
        position=0,
    )
    item.created_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    item.updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    for k, v in overrides.items():
        setattr(item, k, v)
    return item


def _client(service: MagicMock, user_id: object | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(persona_router)
    app.dependency_overrides[get_persona_service] = lambda: service
    # 假装 current_user dependency 已注入 — 实际 endpoint 用 get_current_user_required
    from app.router.persona_router import _get_current_user_id

    app.dependency_overrides[_get_current_user_id] = lambda: user_id or uuid4()
    return TestClient(app)


@pytest.mark.unit
def test_get_persona_returns_two_sections() -> None:
    service = MagicMock()
    user_item = _fake_item(source="user", text="A")
    agent_item = _fake_item(source="agent", text="B")
    service.list_items.return_value = {
        "user_declared": [user_item],
        "agent_inferred": [agent_item],
    }
    client = _client(service)

    resp = client.get("/api/v0/persona")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["user_declared"]) == 1
    assert body["user_declared"][0]["text"] == "A"
    assert len(body["agent_inferred"]) == 1


@pytest.mark.unit
def test_post_persona_item_creates() -> None:
    service = MagicMock()
    new_item = _fake_item(text="新条")
    service.add_item.return_value = new_item
    client = _client(service)

    resp = client.post(
        "/api/v0/persona/items",
        json={"text": "新条", "target_section": "user"},
    )

    assert resp.status_code == 201
    assert resp.json()["text"] == "新条"


@pytest.mark.unit
def test_post_persona_rejects_invalid_payload() -> None:
    client = _client(MagicMock())
    resp = client.post(
        "/api/v0/persona/items",
        json={"text": "", "target_section": "user"},
    )
    assert resp.status_code == 422


@pytest.mark.unit
def test_patch_persona_item_returns_updated() -> None:
    service = MagicMock()
    upgraded = _fake_item(source="user", text="改后", position=3)
    service.update_item.return_value = upgraded
    client = _client(service)

    resp = client.patch(
        f"/api/v0/persona/items/{uuid4()}",
        json={"text": "改后"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "user"
    assert body["text"] == "改后"


@pytest.mark.unit
def test_patch_persona_item_not_found() -> None:
    service = MagicMock()
    service.update_item.side_effect = LookupError("not found")
    client = _client(service)
    resp = client.patch(
        f"/api/v0/persona/items/{uuid4()}",
        json={"text": "x"},
    )
    assert resp.status_code == 404


@pytest.mark.unit
def test_delete_persona_item_204() -> None:
    service = MagicMock()
    client = _client(service)
    resp = client.delete(f"/api/v0/persona/items/{uuid4()}")
    assert resp.status_code == 204


@pytest.mark.unit
def test_delete_persona_item_not_found() -> None:
    service = MagicMock()
    service.delete_item.side_effect = LookupError("not found")
    client = _client(service)
    resp = client.delete(f"/api/v0/persona/items/{uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行 FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_persona_router.py -v -k "test_get_persona or test_post_persona or test_patch_persona or test_delete_persona"
```

Expected: 7 errors（persona_router 未实现）。

- [ ] **Step 3: 写 persona_router**

新建 `backend/app/router/persona_router.py`：

```python
"""persona_router — Plan Task 8 — REST endpoints for Tier 1 persona items.

spec § 7 (路径调整为 /api/v0/persona 对齐项目 router 前缀风格).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.memory.persona_service import PersonaService
from app.router._persona_schemas import (
    PersonaItemOut,
    PersonaListResponse,
    PersonaPatchRequest,
    PersonaPostRequest,
)

router = APIRouter(prefix="/api/v0/persona", tags=["persona-ui"])


# ----- 依赖注入 占位 -----
# 注: get_current_user_required 应复用项目既有的 dependency（grep `get_current_user`
#     找到真实模块；C.5 memory_router 也用这个 dep）。Subagent 实施时改 import 路径。


def _get_current_user_id() -> UUID:
    """占位 — 实施时改为 from app.auth.dependencies import get_current_user_required.

    test fixture 通过 app.dependency_overrides 替换此 dep。
    """
    raise NotImplementedError(
        "_get_current_user_id placeholder — replace with project auth dep"
    )


def get_persona_session_factory():  # type: ignore[no-untyped-def]
    """占位 — 实施时复用 app.memory.session_factory.get_persona_session_factory."""
    from app.memory.session_factory import get_persona_session_factory as _impl

    return _impl()


def get_persona_service(
    session_factory: Annotated[object, Depends(get_persona_session_factory)],
) -> PersonaService:
    return PersonaService(pg_session_factory=session_factory)  # type: ignore[arg-type]


def _to_out(item) -> PersonaItemOut:  # type: ignore[no-untyped-def]
    return PersonaItemOut(
        id=item.item_id,
        text=item.text,
        source=item.source,
        position=item.position,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=PersonaListResponse)
def list_persona(
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaListResponse:
    result = service.list_items(user_id=user_id)
    return PersonaListResponse(
        user_declared=[_to_out(i) for i in result["user_declared"]],
        agent_inferred=[_to_out(i) for i in result["agent_inferred"]],
    )


@router.post(
    "/items",
    response_model=PersonaItemOut,
    status_code=status.HTTP_201_CREATED,
)
def add_persona_item(
    body: PersonaPostRequest,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaItemOut:
    item = service.add_item(
        user_id=user_id, text=body.text, target_section=body.target_section
    )
    return _to_out(item)


@router.patch("/items/{item_id}", response_model=PersonaItemOut)
def update_persona_item(
    item_id: UUID,
    body: PersonaPatchRequest,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> PersonaItemOut:
    try:
        item = service.update_item(user_id=user_id, item_id=item_id, text=body.text)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona_item(
    item_id: UUID,
    user_id: Annotated[UUID, Depends(_get_current_user_id)],
    service: Annotated[PersonaService, Depends(get_persona_service)],
) -> Response:
    try:
        service.delete_item(user_id=user_id, item_id=item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: 修正 `_get_current_user_id` import**

```bash
grep -rn "get_current_user_required\|get_current_user\b" backend/app/ -l | head -5
```

按 grep 结果找到现有 auth dependency 真实位置（多半在 `app/auth/dependencies.py` 或 `app/auth/utils.py`），把 `persona_router.py` 中的 `_get_current_user_id` 函数体替换为：

```python
def _get_current_user_id(
    current_user: Annotated[object, Depends(<真实 dep>)],
) -> UUID:
    return current_user.id  # 或对应字段
```

若项目没有现成 dep，则保留占位 + test 用 `dependency_overrides`（test 已支持）。

- [ ] **Step 5: 运行 PASS**

```bash
uv run pytest backend/tests/unit/memory/test_persona_router.py -v
```

Expected: 14 passed（7 schema + 7 router）。

- [ ] **Step 6: app_main include_router + smoke**

打开 `backend/app/app_main.py`，在现有 `from app.router.memory_router import router as memory_router` 附近追加：

```python
from app.router.persona_router import router as persona_router  # noqa: E402
```

在 `app.include_router(memory_router)` 后追加：

```python
app.include_router(persona_router)
```

smoke:

```bash
uv run python -c "from app.app_main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'persona' in r])"
```

Expected: 打印 4 条路径，含 `/api/v0/persona` / `/api/v0/persona/items` / 2 个 `/api/v0/persona/items/{item_id}`。

- [ ] **Step 7: strict + commit**

```bash
uv run mypy backend/app/router/persona_router.py backend/app/app_main.py
uv run ruff check backend/app/router/persona_router.py backend/app/app_main.py backend/tests/unit/memory/test_persona_router.py
git add backend/app/router/persona_router.py backend/app/app_main.py backend/tests/unit/memory/test_persona_router.py
git commit -m "feat(persona-ui): persona_router 4 endpoints + include in app_main (Plan Task 8)"
```

---

### Task 9: L1 integration e2e — 真 PG

**Files:**
- Create: `backend/tests/integration/memory/test_persona_e2e.py`

- [ ] **Step 1: 写 e2e**

新建 `backend/tests/integration/memory/test_persona_e2e.py`：

```python
"""真 PG e2e — Plan Task 9.

复用 pg_memory_session_factory fixture (backend/tests/integration/memory/conftest.py).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


def _service(factory):  # type: ignore[no-untyped-def]
    return PersonaService(pg_session_factory=factory)


def test_full_lifecycle_user_add_agent_append_upgrade(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()

    # 1. user 加一条
    u1 = svc.add_item(user_id=user_id, text="保守稳健", target_section="user")
    assert u1.source == "user"

    # 2. agent 通过转译层加两条
    appended = svc.apply_agent_append(
        user_id=user_id, content="- 关注新能源\n- 高股息消费\n"
    )
    assert len(appended) == 2

    # 3. user 改 agent 区第一条 → 升级
    upgraded = svc.update_item(
        user_id=user_id, item_id=appended[0].item_id, text="关注新能源 + 储能"
    )
    assert upgraded.source == "user"

    # 4. list 验证
    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 2
    assert len(result["agent_inferred"]) == 1
    user_texts = {i.text for i in result["user_declared"]}
    assert user_texts == {"保守稳健", "关注新能源 + 储能"}

    # 5. render_to_markdown 跟状态一致
    md = svc.render_to_markdown(user_id=user_id)
    assert "## 你声明的" in md
    assert "保守稳健" in md
    assert "关注新能源 + 储能" in md
    assert "高股息消费" in md

    # 6. _sync_to_working_block 应已写回 working_blocks
    session = pg_memory_session_factory()
    try:
        block = (
            session.query(ChatMemoryWorkingBlock)
            .filter_by(user_id=user_id, block_name="persona")
            .first()
        )
        assert block is not None
        assert "保守稳健" in block.content
    finally:
        session.close()


def test_cross_user_isolation(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = _service(pg_memory_session_factory)
    user_a = uuid4()
    user_b = uuid4()

    svc.add_item(user_id=user_a, text="A 的条", target_section="user")
    svc.add_item(user_id=user_b, text="B 的条", target_section="user")

    a_result = svc.list_items(user_id=user_a)
    b_result = svc.list_items(user_id=user_b)

    assert {i.text for i in a_result["user_declared"]} == {"A 的条"}
    assert {i.text for i in b_result["user_declared"]} == {"B 的条"}


def test_apply_agent_replace_fallback_to_append(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()

    # 没有任何 agent item → replace 应 fallback 为 append
    items = svc.apply_agent_replace(
        user_id=user_id, old_content="不存在", new_content="新加的"
    )
    assert len(items) == 1
    assert items[0].source == "agent"
    assert items[0].text == "新加的"


def test_delete_item_removes_row(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = _service(pg_memory_session_factory)
    user_id = uuid4()
    item = svc.add_item(user_id=user_id, text="待删", target_section="user")

    svc.delete_item(user_id=user_id, item_id=item.item_id)

    result = svc.list_items(user_id=user_id)
    assert result["user_declared"] == []

    # 确认 DB 真的删了
    session = pg_memory_session_factory()
    try:
        remaining = (
            session.query(ChatMemoryPersonaItem)
            .filter_by(item_id=item.item_id)
            .first()
        )
        assert remaining is None
    finally:
        session.close()
```

- [ ] **Step 2: 运行 e2e（需 PG fixture）**

```bash
uv run pytest backend/tests/integration/memory/test_persona_e2e.py -v
```

Expected: 4 passed（如失败，先 grep 确认 `pg_memory_session_factory` fixture 仍在 `backend/tests/integration/memory/conftest.py:178-195`，且 schema migration 在 fixture setup 中跑了 `Base.metadata.create_all`）。

- [ ] **Step 3: commit**

```bash
git add backend/tests/integration/memory/test_persona_e2e.py
git commit -m "test(persona-ui): L1 e2e covering full lifecycle + cross-user isolation (Plan Task 9)"
```

---

### Task 10: L1 chat_planner 端到端 prompt 注入验证

**Files:**
- Create: `backend/tests/integration/memory/test_persona_chat_planner_e2e.py`

- [ ] **Step 1: 写 e2e**

新建 `backend/tests/integration/memory/test_persona_chat_planner_e2e.py`：

```python
"""持仓改动 → ChatPlanner 下轮 prompt 含新内容 — 验证端到端 wire."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agents.chat.prompt_loader import load_memory_tool_usage_prompt
from app.memory.hierarchical import HierarchicalMemory
from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_user_persona_change_visible_in_next_prompt(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    persona_svc = PersonaService(pg_session_factory=pg_memory_session_factory)
    user_id = uuid4()
    session_id = uuid4()

    # 用户加一条
    persona_svc.add_item(
        user_id=user_id, text="风险偏好：保守稳健", target_section="user"
    )

    # 构造 HierarchicalMemory（最小 DI）
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,  # type: ignore[arg-type]
        milvus_client=None,  # type: ignore[arg-type]
        embed_service=None,  # type: ignore[arg-type]
        llm_extractor=None,  # type: ignore[arg-type]
        llm_judge=None,  # type: ignore[arg-type]
    )

    rendered = await load_memory_tool_usage_prompt(
        memory=memory, user_id=user_id, session_id=session_id
    )

    assert "风险偏好：保守稳健" in rendered
    assert "## 你声明的" in rendered
```

- [ ] **Step 2: 运行 PASS**

```bash
uv run pytest backend/tests/integration/memory/test_persona_chat_planner_e2e.py -v
```

Expected: 1 passed。若 `load_memory_tool_usage_prompt` 签名不一致，按 explore 报告 prompt_loader.py:40-61 修正参数。

- [ ] **Step 3: commit**

```bash
git add backend/tests/integration/memory/test_persona_chat_planner_e2e.py
git commit -m "test(persona-ui): user persona change visible in next ChatPlanner prompt (Plan Task 10)"
```

---

## Phase 3 — Frontend client + 组件 + vitest（Tasks 11–16）

### Task 11: personaApi.ts client

**Files:**
- Create: `frontend/src/api/personaApi.ts`
- Create: `frontend/src/api/__tests__/personaApi.test.ts`

- [ ] **Step 1: 写测试**

新建 `frontend/src/api/__tests__/personaApi.test.ts`：

```typescript
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import {
  addPersonaItem,
  deletePersonaItem,
  fetchPersona,
  updatePersonaItem,
} from '@/api/personaApi'

const BASE = '/api/v0/persona'

const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterAll(() => server.close())
beforeEach(() => server.resetHandlers())

describe('personaApi', () => {
  it('GET /api/v0/persona returns parsed PersonaListResponse', async () => {
    server.use(
      http.get(BASE, () =>
        HttpResponse.json({
          user_declared: [
            {
              id: '00000000-0000-0000-0000-000000000001',
              text: '保守稳健',
              source: 'user',
              position: 0,
              created_at: '2026-05-17T00:00:00+00:00',
              updated_at: '2026-05-17T00:00:00+00:00',
            },
          ],
          agent_inferred: [],
        })
      )
    )

    const data = await fetchPersona()
    expect(data.user_declared).toHaveLength(1)
    expect(data.user_declared[0].text).toBe('保守稳健')
  })

  it('POST /api/v0/persona/items returns created item', async () => {
    server.use(
      http.post(`${BASE}/items`, async ({ request }) => {
        const body = (await request.json()) as { text: string; target_section: string }
        return HttpResponse.json(
          {
            id: '00000000-0000-0000-0000-000000000002',
            text: body.text,
            source: body.target_section,
            position: 1,
            created_at: '2026-05-17T00:00:00+00:00',
            updated_at: '2026-05-17T00:00:00+00:00',
          },
          { status: 201 }
        )
      })
    )

    const item = await addPersonaItem({ text: '新条', target_section: 'user' })
    expect(item.text).toBe('新条')
    expect(item.source).toBe('user')
  })

  it('PATCH /api/v0/persona/items/{id} returns updated item with upgraded source', async () => {
    server.use(
      http.patch(`${BASE}/items/:id`, () =>
        HttpResponse.json({
          id: '00000000-0000-0000-0000-000000000003',
          text: '改后',
          source: 'user',
          position: 3,
          created_at: '2026-05-17T00:00:00+00:00',
          updated_at: '2026-05-17T00:00:00+00:00',
        })
      )
    )

    const item = await updatePersonaItem('00000000-0000-0000-0000-000000000003', '改后')
    expect(item.source).toBe('user')
    expect(item.text).toBe('改后')
  })

  it('DELETE /api/v0/persona/items/{id} resolves on 204', async () => {
    server.use(http.delete(`${BASE}/items/:id`, () => new HttpResponse(null, { status: 204 })))
    await expect(
      deletePersonaItem('00000000-0000-0000-0000-000000000004')
    ).resolves.toBeUndefined()
  })

  it('GET error throws with status', async () => {
    server.use(http.get(BASE, () => new HttpResponse('boom', { status: 500 })))
    await expect(fetchPersona()).rejects.toThrow(/500/)
  })
})
```

- [ ] **Step 2: 运行 FAIL**

```bash
cd frontend && npx vitest run src/api/__tests__/personaApi.test.ts
```

Expected: 5 fail（personaApi module 未实现）。

- [ ] **Step 3: 写 client**

新建 `frontend/src/api/personaApi.ts`：

```typescript
const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''
const BASE = '/api/v0/persona'

const apiUrl = (path: string) => `${API_BASE}${path}`

export type PersonaSource = 'user' | 'agent'

export interface PersonaItem {
  id: string
  text: string
  source: PersonaSource
  position: number
  created_at: string
  updated_at: string
}

export interface PersonaListResponse {
  user_declared: PersonaItem[]
  agent_inferred: PersonaItem[]
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

export async function fetchPersona(): Promise<PersonaListResponse> {
  return fetchJson<PersonaListResponse>(BASE)
}

export async function addPersonaItem(params: {
  text: string
  target_section: PersonaSource
}): Promise<PersonaItem> {
  return fetchJson<PersonaItem>(`${BASE}/items`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function updatePersonaItem(
  itemId: string,
  text: string
): Promise<PersonaItem> {
  return fetchJson<PersonaItem>(`${BASE}/items/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify({ text }),
  })
}

export async function deletePersonaItem(itemId: string): Promise<void> {
  await fetchJson<void>(`${BASE}/items/${itemId}`, { method: 'DELETE' })
}
```

- [ ] **Step 4: 运行 PASS + commit**

```bash
cd frontend && npx vitest run src/api/__tests__/personaApi.test.ts
```

Expected: 5 passed。

```bash
git add frontend/src/api/personaApi.ts frontend/src/api/__tests__/personaApi.test.ts
git commit -m "feat(persona-ui): personaApi typed client + msw tests (Plan Task 11)"
```

---

### Task 12: MemoryPersona 组件 — 渲染 + 空状态

**Files:**
- Create: `frontend/src/components/memory/MemoryPersona.tsx`
- Create: `frontend/src/components/memory/MemoryPersona.styles.ts`
- Create: `frontend/src/components/memory/__tests__/MemoryPersona.test.tsx`（最小渲染测试）

- [ ] **Step 1: 写最小渲染测试**

新建 `frontend/src/components/memory/__tests__/MemoryPersona.test.tsx`：

```typescript
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/personaApi'
import MemoryPersona from '@/components/memory/MemoryPersona'

vi.mock('@/api/personaApi')

const mkItem = (overrides: Partial<api.PersonaItem> = {}): api.PersonaItem => ({
  id: `id-${Math.random()}`,
  text: '默认',
  source: 'user',
  position: 0,
  created_at: '2026-05-17T00:00:00+00:00',
  updated_at: '2026-05-17T00:00:00+00:00',
  ...overrides,
})

describe('<MemoryPersona>', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('renders Spin while loading', () => {
    vi.mocked(api.fetchPersona).mockReturnValue(new Promise(() => {}))
    render(<MemoryPersona />)
    expect(document.querySelector('.ant-spin')).not.toBeNull()
  })

  it('renders two sections with items', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [mkItem({ text: '保守稳健', source: 'user' })],
      agent_inferred: [mkItem({ text: '关注新能源', source: 'agent' })],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText('保守稳健')).toBeTruthy()
      expect(screen.getByText('关注新能源')).toBeTruthy()
    })
    expect(screen.getByText('你声明的')).toBeTruthy()
    expect(screen.getByText('agent 观察到的')).toBeTruthy()
  })

  it('shows empty state when both sections empty', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText(/还没有任何记忆/)).toBeTruthy()
    })
  })

  it('shows section-level placeholder when one section empty', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValue({
      user_declared: [mkItem({ text: '保守稳健' })],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByText('保守稳健')).toBeTruthy()
      expect(screen.getByText('（暂无）')).toBeTruthy()
    })
  })

  it('shows error state when fetch fails', async () => {
    vi.mocked(api.fetchPersona).mockRejectedValue(new Error('boom'))
    render(<MemoryPersona />)
    await waitFor(() => {
      expect(screen.getByText(/加载失败/)).toBeTruthy()
    })
  })
})
```

- [ ] **Step 2: 运行 FAIL**

```bash
cd frontend && npx vitest run src/components/memory/__tests__/MemoryPersona.test.tsx
```

Expected: 5 fail（组件未实现）。

- [ ] **Step 3: 写 styles 文件**

新建 `frontend/src/components/memory/MemoryPersona.styles.ts`：

```typescript
import type { CSSProperties } from 'react'

export const sectionWrapper: CSSProperties = {
  marginBottom: 32,
}

export const sectionHeader: CSSProperties = {
  fontWeight: 600,
  fontSize: 15,
  marginBottom: 12,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

export const itemRow: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'flex-start',
  border: '1px solid var(--persona-border, #e0e0e0)',
  borderRadius: 6,
  padding: '10px 12px',
  marginBottom: 8,
  background: 'var(--persona-bg, #fff)',
  transition: 'background 200ms ease',
}

export const itemRowHighlighted: CSSProperties = {
  ...itemRow,
  background: 'rgba(245, 197, 24, 0.15)',
}

export const actions: CSSProperties = {
  display: 'flex',
  gap: 6,
  flexShrink: 0,
  marginLeft: 12,
}

export const emptyPlaceholder: CSSProperties = {
  color: '#999',
  fontStyle: 'italic',
  fontSize: 13,
  padding: '8px 12px',
}

export const fullEmpty: CSSProperties = {
  textAlign: 'center',
  padding: '40px 20px',
  color: '#666',
}
```

- [ ] **Step 4: 写组件（仅渲染 / 加载 / 空 / 错误，不含 edit/add/delete）**

新建 `frontend/src/components/memory/MemoryPersona.tsx`：

```typescript
import { Alert, Button, Spin } from 'antd'
import { useEffect, useState } from 'react'

import { fetchPersona, type PersonaItem, type PersonaListResponse } from '@/api/personaApi'

import * as S from './MemoryPersona.styles'

export interface MemoryPersonaProps {
  /** test 注入用；正式渲染时不传 */
  initialData?: PersonaListResponse
}

export default function MemoryPersona({ initialData }: MemoryPersonaProps = {}) {
  const [data, setData] = useState<PersonaListResponse | null>(initialData ?? null)
  const [loading, setLoading] = useState(!initialData)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialData) return
    let cancelled = false
    setLoading(true)
    fetchPersona()
      .then((resp) => {
        if (!cancelled) {
          setData(resp)
          setError(null)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || '加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [initialData])

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        message={`加载失败: ${error}`}
        action={
          <Button size="small" onClick={() => window.location.reload()}>
            重试
          </Button>
        }
      />
    )
  }

  if (!data) return null

  const totalCount = data.user_declared.length + data.agent_inferred.length

  if (totalCount === 0) {
    return (
      <div style={S.fullEmpty}>
        <p>还没有任何记忆 — 跟 agent 多聊几句它会自己开始记，或者点 + 自己加</p>
      </div>
    )
  }

  return (
    <div>
      <Section
        title="你声明的"
        icon="👤"
        items={data.user_declared}
        emptyPlaceholderText="（暂无）"
        canAdd
      />
      <Section
        title="agent 观察到的"
        icon="🤖"
        items={data.agent_inferred}
        emptyPlaceholderText="（暂无）"
      />
    </div>
  )
}

interface SectionProps {
  title: string
  icon: string
  items: PersonaItem[]
  emptyPlaceholderText: string
  canAdd?: boolean
}

function Section({ title, icon, items, emptyPlaceholderText }: SectionProps) {
  return (
    <div style={S.sectionWrapper}>
      <div style={S.sectionHeader}>
        <span>{icon}</span>
        <span>{title}</span>
      </div>
      {items.length === 0 ? (
        <div style={S.emptyPlaceholder}>{emptyPlaceholderText}</div>
      ) : (
        items.map((it) => (
          <div key={it.id} style={S.itemRow} data-testid={`persona-item-${it.id}`}>
            <div style={{ flex: 1, lineHeight: 1.5 }}>{it.text}</div>
          </div>
        ))
      )}
    </div>
  )
}
```

- [ ] **Step 5: 运行 PASS + commit**

```bash
cd frontend && npx vitest run src/components/memory/__tests__/MemoryPersona.test.tsx
```

Expected: 5 passed。

```bash
git add frontend/src/components/memory/MemoryPersona.tsx frontend/src/components/memory/MemoryPersona.styles.ts frontend/src/components/memory/__tests__/MemoryPersona.test.tsx
git commit -m "feat(persona-ui): MemoryPersona render + loading + empty + error (Plan Task 12)"
```

---

### Task 13: MemoryPersona — 编辑 / 删除 / 添加

**Files:**
- Modify: `frontend/src/components/memory/MemoryPersona.tsx`
- Modify: `frontend/src/components/memory/__tests__/MemoryPersona.test.tsx`

- [ ] **Step 1: 追加交互测试**

打开 `MemoryPersona.test.tsx` 末尾追加：

```typescript
import { fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

describe('<MemoryPersona> interactions', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('add item via modal calls addPersonaItem with target_section=user', async () => {
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [],
      agent_inferred: [],
    })
    vi.mocked(api.addPersonaItem).mockResolvedValue(
      mkItem({ text: '新条', source: 'user' })
    )
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [mkItem({ text: '新条', source: 'user' })],
      agent_inferred: [],
    })

    render(<MemoryPersona />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /添加我的第一条/ })).toBeTruthy()
    })

    await userEvent.click(screen.getByRole('button', { name: /添加我的第一条/ }))
    const textarea = await screen.findByPlaceholderText(/输入一条画像/)
    await userEvent.type(textarea, '新条')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      expect(api.addPersonaItem).toHaveBeenCalledWith({
        text: '新条',
        target_section: 'user',
      })
    })
  })

  it('inline edit calls updatePersonaItem', async () => {
    const item = mkItem({ text: '原文', source: 'user', id: 'fixed-id' })
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [item],
      agent_inferred: [],
    })
    vi.mocked(api.updatePersonaItem).mockResolvedValue({ ...item, text: '改后' })

    render(<MemoryPersona />)

    await waitFor(() => expect(screen.getByText('原文')).toBeTruthy())
    fireEvent.click(screen.getByTestId('persona-edit-fixed-id'))
    const textarea = await screen.findByDisplayValue('原文')
    fireEvent.change(textarea, { target: { value: '改后' } })
    fireEvent.click(screen.getByTestId('persona-save-fixed-id'))

    await waitFor(() => {
      expect(api.updatePersonaItem).toHaveBeenCalledWith('fixed-id', '改后')
    })
  })

  it('delete confirmation calls deletePersonaItem', async () => {
    const item = mkItem({ text: '待删', source: 'user', id: 'del-id' })
    vi.mocked(api.fetchPersona).mockResolvedValueOnce({
      user_declared: [item],
      agent_inferred: [],
    })
    vi.mocked(api.deletePersonaItem).mockResolvedValue()

    render(<MemoryPersona />)

    await waitFor(() => expect(screen.getByText('待删')).toBeTruthy())
    fireEvent.click(screen.getByTestId('persona-delete-del-id'))
    fireEvent.click(await screen.findByRole('button', { name: /^确\s*认$/ }))

    await waitFor(() => {
      expect(api.deletePersonaItem).toHaveBeenCalledWith('del-id')
    })
  })
})
```

- [ ] **Step 2: 运行 FAIL**

```bash
cd frontend && npx vitest run src/components/memory/__tests__/MemoryPersona.test.tsx
```

Expected: 3 new fail。

- [ ] **Step 3: 改 MemoryPersona 组件加交互**

打开 `frontend/src/components/memory/MemoryPersona.tsx`，**整体替换为以下内容**（基于 Task 12 加交互）：

```typescript
import { Alert, Button, Input, message, Modal, Popconfirm, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'

import {
  addPersonaItem,
  deletePersonaItem,
  fetchPersona,
  updatePersonaItem,
  type PersonaItem,
  type PersonaListResponse,
} from '@/api/personaApi'

import * as S from './MemoryPersona.styles'

export interface MemoryPersonaProps {
  initialData?: PersonaListResponse
}

export default function MemoryPersona({ initialData }: MemoryPersonaProps = {}) {
  const [data, setData] = useState<PersonaListResponse | null>(initialData ?? null)
  const [loading, setLoading] = useState(!initialData)
  const [error, setError] = useState<string | null>(null)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addText, setAddText] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [recentlyUpgradedId, setRecentlyUpgradedId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await fetchPersona()
      setData(resp)
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!initialData) {
      void refresh()
    }
  }, [initialData, refresh])

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        message={`加载失败: ${error}`}
        action={
          <Button size="small" onClick={() => void refresh()}>
            重试
          </Button>
        }
      />
    )
  }

  if (!data) return null

  const total = data.user_declared.length + data.agent_inferred.length

  const handleAdd = async () => {
    const text = addText.trim()
    if (!text) return
    setAdding(true)
    try {
      await addPersonaItem({ text, target_section: 'user' })
      setAddText('')
      setAddModalOpen(false)
      await refresh()
      message.success('已添加')
    } catch (err) {
      message.error(`添加失败: ${(err as Error).message}`)
    } finally {
      setAdding(false)
    }
  }

  const handleSaveEdit = async (item: PersonaItem) => {
    const text = editText.trim()
    if (!text) return
    try {
      const updated = await updatePersonaItem(item.id, text)
      setEditingId(null)
      if (item.source === 'agent' && updated.source === 'user') {
        setRecentlyUpgradedId(updated.id)
        message.success('已迁到你的声明区')
        setTimeout(() => setRecentlyUpgradedId(null), 1500)
      }
      await refresh()
    } catch (err) {
      message.error(`保存失败: ${(err as Error).message}`)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deletePersonaItem(id)
      await refresh()
      message.success('已删除')
    } catch (err) {
      message.error(`删除失败: ${(err as Error).message}`)
    }
  }

  if (total === 0) {
    return (
      <>
        <div style={S.fullEmpty}>
          <p>还没有任何记忆 — 跟 agent 多聊几句它会自己开始记，或者点 + 自己加</p>
          <Button type="primary" onClick={() => setAddModalOpen(true)}>
            添加我的第一条
          </Button>
        </div>
        {renderAddModal({
          open: addModalOpen,
          text: addText,
          adding,
          onChange: setAddText,
          onCancel: () => {
            setAddModalOpen(false)
            setAddText('')
          },
          onOk: handleAdd,
        })}
      </>
    )
  }

  return (
    <div>
      <Section
        title="你声明的"
        icon="👤"
        items={data.user_declared}
        canAdd
        onAdd={() => setAddModalOpen(true)}
        editingId={editingId}
        editText={editText}
        setEditingId={setEditingId}
        setEditText={setEditText}
        onSaveEdit={handleSaveEdit}
        onDelete={handleDelete}
        recentlyUpgradedId={recentlyUpgradedId}
      />
      <Section
        title="agent 观察到的"
        icon="🤖"
        items={data.agent_inferred}
        editingId={editingId}
        editText={editText}
        setEditingId={setEditingId}
        setEditText={setEditText}
        onSaveEdit={handleSaveEdit}
        onDelete={handleDelete}
        recentlyUpgradedId={recentlyUpgradedId}
      />
      {renderAddModal({
        open: addModalOpen,
        text: addText,
        adding,
        onChange: setAddText,
        onCancel: () => {
          setAddModalOpen(false)
          setAddText('')
        },
        onOk: handleAdd,
      })}
    </div>
  )
}

interface SectionProps {
  title: string
  icon: string
  items: PersonaItem[]
  canAdd?: boolean
  onAdd?: () => void
  editingId: string | null
  editText: string
  setEditingId: (id: string | null) => void
  setEditText: (s: string) => void
  onSaveEdit: (item: PersonaItem) => Promise<void>
  onDelete: (id: string) => Promise<void>
  recentlyUpgradedId: string | null
}

function Section({
  title,
  icon,
  items,
  canAdd,
  onAdd,
  editingId,
  editText,
  setEditingId,
  setEditText,
  onSaveEdit,
  onDelete,
  recentlyUpgradedId,
}: SectionProps) {
  return (
    <div style={S.sectionWrapper}>
      <div style={S.sectionHeader}>
        <span>{icon}</span>
        <span>{title}</span>
      </div>
      {items.length === 0 ? (
        <div style={S.emptyPlaceholder}>（暂无）</div>
      ) : (
        items.map((it) => {
          const rowStyle = recentlyUpgradedId === it.id ? S.itemRowHighlighted : S.itemRow
          if (editingId === it.id) {
            return (
              <div key={it.id} style={rowStyle}>
                <Input.TextArea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  style={{ flex: 1 }}
                />
                <div style={S.actions}>
                  <Button
                    size="small"
                    type="primary"
                    data-testid={`persona-save-${it.id}`}
                    onClick={() => void onSaveEdit(it)}
                  >
                    ✓
                  </Button>
                  <Button size="small" onClick={() => setEditingId(null)}>
                    ✗
                  </Button>
                </div>
              </div>
            )
          }
          return (
            <div key={it.id} style={rowStyle} data-testid={`persona-item-${it.id}`}>
              <div style={{ flex: 1, lineHeight: 1.5 }}>{it.text}</div>
              <div style={S.actions}>
                <Button
                  size="small"
                  type="text"
                  data-testid={`persona-edit-${it.id}`}
                  onClick={() => {
                    setEditingId(it.id)
                    setEditText(it.text)
                  }}
                >
                  ✏️
                </Button>
                <Popconfirm
                  title="确认删除？"
                  okText="确认"
                  cancelText="取消"
                  onConfirm={() => void onDelete(it.id)}
                >
                  <Button
                    size="small"
                    type="text"
                    danger
                    data-testid={`persona-delete-${it.id}`}
                  >
                    🗑️
                  </Button>
                </Popconfirm>
              </div>
            </div>
          )
        })
      )}
      {canAdd && (
        <Button block type="dashed" onClick={onAdd}>
          + 手动添加一条
        </Button>
      )}
    </div>
  )
}

interface AddModalArgs {
  open: boolean
  text: string
  adding: boolean
  onChange: (s: string) => void
  onCancel: () => void
  onOk: () => void
}

function renderAddModal({ open, text, adding, onChange, onCancel, onOk }: AddModalArgs) {
  return (
    <Modal
      open={open}
      title="添加一条画像"
      onCancel={onCancel}
      onOk={onOk}
      confirmLoading={adding}
      okText="保存"
      cancelText="取消"
    >
      <Input.TextArea
        value={text}
        onChange={(e) => onChange(e.target.value)}
        placeholder="输入一条画像，例如：风险偏好稳健"
        autoSize={{ minRows: 2, maxRows: 6 }}
        maxLength={500}
      />
    </Modal>
  )
}
```

- [ ] **Step 4: 运行 PASS**

```bash
cd frontend && npx vitest run src/components/memory/__tests__/MemoryPersona.test.tsx
```

Expected: 8 passed。

- [ ] **Step 5: 类型检查 + commit**

```bash
cd frontend && npx tsc --noEmit -p tsconfig.json
git add frontend/src/components/memory/MemoryPersona.tsx frontend/src/components/memory/__tests__/MemoryPersona.test.tsx
git commit -m "feat(persona-ui): MemoryPersona add/edit/delete + upgrade highlight (Plan Task 13)"
```

---

### Task 14: chat 顶角快捷入口

**Files:**
- Modify: `frontend/src/pages/chat/index.tsx`（或实际 chat landing 路径 — 先 grep 找）

- [ ] **Step 1: 定位 chat landing**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
grep -rn "ChatPane\|chat landing" frontend/src/pages -l | head -5
grep -rn "ChatRoute\|ChatLanding" frontend/src/pages -l | head -5
```

按 grep 结果定位实际 chat landing 组件路径（可能是 `frontend/src/pages/chat/index.tsx` 或 `frontend/src/routes/chat.tsx`）。

- [ ] **Step 2: 在 chat landing 顶部加链接**

按定位到的文件，在顶部 toolbar 区域追加：

```tsx
import { Link } from 'react-router-dom'  // 或项目实际 router
import { Button } from 'antd'

// 在 toolbar / header 末尾追加：
<Link to="/memory#persona">
  <Button type="text" size="small">📋 我的画像</Button>
</Link>
```

具体放在哪个 toolbar 由组件结构决定 — 目标：用户在 chat 中能 1-click 跳到 `/memory#persona`。

- [ ] **Step 3: smoke**

```bash
cd frontend && npm run dev
```

启动后浏览器打开 chat landing 页，验证顶角有 "📋 我的画像" 按钮，点击跳 `/memory#persona`。

- [ ] **Step 4: commit**

```bash
git add frontend/src/pages/chat/index.tsx  # 或实际路径
git commit -m "feat(persona-ui): chat landing top-right quick link to /memory#persona (Plan Task 14)"
```

---

### Task 15: /memory 页加 'persona' tab 作默认

**Files:**
- Modify: `frontend/src/pages/memory/index.tsx`

- [ ] **Step 1: 改 page**

打开 `frontend/src/pages/memory/index.tsx`，做两件事：

1. 在 import 段加：
   ```typescript
   import MemoryPersona from '@/components/memory/MemoryPersona'
   ```
2. 改 `activeKey` 初始化和 tabs 列表（行 22+）：

```typescript
const [activeKey, setActiveKey] = useState<string>(() => {
  if (typeof window !== 'undefined' && window.location.hash === '#persona') {
    return 'persona'
  }
  return 'persona'  // 默认 'persona'
})

const tabs: TabsProps['items'] = [
  {
    key: 'persona',
    label: <span data-testid="memory-tab-persona">画像</span>,
    children: <MemoryPersona />,
  },
  {
    key: 'graph',
    label: <span data-testid="memory-tab-graph">图谱</span>,
    children: <MemoryGraph />,
  },
  {
    key: 'timeline',
    label: <span data-testid="memory-tab-timeline">时间线</span>,
    children: <MemoryTimeline />,
  },
  {
    key: 'audit',
    label: <span data-testid="memory-tab-audit">历史</span>,
    children: <MemoryAuditLog />,
  },
]
```

（如原 `<MemoryGraph />` 等组件有 props，保留原 props 不变。）

- [ ] **Step 2: smoke**

```bash
cd frontend && npm run dev
```

浏览器打开 `/memory` 验证默认进入"画像" tab；手动改 hash 到 `/memory#persona` 验证也进画像。

- [ ] **Step 3: commit**

```bash
git add frontend/src/pages/memory/index.tsx
git commit -m "feat(persona-ui): /memory page persona tab as default (Plan Task 15)"
```

---

### Task 16: Playwright e2e

**Files:**
- Create: `frontend/tests/e2e/memory-persona.spec.ts`

- [ ] **Step 1: 写 e2e**

新建 `frontend/tests/e2e/memory-persona.spec.ts`：

```typescript
import { expect, test, type BrowserContext, type Page } from '@playwright/test'

const API_HOST = process.env.PLAYWRIGHT_API_HOST ?? 'http://localhost:5173'

const FAKE_USER = { id: 'u-1', email: 'test@example.com', display_name: 'test' }

async function seedAuth(context: BrowserContext) {
  await context.addInitScript(([authKey, payload]: [string, string]) => {
    window.localStorage.setItem(authKey, payload)
  }, ['auth', JSON.stringify({ token: 'tk-test', user: FAKE_USER, refresh_token: 'rt' })])
}

async function suppressOnboarding(context: BrowserContext) {
  await context.addInitScript(() => {
    window.localStorage.setItem('memory_onboarding_seen_v1', '1')
  })
}

async function stubPersonaEndpoints(page: Page) {
  let userItems = [
    {
      id: 'u-item-1',
      text: '已声明的偏好',
      source: 'user' as const,
      position: 0,
      created_at: '2026-05-17T00:00:00+00:00',
      updated_at: '2026-05-17T00:00:00+00:00',
    },
  ]
  let agentItems = [
    {
      id: 'a-item-1',
      text: '关注新能源',
      source: 'agent' as const,
      position: 0,
      created_at: '2026-05-17T00:00:00+00:00',
      updated_at: '2026-05-17T00:00:00+00:00',
    },
  ]

  await page.route(`${API_HOST}/api/v0/persona`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user_declared: userItems, agent_inferred: agentItems }),
    })
  })
  await page.route(`${API_HOST}/api/v0/persona/items`, async (route) => {
    if (route.request().method() === 'POST') {
      const body = JSON.parse(route.request().postData() ?? '{}')
      const item = {
        id: `u-${Date.now()}`,
        text: body.text,
        source: body.target_section,
        position: userItems.length,
        created_at: '2026-05-17T00:00:00+00:00',
        updated_at: '2026-05-17T00:00:00+00:00',
      }
      userItems = [...userItems, item]
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(item),
      })
      return
    }
    await route.fulfill({ status: 404 })
  })
  await page.route(`${API_HOST}/api/v0/persona/items/*`, async (route) => {
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').pop()!
    if (route.request().method() === 'PATCH') {
      const body = JSON.parse(route.request().postData() ?? '{}')
      // 模拟 agent → user 升级
      const wasAgent = id === 'a-item-1'
      const updated = {
        id,
        text: body.text,
        source: 'user' as const,
        position: userItems.length,
        created_at: '2026-05-17T00:00:00+00:00',
        updated_at: '2026-05-17T00:00:00+00:00',
      }
      if (wasAgent) {
        agentItems = agentItems.filter((i) => i.id !== id)
        userItems = [...userItems, updated]
      } else {
        userItems = userItems.map((i) => (i.id === id ? { ...i, text: body.text } : i))
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(updated),
      })
      return
    }
    if (route.request().method() === 'DELETE') {
      userItems = userItems.filter((i) => i.id !== id)
      agentItems = agentItems.filter((i) => i.id !== id)
      await route.fulfill({ status: 204 })
      return
    }
    await route.fulfill({ status: 404 })
  })
}

test('memory persona tab is default and renders items', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')

  await expect(page.getByText('你声明的')).toBeVisible()
  await expect(page.getByText('agent 观察到的')).toBeVisible()
  await expect(page.getByText('已声明的偏好')).toBeVisible()
  await expect(page.getByText('关注新能源')).toBeVisible()
})

test('add a new persona item appears in user section', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByRole('button', { name: /手动添加一条/ }).click()
  await page.getByPlaceholder(/输入一条画像/).fill('新加的偏好')
  await page.getByRole('button', { name: '保存' }).click()

  await expect(page.getByText('新加的偏好')).toBeVisible()
})

test('edit agent item upgrades to user section', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByTestId('persona-edit-a-item-1').click()
  await page.getByDisplayValue('关注新能源').fill('关注新能源 + 储能')
  await page.getByTestId('persona-save-a-item-1').click()

  await expect(page.getByText('关注新能源 + 储能')).toBeVisible()
})

test('delete an item removes it', async ({ page, context }) => {
  await seedAuth(context)
  await suppressOnboarding(context)
  await stubPersonaEndpoints(page)

  await page.goto('/memory')
  await page.getByTestId('persona-delete-u-item-1').click()
  await page.getByRole('button', { name: /^确\s*认$/ }).click()

  await expect(page.getByText('已声明的偏好')).not.toBeVisible()
})
```

- [ ] **Step 2: 跑 e2e**

```bash
cd frontend && npx playwright test tests/e2e/memory-persona.spec.ts
```

Expected: 4 passed。

- [ ] **Step 3: commit**

```bash
git add frontend/tests/e2e/memory-persona.spec.ts
git commit -m "test(persona-ui): Playwright e2e covering tab default + add/edit/delete (Plan Task 16)"
```

---

## Phase 4 — agent self-managed 转译接通 + 双轨保护 e2e（Tasks 17–19）

### Task 17: HierarchicalMemory.core_memory_append/replace 改为调 PersonaService（仅 persona block）

**Files:**
- Modify: `backend/app/memory/hierarchical.py`
- Modify: `backend/tests/unit/memory/test_hierarchical_di_hooks.py`（若已有 hierarchical 测试，追加用例；否则新建小测）

- [ ] **Step 1: 写测试 — 验证 core_memory_append 触发 PersonaService.apply_agent_append（仅 persona block）**

新建 `backend/tests/unit/memory/test_hierarchical_persona_dispatch.py`：

```python
"""Plan Task 17 — HierarchicalMemory core_memory_* persona block 转译."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.memory.hierarchical import HierarchicalMemory


def _mk_memory(**overrides):  # type: ignore[no-untyped-def]
    defaults = {
        "pg_session_factory": MagicMock(),
        "age_executor": MagicMock(),
        "milvus_client": MagicMock(),
        "embed_service": MagicMock(),
        "llm_extractor": MagicMock(),
        "llm_judge": MagicMock(),
    }
    defaults.update(overrides)
    return HierarchicalMemory(**defaults)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_append_persona_routes_to_persona_service() -> None:
    mem = _mk_memory()
    mock_persona_service = MagicMock()
    mock_persona_service.apply_agent_append.return_value = []
    mem._persona_service = mock_persona_service  # type: ignore[attr-defined]

    await mem.core_memory_append(user_id=uuid4(), block_name="persona", content="X")

    mock_persona_service.apply_agent_append.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_append_scratchpad_keeps_legacy_path() -> None:
    """scratchpad block 走原 ChatMemoryWorkingBlock 路径，不调 PersonaService."""
    mem = _mk_memory()
    mock_persona_service = MagicMock()
    mem._persona_service = mock_persona_service  # type: ignore[attr-defined]

    # 不验证完整 PG 路径，只验证 PersonaService 没被调
    try:
        await mem.core_memory_append(
            user_id=uuid4(), block_name="scratchpad", content="X"
        )
    except Exception:
        # 真 PG 路径可能因 mock 不全报错，我们只 care PersonaService 没被调
        pass

    mock_persona_service.apply_agent_append.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_core_memory_replace_persona_routes_to_persona_service() -> None:
    mem = _mk_memory()
    mock_persona_service = MagicMock()
    mock_persona_service.apply_agent_replace.return_value = []
    mem._persona_service = mock_persona_service  # type: ignore[attr-defined]

    await mem.core_memory_replace(
        user_id=uuid4(), block_name="persona", old_content="A", new_content="B"
    )

    mock_persona_service.apply_agent_replace.assert_called_once_with(
        user_id=mock_persona_service.apply_agent_replace.call_args.kwargs["user_id"],
        old_content="A",
        new_content="B",
    )
```

- [ ] **Step 2: 运行 FAIL**

```bash
uv run pytest backend/tests/unit/memory/test_hierarchical_persona_dispatch.py -v
```

Expected: 3 fail（HierarchicalMemory 还没分支）。

- [ ] **Step 3: 改 HierarchicalMemory**

打开 `backend/app/memory/hierarchical.py`，在 `__init__` 末尾追加 PersonaService 懒构造：

```python
        self._persona_service: PersonaService | None = None
```

并在文件顶部 import：

```python
from app.memory.persona_service import PersonaService
```

在 `__init__` 末尾追加：

```python
        self._persona_service = PersonaService(pg_session_factory=pg_session_factory)
```

修改 `core_memory_append` 方法（行 98 起），在方法开头加分支：

```python
    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> ChatMemoryWorkingBlock | None:
        if block_name == "persona" and self._persona_service is not None:
            self._persona_service.apply_agent_append(user_id=user_id, content=content)
            # 不再返回原 ChatMemoryWorkingBlock — caller (mcp tool) 已不关心 return；
            # 若 caller 关心，可改为返回最新 working_block (Task 5 已 _sync 写回)
            return None
        # 原 legacy path（保留给 scratchpad）
        ...  # 原方法体不动
```

修改 `core_memory_replace` 同样加分支。

注意：原方法返回 `ChatMemoryWorkingBlock`。新 persona 路径如不返回 block，caller（MCP tool）需要 tolerate `None`。grep 调用方：

```bash
grep -rn "core_memory_append\|core_memory_replace" backend/app/ --include="*.py" | grep -v "_test"
```

如调用方使用了 return value，改返回类型为 `ChatMemoryWorkingBlock | None`，调用方加 None 兜底。

- [ ] **Step 4: 运行 PASS + grep 验证调用方**

```bash
uv run pytest backend/tests/unit/memory/test_hierarchical_persona_dispatch.py -v
grep -rn "core_memory_append\|core_memory_replace" backend/app/ --include="*.py" | grep -v test
```

确认调用方 (mcp_server/tools/memory 等) 对 None return 安全。

- [ ] **Step 5: 跑既有 hierarchical 测试不能 regress**

```bash
uv run pytest backend/tests/unit/memory/ backend/tests/integration/memory/ -v
```

Expected: 全 PASS (含 Plan 之前的 + Plan 新加的)，0 regress。

- [ ] **Step 6: strict + commit**

```bash
uv run mypy backend/app/memory/hierarchical.py
uv run ruff check backend/app/memory/hierarchical.py backend/tests/unit/memory/test_hierarchical_persona_dispatch.py
git add backend/app/memory/hierarchical.py backend/tests/unit/memory/test_hierarchical_persona_dispatch.py
git commit -m "feat(persona-ui): HierarchicalMemory persona block routes to PersonaService (Plan Task 17)"
```

---

### Task 18: memory_tool_usage.md 加 "❌ 不要修改 [你声明的] 区" 段 + L0 文案断言

**Files:**
- Modify: `backend/app/agents/chat/prompts/memory_tool_usage.md`
- Modify: `backend/tests/unit/agents/chat/test_system_prompt_template.py`

- [ ] **Step 1: 写文案断言测试**

打开 `backend/tests/unit/agents/chat/test_system_prompt_template.py`，文件末尾追加：

```python
@pytest.mark.unit
def test_memory_tool_usage_warns_not_to_modify_user_section() -> None:
    """Plan Task 18 — 双轨保护 prompt 约束."""
    from pathlib import Path

    template = Path(
        "backend/app/agents/chat/prompts/memory_tool_usage.md"
    ).read_text(encoding="utf-8")

    assert "不要试图修改" in template
    assert "你声明的" in template
```

- [ ] **Step 2: 运行 FAIL**

```bash
uv run pytest backend/tests/unit/agents/chat/test_system_prompt_template.py::test_memory_tool_usage_warns_not_to_modify_user_section -v
```

Expected: fail。

- [ ] **Step 3: 改 prompt 模板**

打开 `backend/app/agents/chat/prompts/memory_tool_usage.md`，定位到现有 "## Don't save (反例 — 避免 over-writing)" 段（约行 88-97），**在该段末尾**追加：

```markdown
- **❌ 不要试图修改 [你声明的] 区的任何 bullet**: 这些是用户手动添加 / 改过的
  画像条目, 是用户的"主权区". `core_memory_replace` 只能 match agent 写入的
  bullet (即 `## agent 观察到的` 段下的 - 项). 若你认为用户区某条已过期或与
  事实冲突, **向用户提议**, 不要直接 replace.
```

- [ ] **Step 4: 运行 PASS + commit**

```bash
uv run pytest backend/tests/unit/agents/chat/test_system_prompt_template.py -v
```

Expected: 全 PASS（含既有测试 + 新加 1 个）。

```bash
git add backend/app/agents/chat/prompts/memory_tool_usage.md backend/tests/unit/agents/chat/test_system_prompt_template.py
git commit -m "feat(persona-ui): prompt warns agent not to modify user-declared section (Plan Task 18)"
```

---

### Task 19: L1 双轨保护 e2e

**Files:**
- Create: `backend/tests/integration/memory/test_agent_double_track_protection.py`

- [ ] **Step 1: 写 e2e**

新建 `backend/tests/integration/memory/test_agent_double_track_protection.py`：

```python
"""Plan Task 19 — agent 试图改 user 区被服务层拒绝 + fallback 落 agent 区."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.memory.persona_service import PersonaService

pytestmark = pytest.mark.integration


def test_agent_replace_user_text_falls_back_to_agent_append(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = PersonaService(pg_session_factory=pg_memory_session_factory)
    user_id = uuid4()

    # 1. user 声明一条
    user_item = svc.add_item(
        user_id=user_id, text="风险偏好：保守稳健", target_section="user"
    )

    # 2. agent 通过 apply_agent_replace 试图改 user 区那条
    items = svc.apply_agent_replace(
        user_id=user_id,
        old_content="风险偏好：保守稳健",
        new_content="风险偏好：激进进取",
    )

    # 3. user 区那条原封不动
    assert items[0].source == "agent"
    assert items[0].text == "风险偏好：激进进取"

    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 1
    assert result["user_declared"][0].item_id == user_item.item_id
    assert result["user_declared"][0].text == "风险偏好：保守稳健"
    # agent 区新增了一条 (fallback append)
    assert len(result["agent_inferred"]) == 1
    assert result["agent_inferred"][0].text == "风险偏好：激进进取"


def test_agent_append_never_writes_to_user_section(pg_memory_session_factory):  # type: ignore[no-untyped-def]
    svc = PersonaService(pg_session_factory=pg_memory_session_factory)
    user_id = uuid4()

    svc.apply_agent_append(user_id=user_id, content="- 关注新能源\n- 偏好长期持有\n")

    result = svc.list_items(user_id=user_id)
    assert len(result["user_declared"]) == 0
    assert len(result["agent_inferred"]) == 2
    assert all(i.source == "agent" for i in result["agent_inferred"])
```

- [ ] **Step 2: 运行 PASS**

```bash
uv run pytest backend/tests/integration/memory/test_agent_double_track_protection.py -v
```

Expected: 2 passed。

- [ ] **Step 3: commit**

```bash
git add backend/tests/integration/memory/test_agent_double_track_protection.py
git commit -m "test(persona-ui): L1 double-track protection — agent cannot modify user section (Plan Task 19)"
```

---

## Phase 5 — 收尾 dogfood + 项目知识沉淀（Tasks 20–21）

### Task 20: dogfood 一轮真 session + 调整

**Files:** 无新增；如 dogfood 发现 bug，针对性修。

- [ ] **Step 1: 全栈起服务**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
uv run poe serve &
SERVE_PID=$!
cd frontend && npm run dev &
DEV_PID=$!
```

记录 SERVE_PID + DEV_PID 待后续 kill。

- [ ] **Step 2: 用浏览器跑一轮 dogfood**

按以下顺序操作，记录任何 UX 问题 / bug：

1. 注册 / 登录一个新 user
2. 打开 /memory, 看到画像 tab 默认 + 空状态 + "添加我的第一条" 按钮
3. 添加 3 条 user 区 ("研究员", "保守", "关注新能源")
4. 切到 /chat 聊一句 "我最近想加大科技股仓位"
5. 等 agent 回复完成 → 应触发 core_memory_append (agent 区新增 1+ 条)
6. 切回 /memory → 看到 agent 区出现新条目
7. 编辑 agent 区一条 → 看到迁移高亮 + 出现在 user 区
8. 删除 user 区一条 → Popconfirm 后消失
9. chat 顶角点 "📋 我的画像" → 跳回 /memory#persona

记录任何 UX bug。

- [ ] **Step 3: kill servers**

```bash
kill $SERVE_PID $DEV_PID
```

- [ ] **Step 4: 修 dogfood 发现的 bug（如有）**

针对性 commit。无 bug 则跳过。

---

### Task 21: 写 claude-context 项目知识卡 + CLAUDE.md 索引

**Files:**
- Create: `docs/claude-context/persona-editable-ui-done.md`
- Modify: `CLAUDE.md`（在合适分组下加一行索引）

- [ ] **Step 1: 写 done 卡**

新建 `docs/claude-context/persona-editable-ui-done.md`：

```markdown
---
name: persona-editable-ui-done
description: Tier 1 persona block ChatGPT 风列表式可编辑 UI ship — 双轨 / atomic / 升级动画 / agent 双层保护
type: project
---

Persona Editable UI ship — YYYY-MM-DD（按真实日期填）。

**结论:** /memory 页加 "画像" 默认 tab, 以 ChatGPT 风列表式 UI 暴露 Tier 1
persona block, 物理分 "你声明的" / "agent 观察到的" 双 section, agent 不可改
user 区 (服务层 + prompt 双层 enforce); 用户改 agent 区条自动升级 user 区 +
高亮动画提示。

**Why:**
- c5 cross-session memory ship 后 Tier 1 working blocks 缺用户交互入口
- dogfood 无法验 self-managed memory 写入质量

**How to apply:**
- persona 写入路径: 用户 UI → /api/v0/persona/* → PersonaService → ChatMemoryPersonaItem
- agent 写入路径: chat → core_memory_append/replace → PersonaService.apply_agent_*
  → 同 PG 表
- prompt cache 兼容: PersonaService._sync_to_working_block 把 items 渲染回
  working_blocks.persona.content; ChatPlanner Phase 1 render_persona_markdown
  路径不变

**Anchor:**
- spec: `docs/superpowers/specs/2026-05-17-persona-editable-ui-design.md`
- plan: `docs/superpowers/plans/2026-05-17-persona-editable-ui-plan.md`

**ship 范围 (21 task):**

| Phase | 范围 |
|---|---|
| 1 | schema + persona_items_md + PersonaService(CRUD + agent_*) + render/sync + migration |
| 2 | persona_router 4 endpoint + L1 e2e + chat_planner 端到端 |
| 3 | personaApi client + MemoryPersona 组件 (read/edit/add/delete/upgrade-anim) + chat 顶角入口 + /memory tab 默认 + Playwright e2e |
| 4 | HierarchicalMemory.core_memory_* persona 分支 + prompt 双轨保护段 + L1 保护 e2e |
| 5 | dogfood + 沉淀 |

**关键决策:**
- 持久化形态: markdown blob → row-per-item with stable UUID (新表 chat_memory_persona_items)
- agent 写入双轨保护: prompt + service 层双层 enforce
- user 改 agent 区条 → 自动升级 user 区 + 200ms 高亮动画
- 删除 = 物理删 (audit 留 P2 hook)
- agent 写入实时刷新 v1 不做 (SSE 留 P2 hook)

**留 hook (v1.x P2/P3):**
1. agent 写入实时 SSE 刷新
2. 编辑 audit log + 软删
3. items 拖拽排序 UI
4. 多语言 (section heading 走 i18n)
5. scratchpad UI (Phase 4)
```

- [ ] **Step 2: 在 CLAUDE.md 加索引**

打开 `CLAUDE.md`，在 "### Chat 记忆分层 Phase 1(2026-05-16 ship 完)" 段之后追加：

```markdown
### Persona Editable UI(YYYY-MM-DD ship 完)
- [persona editable UI ship](docs/claude-context/persona-editable-ui-done.md) — /memory 加画像 tab + 双轨语义 + atomic 操作 + 升级动画 / 21 task ship
```

YYYY-MM-DD 按实际 commit 日期填。

- [ ] **Step 3: commit**

```bash
git add docs/claude-context/persona-editable-ui-done.md CLAUDE.md
git commit -m "docs(claude-context): persona editable UI done card + CLAUDE.md index (Plan Task 21)"
```

---

## Self-Review

**1. Spec coverage:**

| Spec 段 | Plan Task |
|---------|----------|
| § 4.1 schema | Task 1 |
| § 4.2 working_blocks 兼容 | Task 5 |
| § 4.3 渲染契约 | Task 2 |
| § 5 决策 1 (UUID) | Task 1 + Task 3 |
| § 5 决策 2 (双层保护) | Task 4 (service) + Task 18 (prompt) + Task 19 (e2e) |
| § 5 决策 3 (source 升级) | Task 3 (service) + Task 13 (UI 动画) |
| § 5 决策 4 (物理删) | Task 3 + Task 13 |
| § 5 决策 5 (无实时刷新) | Plan 未实现 — 符合 spec scope |
| § 5 决策 6 (position 排序) | Task 1 + Task 3 |
| § 6 前端 UI 全部 | Tasks 12-15 |
| § 7 API schema 全部 | Tasks 7-8 |
| § 8 agent 转译 | Tasks 4 + 17 + 18 |
| § 9 Migration | Task 6 |
| § 10 错误处理 | Tasks 3 / 8 / 12 (含 toast + alert + retry) |
| § 11 测试设计 | Tasks 1-19 全程 TDD |
| § 13 项目集成 | Task 17 + render_persona_markdown 路径保留 |

无缺漏。

**2. Placeholder scan:** 已检：
- `_get_current_user_id` 在 Task 8 Step 4 明确说"找现有 auth dep 替换", 不是 TBD
- `get_persona_session_factory` 占位 + Task 6 给了 fallback 实现说明
- Task 14 chat landing 路径需 grep 确认 — 给了 grep 命令和处理策略

均非 placeholder, 而是 grep-then-replace 模式。

**3. Type 一致性:**
- `PersonaItem.source: 'user' | 'agent'` 在 Frontend (Task 11) 跟 Backend `TargetSection = Literal['user', 'agent']` (Task 7) 一致
- `item_id` 在 ORM 层叫 `item_id` (Task 1), API 层映射为 `id` (Task 7 PersonaItemOut), 前端用 `id` (Task 11)
- `apply_agent_append` 跟 `apply_agent_replace` 签名在 Task 4 / Task 17 一致

无问题。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-17-persona-editable-ui-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 我 dispatch 一个 fresh subagent 跑每个 task, review between tasks, 快速迭代; 适合这种 21 task 的中型 plan, 避免主 context 被实施细节淹没

**2. Inline Execution** - 在本 session 用 executing-plans 批量跑, 含 checkpoint, 适合你想紧密跟踪每步

**Which approach?**
