# Chat 记忆分层 Plan 1 — Self-Managed Wire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 chat 模式 self-managed memory 三要素的最后一步接通 — 让 `memory_tool_usage.md` 教程 prompt 和 working_blocks 当前内容真正拼回 `chat_planner` 主 prompt,使 agent 在每轮对话中能自主调用 6 个 MCP memory tools 写入记忆。

**Architecture:** 新建轻量渲染层(`backend/app/memory/render.py`)从 PG `chat_memory_working_blocks` 表读 persona + scratchpad 内容渲染为 markdown;新建 prompt loader(`backend/app/agents/chat/prompt_loader.py`)加载 `memory_tool_usage.md` 模板并用 Jinja-style `{{persona_block}}` / `{{scratchpad_block}}` 占位符替换;`chat_planner._build_chat_prompt` 在拼主 prompt 前先拼这块教程 + 当前内容。**不引入新表**,沿用 c5 已 ship 的 working_blocks 架构;Phase 4 才正式拆出 `chat_scratchpad` 独立表。

**Tech Stack:** Python 3.11+, FastAPI, LangGraph 1.x, SQLAlchemy 2.x sync Session, pytest 8.x, ruff, mypy strict

**Spec anchor:** `docs/superpowers/specs/2026-05-16-chat-memory-layering-design.md` § 6 决策 8 + § 7 Phase 1

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `backend/app/agents/chat/prompts/memory_tool_usage.md` | **Modify** | 加 3 条 domain-specific save triggers + 4 条 Don't save 反例(Hermes 风的"WHEN TO SAVE" 教程,金融业务定制) |
| `backend/app/memory/render.py` | **Create** | `render_persona_markdown(user_id) -> str` + `render_scratchpad_markdown(user_id) -> str` 纯函数。从 c5 已 ship 的 `HierarchicalMemory.get_working_blocks` 读 → 渲染 markdown |
| `backend/app/agents/chat/prompt_loader.py` | **Create** | `load_memory_tool_usage_prompt(user_id, session_id, memory) -> str` — 加载 `memory_tool_usage.md`,用 render.py 函数填占位符 |
| `backend/app/agents/chat_planner.py` | **Modify** | `_build_chat_prompt` 在拼主 prompt 前 prepend memory_tool_usage 块 |
| `backend/tests/unit/memory/test_render.py` | **Create** | render_persona_markdown / render_scratchpad_markdown 单测 |
| `backend/tests/unit/agents/test_prompt_loader.py` | **Create** | load_memory_tool_usage_prompt 单测 |
| `backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py` | **Create** | L1 端到端 — 验证 chat_planner._build_chat_prompt 输出含 persona/scratchpad/三条 save triggers |

**DRY check**:`HierarchicalMemory.get_working_blocks` 已 ship,直接复用;`memory_tool_usage.md` 已存在,只 Edit 加 3 条 + 4 条;`chat_planner.py:_build_chat_prompt` 已存在,只在头部 prepend 一块。**0 重复造轮**。

---

## Task 1: 加 domain-specific save triggers 到 memory_tool_usage.md

**Files:**
- Modify: `backend/app/agents/chat/prompts/memory_tool_usage.md`(在末尾追加两节)
- Test: `backend/tests/unit/memory/test_system_prompt_template.py`(已存在,加 3 个新断言)

- [ ] **Step 1: 在 test_system_prompt_template.py 末尾加新断言**

写入 `backend/tests/unit/memory/test_system_prompt_template.py` 末尾(文件末尾追加):

```python
def test_template_has_domain_specific_save_triggers() -> None:
    """Plan 1 spec § 6 决策 8 — 金融业务定制 save triggers."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 3 条 domain-specific save triggers
    assert "投资偏好" in content
    assert "加减仓" in content or "HOLDS" in content
    assert "EXPRESSED_VIEW" in content
    # Don't save 反例
    assert "一次性" in content or "闲聊" in content


def test_template_has_dont_save_section() -> None:
    """Phase 1 — 反例避免 agent over-write."""
    content = PROMPT_PATH.read_text(encoding="utf-8")
    # 反例 section 必须存在
    assert "Don't save" in content or "不要 save" in content
```

- [ ] **Step 2: 运行测试验证 fail**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
uv run pytest backend/tests/unit/memory/test_system_prompt_template.py::test_template_has_domain_specific_save_triggers backend/tests/unit/memory/test_system_prompt_template.py::test_template_has_dont_save_section -v
```

Expected: 2 FAIL,关键词在模板中找不到。

- [ ] **Step 3: 在 memory_tool_usage.md 末尾追加两节**

编辑 `backend/app/agents/chat/prompts/memory_tool_usage.md`,在文件末尾追加:

```markdown

## Domain-specific save triggers (Phase 1 — 金融业务定制)

These are the high-signal patterns specific to financial research chat. Match
them proactively without waiting for the user to say "remember this":

- **用户表达投资偏好 / 风格 / 禁忌** → `core_memory_append("persona", content)`
  Examples: "我只买白马股" / "我不碰 ST" / "我偏好稳健" / "我资产规模 200 万"
- **用户报告加仓 / 减仓 / 新增关注** → `archival_memory_insert` with `rel_type="HOLDS"` or `"WATCHES"`
  Examples: "我加仓了 500 股茅台" / "卖出宁德 200 股" / "开始关注半导体板块"
- **用户对某股 / 行业表态 / 给出研究结论** → `archival_memory_insert` with `rel_type="EXPRESSED_VIEW"`
  Examples: "我看好 AI 算力链" / "对消费股谨慎" / "认为茅台估值合理"
- **用户纠正之前记忆里的事实** → `core_memory_replace` 或 archival 重写
  Examples: "其实我重仓的是宁德不是比亚迪" / "之前说错了,我不持有招商"

## Don't save (反例 — 避免 over-writing)

Do NOT call write tools for:

- **一次性事实查询**:用户问"茅台今天涨没涨" / "立讯精密的市盈率" — 这是查询,不是表态
- **闲聊 / 寒暄**:"你好" / "在吗" / "谢谢"
- **agent 自己推理的"事实"**:你只能写用户消息或前面 agent 回复里**原文出现过的事实**;
  evidence_quote substring 校验会 reject 你瞎编的内容
- **agent 临时计算结果**:DCF 估值数字 / 财务比率 — 这些每次跑都不同,不该入长期记忆

## Self-managed loop (核心理念)

每次用户消息后,在生成回复**之前**,自问:
1. 用户这句话有没有暴露稳定的偏好 / 持仓 / 表态?
2. 跟你已经看到的 [画像] / [持仓与关注] 块对比,是不是新信息或更新?
3. 是的话,先调一次 memory write tool,再产生回复。

参考 MemGPT (Letta 2023) 的 agent-self-managed memory 哲学:agent 是自己长期记忆的
管理员,不依赖后台批处理。
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest backend/tests/unit/memory/test_system_prompt_template.py -v
```

Expected: 全部 PASS(原有 6 个 + 新加 2 个 = 8 个)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/prompts/memory_tool_usage.md \
        backend/tests/unit/memory/test_system_prompt_template.py
git commit -m "$(cat <<'EOF'
feat(memory): add 3 domain-specific save triggers + 4 don't-save examples

Spec § 6 决策 8 — memory_tool_usage.md 加金融业务定制 self-managed prompt:
- 3 条 save triggers: 投资偏好 / 加减仓 / 表态 / 纠正
- 4 条 Don't save: 一次性查询 / 闲聊 / agent 推理 / 临时计算
- Self-managed loop 核心理念段(参考 MemGPT Letta 2023)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 新建 render.py — 渲染 working_blocks 为 markdown

**Files:**
- Create: `backend/app/memory/render.py`
- Test: `backend/tests/unit/memory/test_render.py`

- [ ] **Step 1: 写 failing tests**

写入 `backend/tests/unit/memory/test_render.py`:

```python
"""L0 — render_persona_markdown / render_scratchpad_markdown 纯函数."""
from __future__ import annotations

from uuid import UUID
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.memory.render import (
    render_persona_markdown,
    render_scratchpad_markdown,
)


@pytest.fixture
def fake_user_id() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_render_persona_markdown_empty(fake_user_id: UUID) -> None:
    """空 working_blocks 返回 placeholder 字符串."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await render_persona_markdown(memory, fake_user_id)
    assert result == "(暂无画像 — 用户首次对话,等待信号沉淀)"


@pytest.mark.asyncio
async def test_render_persona_markdown_with_content(fake_user_id: UUID) -> None:
    """有 persona block 渲染为 markdown."""
    block = MagicMock()
    block.content = "- 风险偏好: 稳健\n- 不碰: ST / 高估值"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"persona": block})

    result = await render_persona_markdown(memory, fake_user_id)
    assert "风险偏好: 稳健" in result
    assert "不碰: ST" in result


@pytest.mark.asyncio
async def test_render_scratchpad_markdown_empty(fake_user_id: UUID) -> None:
    """空 scratchpad 返回 placeholder."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await render_scratchpad_markdown(memory, fake_user_id)
    assert result == "(本 session 暂无便签)"


@pytest.mark.asyncio
async def test_render_scratchpad_markdown_with_content(fake_user_id: UUID) -> None:
    """有 scratchpad block 渲染."""
    block = MagicMock()
    block.content = "- 本轮在追立讯精密 002475"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"scratchpad": block})

    result = await render_scratchpad_markdown(memory, fake_user_id)
    assert "立讯精密" in result


@pytest.mark.asyncio
async def test_render_persona_markdown_handles_db_error(fake_user_id: UUID) -> None:
    """get_working_blocks 抛错时返回 placeholder,不让 chat 崩."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(side_effect=RuntimeError("DB down"))

    result = await render_persona_markdown(memory, fake_user_id)
    assert "(画像渲染失败" in result
```

- [ ] **Step 2: 验证 fail**

```bash
uv run pytest backend/tests/unit/memory/test_render.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.memory.render'`

- [ ] **Step 3: 写 render.py 实现**

写入 `backend/app/memory/render.py`:

```python
"""Working blocks → markdown 渲染层.

Phase 1 — self-managed wire 用,从 c5 已 ship 的 HierarchicalMemory.get_working_blocks
拉 persona / scratchpad block,渲染成 markdown 字符串供 chat_planner prompt 注入。

设计要点:
- 纯函数 + async(因 get_working_blocks 是 async)
- 失败隔离:DB 错误返回 placeholder,不让 chat 崩
- Phase 4 把 scratchpad 拆出独立表后,本模块再加 render_scratchpad_from_session(session_id)
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


_PERSONA_EMPTY = "(暂无画像 — 用户首次对话,等待信号沉淀)"
_SCRATCHPAD_EMPTY = "(本 session 暂无便签)"


async def render_persona_markdown(memory: Any, user_id: UUID) -> str:
    """渲染 persona working block 为 markdown 字符串.

    Args:
        memory: HierarchicalMemory 实例(Memory Protocol).
        user_id: 用户 UUID.

    Returns:
        markdown 字符串. 空 block 返回 placeholder; DB 错误返回 error placeholder.
    """
    try:
        blocks = await memory.get_working_blocks(user_id)
    except Exception as exc:
        logger.warning("render_persona_markdown: get_working_blocks failed: %s", exc)
        return f"(画像渲染失败 — {type(exc).__name__})"

    block = blocks.get("persona")
    if block is None or not block.content:
        return _PERSONA_EMPTY
    return str(block.content)


async def render_scratchpad_markdown(memory: Any, user_id: UUID) -> str:
    """渲染 scratchpad working block 为 markdown.

    Phase 1 沿用 c5 working_blocks 表(user-scoped, 不是 session-scoped).
    Phase 4 拆出独立 chat_scratchpad 表后,签名会从 user_id 改成 session_id.
    """
    try:
        blocks = await memory.get_working_blocks(user_id)
    except Exception as exc:
        logger.warning("render_scratchpad_markdown: get_working_blocks failed: %s", exc)
        return f"(便签渲染失败 — {type(exc).__name__})"

    block = blocks.get("scratchpad")
    if block is None or not block.content:
        return _SCRATCHPAD_EMPTY
    return str(block.content)
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest backend/tests/unit/memory/test_render.py -v
uv run mypy backend/app/memory/render.py
uv run ruff check backend/app/memory/render.py backend/tests/unit/memory/test_render.py
```

Expected: 5 PASS / 0 mypy error / 0 ruff error。

- [ ] **Step 5: Commit**

```bash
git add backend/app/memory/render.py backend/tests/unit/memory/test_render.py
git commit -m "$(cat <<'EOF'
feat(memory): render_persona / render_scratchpad markdown 纯函数

Spec § 7 Phase 1 — 从 c5 HierarchicalMemory.get_working_blocks 拉
working_blocks → markdown 字符串, 供 chat_planner 注入.

DB 错误隔离 (chat 不崩); 空 block placeholder; mypy strict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 新建 prompt_loader.py — 加载并渲染 memory_tool_usage 模板

**Files:**
- Create: `backend/app/agents/chat/prompt_loader.py`
- Test: `backend/tests/unit/agents/test_prompt_loader.py`

- [ ] **Step 1: 写 failing test**

先确认目录存在:

```bash
mkdir -p backend/tests/unit/agents
touch backend/tests/unit/agents/__init__.py
```

写入 `backend/tests/unit/agents/test_prompt_loader.py`:

```python
"""L0 — load_memory_tool_usage_prompt 模板加载 + 占位符替换."""
from __future__ import annotations

from uuid import UUID
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.agents.chat.prompt_loader import load_memory_tool_usage_prompt


@pytest.fixture
def fake_user_id() -> UUID:
    return UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def fake_session_id() -> UUID:
    return UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.asyncio
async def test_load_returns_string_containing_template_content(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    # 含模板原文关键段
    assert "Memory Tool Usage" in result
    assert "Tier 1" in result
    assert "Tier 2" in result
    # 含 Phase 1 新增的 domain-specific save triggers
    assert "投资偏好" in result
    assert "Don't save" in result or "不要 save" in result


@pytest.mark.asyncio
async def test_load_replaces_persona_placeholder(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    """{{persona_block}} 必须被替换成实际内容."""
    block = MagicMock()
    block.content = "- 风险偏好: 稳健"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"persona": block})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    # 占位符不能残留
    assert "{{persona_block}}" not in result
    assert "{{scratchpad_block}}" not in result
    # 实际内容必须出现
    assert "风险偏好: 稳健" in result


@pytest.mark.asyncio
async def test_load_replaces_scratchpad_placeholder(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    block = MagicMock()
    block.content = "- 本轮在追立讯精密"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"scratchpad": block})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    assert "{{scratchpad_block}}" not in result
    assert "立讯精密" in result


@pytest.mark.asyncio
async def test_load_uses_empty_placeholders_when_no_blocks(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    """空 blocks 替换为人类可读的 placeholder, 不是空字符串."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    result = await load_memory_tool_usage_prompt(
        memory=memory, user_id=fake_user_id, session_id=fake_session_id
    )

    assert "(暂无画像" in result
    assert "(本 session 暂无便签)" in result
```

- [ ] **Step 2: 验证 fail**

```bash
uv run pytest backend/tests/unit/agents/test_prompt_loader.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: 写 prompt_loader.py 实现**

确认 prompts 目录存在(已存在,但安全起见):

```bash
ls backend/app/agents/chat/prompts/memory_tool_usage.md
```

写入 `backend/app/agents/chat/prompt_loader.py`:

```python
"""Memory tool usage prompt loader.

Phase 1 — self-managed wire. 加载 prompts/memory_tool_usage.md, 用 render.py
函数填占位符 {{persona_block}} / {{scratchpad_block}}, 返回完整字符串供
chat_planner._build_chat_prompt 注入.

设计要点:
- 模块加载时缓存模板内容(模板是静态文件,不会运行时变);
- 占位符 sentinel "{{persona_block}}" / "{{scratchpad_block}}" 必须存在,
  缺一就 raise(防 silent miss);
- DB 错误传递给 render.py 处理(它会返回 error placeholder).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.memory.render import (
    render_persona_markdown,
    render_scratchpad_markdown,
)

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "prompts" / "memory_tool_usage.md"
)

_PERSONA_PLACEHOLDER = "{{persona_block}}"
_SCRATCHPAD_PLACEHOLDER = "{{scratchpad_block}}"

# 启动时一次性加载
_TEMPLATE_TEXT: str = _TEMPLATE_PATH.read_text(encoding="utf-8")

# Sanity check (模块导入即触发,防止线上才发现模板坏)
if _PERSONA_PLACEHOLDER not in _TEMPLATE_TEXT:
    raise RuntimeError(
        f"{_TEMPLATE_PATH}: missing placeholder {_PERSONA_PLACEHOLDER!r}"
    )
if _SCRATCHPAD_PLACEHOLDER not in _TEMPLATE_TEXT:
    raise RuntimeError(
        f"{_TEMPLATE_PATH}: missing placeholder {_SCRATCHPAD_PLACEHOLDER!r}"
    )


async def load_memory_tool_usage_prompt(
    memory: Any,
    user_id: UUID,
    session_id: UUID,
) -> str:
    """Load memory_tool_usage.md template + render persona/scratchpad blocks.

    Args:
        memory: HierarchicalMemory 实例.
        user_id: 用户 UUID(画像层 + Phase 1 期 scratchpad 也按 user 取).
        session_id: session UUID(Phase 1 暂未使用, Phase 4 接 chat_scratchpad 表后用).

    Returns:
        完整 memory tool usage prompt 字符串, 占位符已替换.
    """
    persona = await render_persona_markdown(memory, user_id)
    scratchpad = await render_scratchpad_markdown(memory, user_id)

    rendered = _TEMPLATE_TEXT
    rendered = rendered.replace(_PERSONA_PLACEHOLDER, persona)
    rendered = rendered.replace(_SCRATCHPAD_PLACEHOLDER, scratchpad)
    return rendered
```

注意上面 `_TEMPLATE_TEXT` 在模块加载时一次读取,Sanity check 也是模块加载时。如果占位符在 Task 1 编辑模板后还在,这步直接通过。

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest backend/tests/unit/agents/test_prompt_loader.py -v
uv run mypy backend/app/agents/chat/prompt_loader.py
uv run ruff check backend/app/agents/chat/prompt_loader.py backend/tests/unit/agents/test_prompt_loader.py
```

Expected: 4 PASS / 0 mypy / 0 ruff。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/prompt_loader.py \
        backend/tests/unit/agents/test_prompt_loader.py \
        backend/tests/unit/agents/__init__.py
git commit -m "$(cat <<'EOF'
feat(agents): memory_tool_usage prompt loader + placeholder replace

Spec § 7 Phase 1 — 加载 prompts/memory_tool_usage.md, 用 render.py 填
{{persona_block}} / {{scratchpad_block}}.

模板字面 sanity check 在模块加载时跑 (防 silent miss); 一次性 read
启动后不再 I/O.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 修改 chat_planner._build_chat_prompt — 拼回 memory prompt

**Files:**
- Modify: `backend/app/agents/chat_planner.py:392-424`(`_build_chat_prompt` 方法)
- Test: 已有 unit test 通过即可,L1 e2e 在 Task 5。

- [ ] **Step 1: 写 unit test 守护新行为**

在 `backend/tests/unit/agents/test_prompt_loader.py` 末尾追加(不新建文件,跟 prompt_loader 同源):

```python
@pytest.mark.asyncio
async def test_chat_planner_build_prompt_includes_memory_section(
    fake_user_id: UUID, fake_session_id: UUID
) -> None:
    """ChatPlanner._build_chat_prompt 必须在主 prompt 前 prepend memory tool usage.

    Spec § 7 Phase 1 — self-managed wire 最后一步.
    """
    from unittest.mock import MagicMock as _MagicMock
    from app.agents.chat_planner import ChatPlanner
    from app.agents.schemas import ChatState, HistoryMessage

    block = _MagicMock()
    block.content = "- 风险偏好: 稳健"
    memory = _MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={"persona": block})

    llm = _MagicMock()
    planner = ChatPlanner(
        llm=llm,
        available_tools=["fetch_quote"],
        memory=memory,  # 新增 DI
    )

    state = ChatState(
        user_id=str(fake_user_id),
        session_id=str(fake_session_id),
        user_message="我想看看立讯精密",
        history=[],
    )

    prompt = await planner._build_chat_prompt(state)

    # memory tool usage 段先于主 prompt
    assert "Memory Tool Usage" in prompt
    assert "风险偏好: 稳健" in prompt  # persona 渲染成功
    assert "用户当前问题:" in prompt
    # 顺序: memory tool usage → 主 prompt
    assert prompt.index("Memory Tool Usage") < prompt.index("用户当前问题:")
```

- [ ] **Step 2: 验证 fail**

```bash
uv run pytest backend/tests/unit/agents/test_prompt_loader.py::test_chat_planner_build_prompt_includes_memory_section -v
```

Expected: FAIL — `ChatPlanner.__init__()` 不接受 `memory` 参数,或 `_build_chat_prompt` 是 sync 没 await。

- [ ] **Step 3: 修改 `chat_planner.py`**

打开 `backend/app/agents/chat_planner.py`,做四处改动:

**改动 a:`__init__` 加 `memory` 参数(default None,向后兼容)**

定位到 `__init__` (line 288 附近):

```python
    def __init__(
        self,
        llm: LLMService,
        registry: ToolRegistry | None = None,
        available_tools: list[str] | None = None,
        available_skills: list[str] | None = None,
        recent_k: int = 4,
        memory: Any | None = None,  # ← 新增, Phase 1 self-managed wire
    ) -> None:
        super().__init__(llm)
        self._registry = registry
        self._available_tools = available_tools or []
        self._available_skills = available_skills or []
        self._recent_k = recent_k
        self._memory = memory  # ← 新增
```

**改动 b:`_build_chat_prompt` 改成 async 并 prepend memory 块**

完整替换原 `_build_chat_prompt` 方法:

```python
    async def _build_chat_prompt(self, state: ChatState) -> str:
        tool_lines = (
            [f"- {t}" for t in self._available_tools]
            if self._available_tools
            else ["(no tools)"]
        )
        recent = state.history[-self._recent_k :] if state.history else []
        recent_lines = [
            f"[{m.turn_index}] {m.role}: {m.content[:200]}" for m in recent
        ]
        prompt = _PLANNER_PROMPT_TEMPLATE.format(
            tool_descriptions="\n".join(tool_lines),
            user_message=state.user_message,
            history_summary=state.history_summary or "(无)",
            recent_k=self._recent_k,
            recent_turns="\n".join(recent_lines) or "(无)",
        )

        # === Plan 6 (c5) — segregation blocks injection ===
        user_ctx_block = _format_memory_hits(state.memory_hits)
        market_block = _format_kb_hits(state.kb_hits)

        if user_ctx_block or market_block:
            inject_parts: list[str] = []
            if user_ctx_block:
                inject_parts.append(user_ctx_block)
            if market_block:
                inject_parts.append(market_block)
            if user_ctx_block and market_block:
                inject_parts.append(_SEGREGATION_DISCLAIMER)
            inject_block = "\n\n".join(inject_parts) + "\n\n"
            anchor = "用户当前问题:"
            prompt = prompt.replace(anchor, inject_block + anchor, 1)

        # === Phase 1 (chat-memory-layering) — self-managed wire ===
        # spec § 7 Phase 1: memory_tool_usage prompt prepend 到主 prompt 头部
        if self._memory is not None:
            try:
                from uuid import UUID
                from app.agents.chat.prompt_loader import (
                    load_memory_tool_usage_prompt,
                )

                memory_block = await load_memory_tool_usage_prompt(
                    memory=self._memory,
                    user_id=UUID(state.user_id),
                    session_id=UUID(state.session_id),
                )
                prompt = memory_block + "\n\n---\n\n" + prompt
            except Exception as exc:
                # 失败隔离 — chat 不崩, 仅 log
                logger.warning(
                    "memory_tool_usage prompt injection failed: %s", exc
                )

        return prompt
```

**改动 c:`run()` 方法调用处加 await**

定位到 `async def run` (line 306) 里:

```python
        prompt = self._build_chat_prompt(state)
```

改成:

```python
        prompt = await self._build_chat_prompt(state)
```

**改动 d:确认 `logger` 已 import**

`chat_planner.py` 文件顶部应已有 `logger = logging.getLogger(__name__)`(c5 plan 3 加过)。若没有,在 import 段后加:

```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: 验证测试通过**

```bash
uv run pytest backend/tests/unit/agents/test_prompt_loader.py -v
uv run mypy backend/app/agents/chat_planner.py
uv run ruff check backend/app/agents/chat_planner.py
```

Expected:
- 5 个 prompt_loader tests + 1 个 chat_planner test = 6 PASS
- mypy 0 error
- ruff 0 error

**回归检查**:跑现有 chat 测试,确认没破坏:

```bash
uv run pytest backend/tests/unit/agents/ backend/tests/integration/agents/ -v --ignore=backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py 2>&1 | tail -20
```

Expected:无新 fail(c5 已有 chat_planner 相关测试若 fixture 不传 `memory=` 参数 default None,prepend 路径被 skip → 行为不变)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat_planner.py \
        backend/tests/unit/agents/test_prompt_loader.py
git commit -m "$(cat <<'EOF'
feat(chat-planner): prepend memory_tool_usage prompt to main planner prompt

Spec § 7 Phase 1 最后一步 — self-managed wire 接通.

改动:
- ChatPlanner.__init__ 新增 memory DI 参数 (default None, 向后兼容)
- _build_chat_prompt 变 async, 在主 prompt 前 prepend memory_tool_usage
  block (含 persona + scratchpad 渲染内容)
- run() 改 await self._build_chat_prompt
- 失败隔离: load_memory_tool_usage_prompt 出错只 log, chat 不崩

此 commit 后 agent 在每轮对话能看到当前画像 + 便签 + 6 个 memory tools
+ 何时调用的 self-managed prompt, MemGPT 范式 wire complete.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: L1 integration test — chat_planner self-managed e2e

**Files:**
- Create: `backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py`

- [ ] **Step 1: 写 e2e test**

确认目录:

```bash
mkdir -p backend/tests/integration/agents
test -f backend/tests/integration/agents/__init__.py || touch backend/tests/integration/agents/__init__.py
```

写入 `backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py`:

```python
"""L1 — chat_planner self-managed memory prompt e2e.

Spec § 7 Phase 1 DoD — verify:
  1. session 起手 prompt 头部含 [画像] / [便签] 内容
  2. 3 条 domain-specific save triggers 可见
  3. 失败隔离: memory 抛错时 chat 仍能产生 prompt
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.agents.chat_planner import ChatPlanner
from app.agents.schemas import ChatState


@pytest.fixture
def fake_llm() -> MagicMock:
    return MagicMock()


@pytest.fixture
def fake_state() -> ChatState:
    return ChatState(
        user_id=str(uuid4()),
        session_id=str(uuid4()),
        user_message="我想加仓 500 股茅台",
        history=[],
    )


@pytest.mark.asyncio
async def test_e2e_prompt_contains_persona_scratchpad_triggers_and_user_msg(
    fake_llm: MagicMock, fake_state: ChatState
) -> None:
    """端到端: 完整 chat_planner build_chat_prompt 输出全部必要段."""
    persona_block = MagicMock()
    persona_block.content = "- 风险偏好: 稳健\n- 资产规模: 200 万"
    scratch_block = MagicMock()
    scratch_block.content = "- 本轮在追立讯精密 002475"
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(
        return_value={"persona": persona_block, "scratchpad": scratch_block}
    )

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote", "archival_memory_insert"],
        memory=memory,
    )

    prompt = await planner._build_chat_prompt(fake_state)

    # 1. memory block 段 (Tier 1 + Tier 2 + Tier 3)
    assert "Memory Tool Usage" in prompt
    assert "Tier 1" in prompt
    assert "Tier 2" in prompt
    assert "Tier 3" in prompt

    # 2. persona + scratchpad 实际内容
    assert "风险偏好: 稳健" in prompt
    assert "立讯精密" in prompt

    # 3. 3 条 domain-specific save triggers
    assert "投资偏好" in prompt
    assert "HOLDS" in prompt or "加仓" in prompt
    assert "EXPRESSED_VIEW" in prompt or "表态" in prompt

    # 4. 反例 Don't save
    assert "一次性" in prompt or "闲聊" in prompt

    # 5. 主 prompt 段 (planner template)
    assert "用户当前问题:" in prompt
    assert "我想加仓 500 股茅台" in prompt

    # 6. 顺序: memory block 在主 prompt 之前
    assert prompt.index("Memory Tool Usage") < prompt.index("用户当前问题:")


@pytest.mark.asyncio
async def test_e2e_no_memory_di_falls_back_gracefully(
    fake_llm: MagicMock, fake_state: ChatState
) -> None:
    """memory=None 时, prompt 不含 memory block 但主 prompt 完整 (向后兼容)."""
    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=None,
    )

    prompt = await planner._build_chat_prompt(fake_state)

    # 主 prompt 仍然完整
    assert "用户当前问题:" in prompt
    assert "我想加仓 500 股茅台" in prompt
    # memory block 段不存在
    assert "Memory Tool Usage" not in prompt


@pytest.mark.asyncio
async def test_e2e_memory_db_error_isolated(
    fake_llm: MagicMock, fake_state: ChatState
) -> None:
    """memory.get_working_blocks 抛 DB error 时, chat 仍能产生 prompt."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(side_effect=RuntimeError("PG down"))

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=memory,
    )

    prompt = await planner._build_chat_prompt(fake_state)

    # 主 prompt 必须能产生
    assert "用户当前问题:" in prompt
    # memory section 出现, 但内容是 error placeholder
    assert "Memory Tool Usage" in prompt
    assert "画像渲染失败" in prompt or "便签渲染失败" in prompt


@pytest.mark.asyncio
async def test_e2e_empty_working_blocks_uses_placeholders(
    fake_llm: MagicMock, fake_state: ChatState
) -> None:
    """空 working_blocks → 用人类可读 placeholder."""
    memory = MagicMock()
    memory.get_working_blocks = AsyncMock(return_value={})

    planner = ChatPlanner(
        llm=fake_llm,
        available_tools=["fetch_quote"],
        memory=memory,
    )

    prompt = await planner._build_chat_prompt(fake_state)

    assert "(暂无画像" in prompt
    assert "(本 session 暂无便签)" in prompt
```

- [ ] **Step 2: 验证 fail / pass**

```bash
uv run pytest backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py -v
```

Expected: 4 PASS(Task 4 已实现完毕,这里只是端到端 validation,应直接绿)。

- [ ] **Step 3: 跑 full chat test suite 回归**

```bash
uv run pytest backend/tests/ -k "chat or planner or memory" -v 2>&1 | tail -30
```

Expected: 无新 fail(已有 12 个 pre-existing test failures 不在 plan 1 责任范围,见 `c5-cross-session-memory-done.md` 末尾 Known test failures)。

- [ ] **Step 4: Final mypy + ruff sweep**

```bash
uv run mypy backend/app/memory/render.py backend/app/agents/chat/prompt_loader.py backend/app/agents/chat_planner.py
uv run ruff check backend/app/memory/render.py backend/app/agents/chat/prompt_loader.py backend/app/agents/chat_planner.py backend/tests/unit/memory/test_render.py backend/tests/unit/agents/test_prompt_loader.py backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py
```

Expected: 0 mypy error / 0 ruff error。

- [ ] **Step 5: Commit**

```bash
git add backend/tests/integration/agents/test_chat_planner_self_managed_e2e.py \
        backend/tests/integration/agents/__init__.py
git commit -m "$(cat <<'EOF'
test(chat-planner): L1 e2e — self-managed memory prompt wire

Spec § 7 Phase 1 DoD 守护:
- persona / scratchpad 块渲染进 prompt 头部
- 3 条 domain-specific save triggers + Don't save 段可见
- memory=None 向后兼容 (legacy chat path 不受影响)
- DB error 失败隔离 (chat 仍能产生 prompt)
- 空 working_blocks 用 placeholder, 不留空白

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 接通 chat router DI + 手动 smoke test

**Files:**
- Modify: `backend/app/router/chat.py`(确认 `build_chat_graph` 调用处把 `memory` 传给 ChatPlanner)

- [ ] **Step 1: 查 chat router 当前 ChatPlanner 实例化处**

```bash
grep -n "ChatPlanner(" backend/app/router/chat.py backend/app/orchestration/chat_graph.py
```

定位到实际创建 ChatPlanner 的位置。

- [ ] **Step 2: 写 unit test 守护 DI 接通**

写入 `backend/tests/unit/router/test_chat_router_planner_di.py`(目录可能要建):

```bash
mkdir -p backend/tests/unit/router
test -f backend/tests/unit/router/__init__.py || touch backend/tests/unit/router/__init__.py
```

```python
"""L0 — chat router 实例化 ChatPlanner 时传 memory."""
from __future__ import annotations

import inspect

from app.agents.chat_planner import ChatPlanner


def test_chat_planner_init_accepts_memory_param() -> None:
    """Phase 1 wire 守护 — ChatPlanner.__init__ 必须有 memory 参数."""
    sig = inspect.signature(ChatPlanner.__init__)
    assert "memory" in sig.parameters
    # default 应该是 None (向后兼容)
    assert sig.parameters["memory"].default is None


def test_chat_planner_stores_memory() -> None:
    """memory 必须挂在 instance 上 (chat 节点能读)."""
    from unittest.mock import MagicMock

    planner = ChatPlanner(llm=MagicMock(), memory="<sentinel>")
    assert planner._memory == "<sentinel>"
```

- [ ] **Step 3: 验证 pass**

```bash
uv run pytest backend/tests/unit/router/test_chat_router_planner_di.py -v
```

Expected: 2 PASS(Task 4 已经加了 memory 参数 + 字段)。

- [ ] **Step 4: 检查 chat_graph / chat router 实例化处是否传 memory**

```bash
grep -n "ChatPlanner(" backend/app/orchestration/chat_graph.py backend/app/router/chat.py
```

如果原代码是 `ChatPlanner(llm=llm, available_tools=tools)`(没传 memory),需要在 chat 主流程里把 `memory` 实例(`HierarchicalMemory` 或 `InSessionMemory`)传进去:

预期:`chat_graph.py` 或 `chat.py` 已经在更早 c5 plan 里有 `memory` 局部变量。在 `ChatPlanner(...)` 那行加上 `memory=memory` 参数。

具体 edit(根据 grep 输出定位):

```python
# 修改前 (示例)
planner = ChatPlanner(
    llm=llm,
    available_tools=available_tool_names,
    available_skills=available_skill_names,
)

# 修改后
planner = ChatPlanner(
    llm=llm,
    available_tools=available_tool_names,
    available_skills=available_skill_names,
    memory=memory,  # ← Phase 1 self-managed wire
)
```

- [ ] **Step 5: 跑 serve smoke + 手动验证**

```bash
# serve smoke (import 链没坏)
uv run python -c "from app.app_main import app; print('serve smoke OK')"

# 启动 dev server(后台)
uv run poe serve &
SERVE_PID=$!
sleep 5

# 发一条 chat 请求(假设 chat router 在 /chat),查看 server log 是否有 prompt 拼装日志
# (可选 — 真要看 prompt 拼装,加临时 log)
curl -s -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"user_id":"11111111-1111-1111-1111-111111111111","session_id":"22222222-2222-2222-2222-222222222222","user_message":"你好"}' \
  | head -20

# 关 server
kill $SERVE_PID
```

Expected:server 起来不崩,chat 请求能返回 SSE event(具体内容看 c5 chat 路径)。

- [ ] **Step 6: Final commit**

```bash
git add backend/app/orchestration/chat_graph.py backend/app/router/chat.py \
        backend/tests/unit/router/test_chat_router_planner_di.py \
        backend/tests/unit/router/__init__.py
git commit -m "$(cat <<'EOF'
feat(chat-router): pass memory DI to ChatPlanner — Phase 1 wire complete

Spec § 7 Phase 1 收尾 — chat 主路径实例化 ChatPlanner 时传 memory 参数,
self-managed prompt 在每个真实 chat 请求都生效.

DoD:
- ChatPlanner.__init__ 接 memory param ✓
- chat_graph / chat router 实例化处传 memory=memory ✓
- serve smoke 不崩 ✓
- 真实 chat 请求 SSE 正常 ✓

Phase 1 self-managed wire 完整接通. 下一步: dogfood + Phase 2 画像层
独立 PG 表 (等 dogfood feedback 后 plan).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done Criteria(Phase 1 全部完成的判定)

- ✅ Task 1: `memory_tool_usage.md` 含 3 条 save triggers + 4 条 Don't save
- ✅ Task 2: `render.py` ship,5 个 L0 test PASS
- ✅ Task 3: `prompt_loader.py` ship,4 个 L0 test PASS
- ✅ Task 4: `chat_planner.py` 改造完成,memory DI 注入,1 个新 L0 test PASS
- ✅ Task 5: 4 个 L1 e2e test PASS,mypy + ruff 全绿
- ✅ Task 6: chat router DI 接通,serve smoke 不崩,2 个 L0 test PASS
- ✅ 总计:11 new L0 + 4 new L1 = 15 个新测试全过
- ✅ pre-existing test failures 数量不变(无新增 regression)
- ✅ Spec § 7 Phase 1 行 "把 memory_tool_usage.md 接入 chat planner 主 prompt;working_blocks persona/scratchpad 拼回" DoD 满足

---

## 后续 Phase 预告(不在本 plan 范围)

| Phase | 范围 | 触发条件 |
|---|---|---|
| **Phase 2** | 画像层独立 PG 表 + 从 archival 图迁出"长期身份"类 edge + onboarding 表单 | Phase 1 dogfood ≥ 1 周后,看 self-managed 写入分布,决定画像层是否需要独立 schema |
| **Phase 3** | 持仓层独立 PG 表 + 接 v1.0 监控引擎 hook + 起手快照渲染 | 同上 + 跟 v1.0 portfolio 表 schema 对齐方案敲定 |
| **Phase 4** | 便签层 PG `chat_scratchpad` 表 + session_id 绑定持久化 + session_end_extractor + 冷冻 30 天 Celery beat | Phase 1 ship 后立即可启(便签 session 绑定是 spec § 1 锁定决策)|

---

## Self-Review(2026-05-16)

**Spec coverage check** — 把 spec § 7 Phase 1 的 DoD "session 起手 prompt 头部能看到 persona + scratchpad 内容" 映射到任务:
- ✅ persona 拼回 → Task 2 (render) + Task 3 (loader) + Task 4 (planner inject)
- ✅ scratchpad 拼回 → 同上
- ✅ memory_tool_usage.md 接入 → Task 4 (prepend in _build_chat_prompt)
- ✅ 失败隔离 → Task 4 + Task 5 (e2e DB error test)
- ✅ 向后兼容 → Task 5 (memory=None 测试) + Task 6 (init signature default None)

**Placeholder scan** — 全 plan 无 "TBD" / "TODO" / "implement later";code blocks 全部完整;命令全部具体可执行。

**Type consistency check**:
- `render_persona_markdown(memory: Any, user_id: UUID) -> str` — Task 2 定义,Task 3 / Task 4 使用一致
- `load_memory_tool_usage_prompt(memory, user_id, session_id) -> str` — Task 3 定义,Task 4 使用一致
- `ChatPlanner.__init__(memory: Any | None = None)` — Task 4 定义,Task 6 用 `memory` keyword arg 一致

无 issue 发现,plan 提交可执行。
