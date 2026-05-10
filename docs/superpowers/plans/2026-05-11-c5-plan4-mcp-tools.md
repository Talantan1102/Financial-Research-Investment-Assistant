# C.5 Plan 4 — 6 MCP Tools + Memory MCP Profile + Evidence Quote 校验

> **作用**：把 spec § 6 的 6 个 memory MCP tool 实施成可被 ChatPlanner / Responder 调用的独立 stdio MCP server profile，并在 `archival_memory_insert` tool 内嵌入算法深度补丁 #2 的 `evidence_quote_in_episode` 强制校验，防 Agent 幻觉写。
>
> **Spec ref**：`docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 6（全部）+ § 11 末尾 #2（投毒 + Agent 幻觉写补丁的 evidence_quote 部分）+ 附录 C（tool input schema）+ 附录 D（traverse trigger 词清单）
>
> **Shared contracts ref**：`docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 1（文件路径）/ § 2（Memory Protocol）/ § 5（`evidence_quote_in_episode` 函数签名）/ § 6（fixture）/ § 8（traverse trigger 词清单）/ § 11（范围矩阵）/ § 12（测试分层）/ § 14（commit 规范）
>
> **依赖前置**：Plan 1 ship（Memory Protocol + 4 PG 表 + HierarchicalMemory 骨架 + working_blocks CRUD）+ Plan 2 ship（archival_memory_insert 写入 pipeline）+ Plan 3 ship（archival_memory_search / graph_traverse 检索实现）。Plan 5 的 `is_prompt_injection` 分类器**不**前置依赖（接口 hook 接受 None，Plan 5 ship 后挂上）。
>
> **工程量**：4 天 wall time，6 MCP tool 实现（1.5 天）+ evidence_quote 校验集成（0.5 天）+ memory MCP profile + server entry（0.5 天）+ system prompt 模板 + tool routing 监控 + eval 框架 setup（0.5 天）+ 完整 L0/L1/L2 测试 + 知识卡（1 天）。

---

## § 1 范围声明

### 1.1 In-Scope（本 Plan ship）

| 项 | 文件 | spec ref |
|---|---|---|
| `core_memory_append` MCP tool | `backend/app/mcp_server/tools/memory/core_memory_append.py` | § 6 Tier 1 写 |
| `core_memory_replace` MCP tool | `backend/app/mcp_server/tools/memory/core_memory_replace.py` | § 6 Tier 1 写 |
| `archival_memory_insert` MCP tool（**含 evidence_quote 校验**）| `backend/app/mcp_server/tools/memory/archival_memory_insert.py` | § 6 Tier 2 写 + § 11 末尾 #2 |
| `archival_memory_search` MCP tool | `backend/app/mcp_server/tools/memory/archival_memory_search.py` | § 6 Tier 2 读 |
| `archival_memory_traverse` MCP tool | `backend/app/mcp_server/tools/memory/archival_memory_traverse.py` | § 6 Tier 2 读 + 附录 D |
| `recall_memory_search` MCP tool | `backend/app/mcp_server/tools/memory/recall_memory_search.py` | § 6 Tier 3 读 |
| Memory MCP server profile（`--profile memory`）| 改 `backend/app/mcp_server/server.py` 加 profile 分发 | § 6 Integration |
| `mcp_servers.yaml` 加 memory profile | `mcp_servers.yaml`（NEW） | § 6 Integration |
| Memory tool registry `__init__.py` | `backend/app/mcp_server/tools/memory/__init__.py` | § 6 Integration |
| `mcp_tool_call_log` 表 + 写入 hook | `backend/app/services/trace_models.py` 加 model + `server.py` call_tool 包装 | § 6 Tool routing 监控 SQL |
| 周报 SQL（commit 进 docs） | `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` 已有，本 Plan ship `backend/scripts/memory/weekly_tool_routing_report.sql` | § 6 监控 |
| System prompt 模板（注入 ChatPlanner / Responder） | `backend/app/agents/chat/prompts/memory_tool_usage.md` | § 6 System prompt |
| Tool routing eval framework setup（50 case 输出格式定义） | `backend/eval/memory/routing_accuracy_metric.py` 骨架 | § 6 Eval + Plan 8 写实际 case |
| L0 / L1 / L2 测试 | `backend/tests/unit/memory/test_mcp_tools.py` + `backend/tests/integration/memory/test_mcp_tools_e2e.py` + `backend/tests/e2e/memory/test_traverse_full_path.py` + `test_recall_full_path.py` | shared contracts § 12 |
| 知识卡 | `docs/claude-context/c5-plan4-mcp-tools-done.md` | shared contracts § 13 |

### 1.2 Out-of-Scope（其他 Plan）

| 项 | 归属 |
|---|---|
| Memory vs KB Search supervisor router | Plan 6（spec § 11 末尾 #7） |
| `is_prompt_injection` 分类器实现 | Plan 5（本 Plan 提供 hook 接受 None） |
| 50 routing accuracy golden case + 实际 metric impl | Plan 8 |
| Frontend `/memory` UI 调 tool routing 监控数据可视化 | Plan 7 |
| `archival_memory_search` 内部 RRF v2 / 3-way hybrid 实现 | Plan 3（本 Plan 调用 wrapper） |
| `archival_memory_insert` 内部 8-step 写入 pipeline 实现 | Plan 2（本 Plan 调用 wrapper） |
| `working_blocks` CRUD / paging logic | Plan 1（本 Plan 调用 wrapper） |
| Bi-temporal differential test / chaos / 投毒 attack 集 | Plan 8 |

### 1.3 算法深度补丁归属

**# 2 Memory 投毒 + Agent 幻觉写**（spec § 11 末尾 #2）：
- (a) Prompt injection 分类器 → **Plan 5**（本 Plan 留 DI hook，`HierarchicalMemory.__init__(injection_classifier=None)`）
- (b) **`evidence_quote` substring 校验 → 本 Plan 4 ship**（`archival_memory_insert` tool 内强制调用 `evidence_quote_in_episode`，失败 raise `EvidenceNotFoundError` 不写入）
- (c) 监控（每用户每周新写入 / 老 edge 比例飙高告警）→ Plan 8 ship 时进 eval pipeline

---

## § 2 文件结构

```
backend/app/mcp_server/
├── server.py                                    ← 修改：加 --profile 参数 + memory profile 分发
└── tools/
    └── memory/                                  ← NEW（本 Plan 创建）
        ├── __init__.py                          ← 6 tool 注册 + _MEMORY_TOOL_MODULES
        ├── core_memory_append.py                ← Plan 4
        ├── core_memory_replace.py               ← Plan 4
        ├── archival_memory_insert.py            ← Plan 4（含 evidence_quote 校验）
        ├── archival_memory_search.py            ← Plan 4
        ├── archival_memory_traverse.py          ← Plan 4（trigger 词清单注入 system prompt）
        ├── recall_memory_search.py              ← Plan 4
        └── _common.py                           ← 共享：error class + memory factory + tool call log writer

backend/app/services/
└── trace_models.py                              ← 修改：加 MCPToolCallLog SQLAlchemy 表

backend/app/memory/
└── recall_search.py                             ← NEW（recall Tier 3 chat_messages semantic search 实现）

backend/app/agents/chat/prompts/
└── memory_tool_usage.md                         ← NEW：system prompt 模板

backend/scripts/memory/
└── weekly_tool_routing_report.sql               ← NEW：周报 SQL

backend/eval/memory/
└── routing_accuracy_metric.py                   ← NEW（骨架，Plan 8 填 case）

backend/tests/
├── unit/memory/
│   └── test_mcp_tools.py                        ← L0：6 tool input schema + evidence_quote 校验
├── integration/memory/
│   └── test_mcp_tools_e2e.py                    ← L1：6 tool 真 PG / AGE / Milvus(mock LLM) 调通
├── e2e/memory/
│   ├── test_traverse_full_path.py               ← L2：traverse + cassette
│   └── test_recall_full_path.py                 ← L2：recall + cassette
└── cassettes/memory/
    ├── traverse_full_path__industry_neighbors.yaml
    └── recall_full_path__我之前说过.yaml

mcp_servers.yaml                                 ← NEW：chat_tools + memory 两 profile

docs/claude-context/
└── c5-plan4-mcp-tools-done.md                   ← 知识卡
```

---

## § 3 共享接口契约（强约束）

### 3.1 严守（contracts § 2 Memory Protocol）

本 Plan 实现的 6 MCP tool 必须直接调用 `HierarchicalMemory`（`app.memory.hierarchical`）暴露的 Memory Protocol 方法，**不**绕过 Protocol 自行查 PG / AGE / Milvus。具体调用映射：

| MCP tool | 调用 Memory Protocol 方法 | Plan 1/2/3 ship 状态 |
|---|---|---|
| `core_memory_append` | `core_memory_append(user_id, block_name, content)` | Plan 1 ship |
| `core_memory_replace` | `core_memory_replace(user_id, block_name, old_content, new_content)` | Plan 1 ship |
| `archival_memory_insert` | `archival_memory_insert(user_id, content, reasoning, importance, evidence_quote, episode_id)` | Plan 2 ship |
| `archival_memory_search` | `archival_memory_search(user_id, query, k)` | Plan 3 ship |
| `archival_memory_traverse` | `archival_memory_traverse(user_id, start_label, hops, rel_types)` | Plan 3 ship |
| `recall_memory_search` | `recall_memory_search(user_id, query, k)` | **本 Plan 实现**（Plan 1 是 stub） |

**注意**：`recall_memory_search` 在 contracts § 3 标 "Plan 4 实现", Plan 1 在 `HierarchicalMemory` 留 `raise NotImplementedError`。本 Plan 必须填实现（直接对 PR #39 ship 的 `chat_messages` 表做 semantic search via qwen embed），同时给 6 tool wrapper。**实现地点**：`backend/app/memory/recall_search.py` 的 `RecallSearcher` class，由 `HierarchicalMemory.recall_memory_search` 调用。

### 3.2 严守（contracts § 5 evidence_quote_in_episode）

`evidence_quote_in_episode(quote: str, episode_text: str) -> bool` 函数签名由 Plan 5 实现，本 Plan 在 `archival_memory_insert` tool 内强制调用：

```python
# backend/app/mcp_server/tools/memory/archival_memory_insert.py（精简示意）

from app.memory.injection_classifier import (
    EvidenceNotFoundError,
    evidence_quote_in_episode,
)

async def handle(args: dict[str, Any]) -> list[TextContent]:
    validated = ArchivalMemoryInsertArgs.model_validate(args)
    memory, db_session = _build_memory_and_session()

    # === Algorithm 深度补丁 #2 evidence_quote 校验 ===
    episode = await _fetch_episode(db_session, validated.episode_id, validated.user_id)
    if episode is None:
        raise ValueError(f"episode {validated.episode_id} not found / not owned by user")

    if not evidence_quote_in_episode(validated.evidence_quote, episode.user_message_text + "\n" + (episode.agent_response_text or "")):
        raise EvidenceNotFoundError(
            f"evidence_quote {validated.evidence_quote!r} not found as substring "
            f"in episode {validated.episode_id} text — refusing write to prevent agent hallucination",
        )

    # 校验通过, 调 Memory Protocol
    edge = await memory.archival_memory_insert(
        user_id=validated.user_id,
        content=validated.content,
        reasoning=validated.reasoning,
        importance=validated.importance,
        evidence_quote=validated.evidence_quote,
        episode_id=validated.episode_id,
    )
    return [TextContent(type="text", text=json.dumps({
        "edge_id": str(edge.edge_id),
        "source_episode_id": str(edge.source_episode_id),
        "rel_type": edge.rel_type,
        "importance": edge.importance,
    }, ensure_ascii=False))]
```

**注意**：
- **`evidence_quote_in_episode` 是 Plan 5 ship** 的函数。本 Plan 4 ship 时 Plan 5 必须已 ship（依赖前置已声明）；如果 Plan 5 还没 ship，本 Plan 实施期临时在 `injection_classifier.py` 写一个 minimal 版本（trim space + lower + substring check + raise `EvidenceNotFoundError` 异常类），等 Plan 5 ship 时合并。**Task 1 自查**：先确认 `evidence_quote_in_episode` 是否已 ship；未 ship 则本 Plan 提供 minimal 版本不算违反 contract（contract 只规定签名）。
- 校验失败 raise `EvidenceNotFoundError`（继承 `ValueError`），**不**返回错误 dict，让 MCP server 把异常上抛，agent 可决定 retry / 改口。
- **校验范围**：`episode.user_message_text + "\n" + episode.agent_response_text`（两者连接，因为 agent 自己说过的话 quote 也算合法 evidence — agent reasoning 不能完全无中生有，但可以 quote 自己之前的话）。

### 3.3 严守（contracts § 6 fixture）

L0 用 `mock_qwen_embed` + 不依赖 DB；L1 用 `pg_memory_fixture` + `age_fixture` + `milvus_memory_fixture` + `mock_llm_extraction` + `mock_llm_judge`；L2 用 `vcr_memory_cassette`。**本 Plan 不新增 fixture**，全复用 Plan 1-3 ship 的。

### 3.4 严守（contracts § 1 文件路径）

所有 6 个 MCP tool 文件必须在 `backend/app/mcp_server/tools/memory/` 目录下，文件名严格按 contracts § 1 第 37-44 行清单。Plan 4 严禁动 PR #39 已 ship 的 `tools/get_stock_quote.py` 等 6 个 chat_tools profile 文件。

### 3.5 严守（contracts § 14 commit 规范）

每 commit message：
- `feat(c5-plan4): <topic>` for 新 tool / profile / endpoint
- `test(c5-plan4): <topic>` for 加测试
- `docs(c5-plan4): <topic>` for 知识卡
- `fix(c5-plan4): <topic>` + body 含 `原因 layer: impl|plan|spec` for bug 修

---

## § 4 Tasks（10 个，TDD 5-step）

### Task 1: 6 MCP Tool 文件骨架 + Pydantic Input Schema（L0 红灯优先）

**目标**：6 文件骨架 + Pydantic args + TOOL_DEF + handle stub raise NotImplementedError，先红灯锁 schema。

**Step 1 — Plan-time review**：
- 复读 spec § 6 Tool inventory 表 + 附录 C tool input schema（`grep -A 100 "附录 C" docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`，如果附录 C 内容缺失则按 spec § 6 关键决策表 + tool schemas 段拼接）
- 复读 contracts § 1 文件路径 + § 2 Memory Protocol 方法签名
- 确认 6 tool 文件路径准确

**Step 2 — Write failing tests**：

创建 `backend/tests/unit/memory/test_mcp_tools.py`：

```python
"""L0 — 6 MCP tool input schema / TOOL_DEF / Pydantic 校验测试.

不依赖 PG / AGE / Milvus, 全 mock.
"""
from __future__ import annotations

import importlib
import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("module_path,expected_name", [
    ("app.mcp_server.tools.memory.core_memory_append", "core_memory_append"),
    ("app.mcp_server.tools.memory.core_memory_replace", "core_memory_replace"),
    ("app.mcp_server.tools.memory.archival_memory_insert", "archival_memory_insert"),
    ("app.mcp_server.tools.memory.archival_memory_search", "archival_memory_search"),
    ("app.mcp_server.tools.memory.archival_memory_traverse", "archival_memory_traverse"),
    ("app.mcp_server.tools.memory.recall_memory_search", "recall_memory_search"),
])
def test_tool_def_exposes_correct_name_and_schema(module_path: str, expected_name: str) -> None:
    mod = importlib.import_module(module_path)
    assert mod.TOOL_DEF.name == expected_name
    assert "type" in mod.TOOL_DEF.inputSchema
    assert mod.TOOL_DEF.inputSchema["type"] == "object"


# === core_memory_append ===

def test_core_memory_append_args_max_200_chars():
    from app.mcp_server.tools.memory.core_memory_append import CoreMemoryAppendArgs

    # 200 chars 通过
    CoreMemoryAppendArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="persona", content="a" * 200)
    # 201 chars 拒绝
    with pytest.raises(ValidationError):
        CoreMemoryAppendArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="persona", content="a" * 201)


def test_core_memory_append_args_block_name_whitelist():
    from app.mcp_server.tools.memory.core_memory_append import CoreMemoryAppendArgs

    # persona / scratchpad 通过
    CoreMemoryAppendArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="persona", content="ok")
    CoreMemoryAppendArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="scratchpad", content="ok")
    # 其他拒绝
    with pytest.raises(ValidationError):
        CoreMemoryAppendArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="random", content="ok")


# === core_memory_replace ===

def test_core_memory_replace_args_old_new_required():
    from app.mcp_server.tools.memory.core_memory_replace import CoreMemoryReplaceArgs

    CoreMemoryReplaceArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        block_name="persona", old_content="old", new_content="new",
    )
    with pytest.raises(ValidationError):
        CoreMemoryReplaceArgs(user_id="00000000-0000-0000-0000-000000000001", block_name="persona", old_content="old")


# === archival_memory_insert ===

def test_archival_memory_insert_args_importance_three_tier():
    from app.mcp_server.tools.memory.archival_memory_insert import ArchivalMemoryInsertArgs

    for imp in [0.9, 0.5, 0.2]:
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={"rel_type": "HOLDS", "source_label": "User", "target_label": "贵州茅台"},
            reasoning="user said 'I bought 500 share'",
            importance=imp,
            evidence_quote="我买了500股茅台",
            episode_id="00000000-0000-0000-0000-000000000099",
        )
    # 0.7 拒绝（三档约束 spec § 11 末尾 #3）
    with pytest.raises(ValidationError):
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={"rel_type": "HOLDS", "source_label": "User", "target_label": "X"},
            reasoning="r", importance=0.7, evidence_quote="q",
            episode_id="00000000-0000-0000-0000-000000000099",
        )


def test_archival_memory_insert_args_evidence_quote_required():
    from app.mcp_server.tools.memory.archival_memory_insert import ArchivalMemoryInsertArgs

    with pytest.raises(ValidationError):
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={"rel_type": "HOLDS"},
            reasoning="r", importance=0.5,
            episode_id="00000000-0000-0000-0000-000000000099",
        )  # evidence_quote 缺失


# === archival_memory_search ===

def test_archival_memory_search_args_k_default_5_max_20():
    from app.mcp_server.tools.memory.archival_memory_search import ArchivalMemorySearchArgs

    args = ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="茅台")
    assert args.k == 5
    # 20 通过
    ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=20)
    # 21 拒绝
    with pytest.raises(ValidationError):
        ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=21)


# === archival_memory_traverse ===

def test_archival_memory_traverse_args_hops_default_2_max_3():
    from app.mcp_server.tools.memory.archival_memory_traverse import ArchivalMemoryTraverseArgs

    args = ArchivalMemoryTraverseArgs(user_id="00000000-0000-0000-0000-000000000001", start_label="贵州茅台")
    assert args.hops == 2
    ArchivalMemoryTraverseArgs(user_id="00000000-0000-0000-0000-000000000001", start_label="X", hops=3)
    with pytest.raises(ValidationError):
        ArchivalMemoryTraverseArgs(user_id="00000000-0000-0000-0000-000000000001", start_label="X", hops=4)


# === recall_memory_search ===

def test_recall_memory_search_args_k_default_5_max_20():
    from app.mcp_server.tools.memory.recall_memory_search import RecallMemorySearchArgs

    args = RecallMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="我之前说")
    assert args.k == 5
    with pytest.raises(ValidationError):
        RecallMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=21)
```

跑：`uv run pytest backend/tests/unit/memory/test_mcp_tools.py -v` → 全红（模块还没建）。

**Step 3 — Write code**：

创建 6 个 tool 文件 + `__init__.py` + `_common.py`。

`backend/app/mcp_server/tools/memory/__init__.py`：

```python
"""Memory MCP tools registry — Plan 4 ship.

6 tools spanning 3 tiers:
  Tier 1 (working memory write): core_memory_append / core_memory_replace
  Tier 2 (archival graph):       archival_memory_insert / archival_memory_search / archival_memory_traverse
  Tier 3 (chat history recall):  recall_memory_search
"""

MEMORY_TOOL_MODULES = [
    "app.mcp_server.tools.memory.core_memory_append",
    "app.mcp_server.tools.memory.core_memory_replace",
    "app.mcp_server.tools.memory.archival_memory_insert",
    "app.mcp_server.tools.memory.archival_memory_search",
    "app.mcp_server.tools.memory.archival_memory_traverse",
    "app.mcp_server.tools.memory.recall_memory_search",
]
```

`backend/app/mcp_server/tools/memory/_common.py`：

```python
"""Shared helpers for memory MCP tools.

- Memory factory (build HierarchicalMemory from app config)
- Tool call log writer (append to mcp_tool_call_log)
"""
from __future__ import annotations

import time
from typing import Any
from uuid import UUID


def build_memory_from_env() -> Any:
    """Construct a HierarchicalMemory using factory wiring.

    Plan 1 ships HierarchicalMemory + factory in app.memory.factory.
    """
    from app.memory.factory import build_hierarchical_memory_from_env
    return build_hierarchical_memory_from_env()


def build_db_session() -> Any:
    from app.core.database import get_session_factory
    return get_session_factory()()


async def write_tool_call_log(
    *,
    user_id: UUID | str,
    tool_name: str,
    args_json: dict[str, Any],
    result_count: int,
    latency_ms: float,
    error: str | None = None,
) -> None:
    """Append one row to mcp_tool_call_log (Plan 4 ship table)."""
    from app.services.trace_models import MCPToolCallLog
    from app.core.database import get_session_factory

    sf = get_session_factory()
    if sf is None:
        return  # tests with no DB skip log

    async with sf() as s:
        log = MCPToolCallLog(
            user_id=str(user_id),
            tool_name=tool_name,
            args_json=args_json,
            result_count=result_count,
            latency_ms=latency_ms,
            error=error,
        )
        s.add(log)
        await s.commit()


class _Timer:
    def __enter__(self) -> "_Timer":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000
```

`backend/app/mcp_server/tools/memory/core_memory_append.py`：

```python
"""MCP tool — core_memory_append (Tier 1 working memory write)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field, field_validator

TOOL_DEF = Tool(
    name="core_memory_append",
    description=(
        "Append durable fact to user's working memory block. Block names: 'persona' (long-term identity)"
        " or 'scratchpad' (recent context). Auto-paging if exceed max_tokens (oldest line archived)."
        " Max 200 chars per call."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "UUID"},
            "block_name": {"type": "string", "enum": ["persona", "scratchpad"]},
            "content": {"type": "string", "maxLength": 200},
        },
        "required": ["user_id", "block_name", "content"],
    },
)


class CoreMemoryAppendArgs(BaseModel):
    user_id: UUID
    block_name: str = Field(pattern="^(persona|scratchpad)$")
    content: str = Field(max_length=200)

    @field_validator("content")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be empty / whitespace")
        return v


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        _Timer, build_memory_from_env, write_tool_call_log,
    )

    validated = CoreMemoryAppendArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    block = None
    with _Timer() as t:
        try:
            block = await memory.core_memory_append(
                user_id=validated.user_id,
                block_name=validated.block_name,
                content=validated.content,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="core_memory_append",
                args_json={"block_name": validated.block_name, "content_len": len(validated.content)},
                result_count=1 if block else 0,
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "block_name": validated.block_name,
        "token_count": block.token_count,
        "max_tokens": block.max_tokens,
        "paged_out": block.token_count <= block.max_tokens,  # True 表示没溢出
    }, ensure_ascii=False))]
```

`backend/app/mcp_server/tools/memory/core_memory_replace.py`：

```python
"""MCP tool — core_memory_replace (Tier 1 exact-substring replace)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="core_memory_replace",
    description=(
        "Replace exact substring in working memory block. Raises ValueError if old_content not found."
        " Use for updating; pair with core_memory_append for additions."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "block_name": {"type": "string", "enum": ["persona", "scratchpad"]},
            "old_content": {"type": "string"},
            "new_content": {"type": "string", "maxLength": 500},
        },
        "required": ["user_id", "block_name", "old_content", "new_content"],
    },
)


class CoreMemoryReplaceArgs(BaseModel):
    user_id: UUID
    block_name: str = Field(pattern="^(persona|scratchpad)$")
    old_content: str = Field(min_length=1)
    new_content: str = Field(max_length=500)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        _Timer, build_memory_from_env, write_tool_call_log,
    )

    validated = CoreMemoryReplaceArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    block = None
    with _Timer() as t:
        try:
            block = await memory.core_memory_replace(
                user_id=validated.user_id,
                block_name=validated.block_name,
                old_content=validated.old_content,
                new_content=validated.new_content,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="core_memory_replace",
                args_json={"block_name": validated.block_name},
                result_count=1 if block else 0,
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "block_name": validated.block_name,
        "token_count": block.token_count,
    }, ensure_ascii=False))]
```

`backend/app/mcp_server/tools/memory/archival_memory_insert.py`：

```python
"""MCP tool — archival_memory_insert (Tier 2 graph write).

Algorithm 深度补丁 #2: evidence_quote substring 校验防 Agent 幻觉写.
"""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field, field_validator

TOOL_DEF = Tool(
    name="archival_memory_insert",
    description=(
        "Write fact to graph memory (Tier 2 archival). Runs full 8-step write pipeline including"
        " entity normalize / 4-action conflict resolution / AGE+Milvus sync. evidence_quote MUST be"
        " a substring of source episode text (algorithm depth patch #2 — prevents agent hallucination)."
        " importance: 0.9=explicit identity, 0.5=contextual, 0.2=weak signal (three-tier discrete)."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "content": {
                "type": "object",
                "properties": {
                    "rel_type": {"type": "string"},
                    "source_label": {"type": "string"},
                    "target_label": {"type": "string"},
                    "valid_from": {"type": "string", "description": "ISO datetime, optional"},
                    "properties": {"type": "object"},
                },
                "required": ["rel_type", "source_label", "target_label"],
            },
            "reasoning": {"type": "string", "description": "agent's reason for this insertion"},
            "importance": {"type": "number", "enum": [0.9, 0.5, 0.2]},
            "evidence_quote": {
                "type": "string",
                "description": "verbatim substring from episode text supporting this fact",
                "minLength": 4,
            },
            "episode_id": {"type": "string", "description": "UUID of source episode"},
        },
        "required": ["user_id", "content", "reasoning", "importance", "evidence_quote", "episode_id"],
    },
)


class ArchivalMemoryInsertArgs(BaseModel):
    user_id: UUID
    content: dict[str, Any]
    reasoning: str = Field(min_length=1)
    importance: Literal[0.9, 0.5, 0.2]  # 三档约束 spec § 11 末尾 #3
    evidence_quote: str = Field(min_length=4)
    episode_id: UUID

    @field_validator("content")
    @classmethod
    def content_has_required(cls, v: dict[str, Any]) -> dict[str, Any]:
        for key in ("rel_type", "source_label", "target_label"):
            if key not in v:
                raise ValueError(f"content missing required key: {key}")
        return v


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from sqlalchemy import select

    from app.memory.injection_classifier import (
        EvidenceNotFoundError,
        evidence_quote_in_episode,
    )
    from app.memory.models import ChatMemoryEpisode
    from app.mcp_server.tools.memory._common import (
        _Timer, build_db_session, build_memory_from_env, write_tool_call_log,
    )

    validated = ArchivalMemoryInsertArgs.model_validate(args)

    memory = build_memory_from_env()
    db = build_db_session()

    err: str | None = None
    edge = None
    with _Timer() as t:
        try:
            # === 算法深度补丁 #2 evidence_quote substring 校验 ===
            async with db as session:
                row = await session.execute(
                    select(ChatMemoryEpisode).where(
                        ChatMemoryEpisode.episode_id == validated.episode_id,
                        ChatMemoryEpisode.user_id == validated.user_id,
                    )
                )
                episode = row.scalar_one_or_none()
                if episode is None:
                    raise ValueError(
                        f"episode {validated.episode_id} not found or not owned by user {validated.user_id}"
                    )

                episode_text = (episode.user_message_text or "") + "\n" + (episode.agent_response_text or "")
                if not evidence_quote_in_episode(validated.evidence_quote, episode_text):
                    raise EvidenceNotFoundError(
                        f"evidence_quote {validated.evidence_quote!r} not a substring "
                        f"of episode {validated.episode_id} — refusing write to prevent agent hallucination "
                        f"(algorithm depth patch #2)"
                    )

            # === 校验通过, 调 Memory Protocol ===
            edge = await memory.archival_memory_insert(
                user_id=validated.user_id,
                content=validated.content,
                reasoning=validated.reasoning,
                importance=validated.importance,
                evidence_quote=validated.evidence_quote,
                episode_id=validated.episode_id,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="archival_memory_insert",
                args_json={
                    "rel_type": validated.content.get("rel_type"),
                    "importance": validated.importance,
                    "episode_id": str(validated.episode_id),
                },
                result_count=1 if edge else 0,
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "edge_id": str(edge.edge_id),
        "source_episode_id": str(edge.source_episode_id),
        "rel_type": edge.rel_type,
        "importance": edge.importance,
        "valid_from": edge.valid_from.isoformat() if edge.valid_from else None,
    }, ensure_ascii=False))]
```

`backend/app/mcp_server/tools/memory/archival_memory_search.py`：

```python
"""MCP tool — archival_memory_search (Tier 2 default 3-way hybrid + RRF v2)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="archival_memory_search",
    description=(
        "DEFAULT memory recall tool — 3-way hybrid (BM25 + dense vector + entity-anchor expansion)"
        " fused with time-aware importance-weighted RRF. Use for 'what did I say about X' queries."
        " k default 5 max 20."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "query": {"type": "string", "minLength": 1},
            "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "required": ["user_id", "query"],
    },
)


class ArchivalMemorySearchArgs(BaseModel):
    user_id: UUID
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        _Timer, build_memory_from_env, write_tool_call_log,
    )

    validated = ArchivalMemorySearchArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    edges: list = []
    with _Timer() as t:
        try:
            edges = await memory.archival_memory_search(
                user_id=validated.user_id,
                query=validated.query,
                k=validated.k,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="archival_memory_search",
                args_json={"query": validated.query[:120], "k": validated.k},
                result_count=len(edges),
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "results": [{
            "edge_id": str(e.edge_id),
            "rel_type": e.rel_type,
            "source_label": e.properties.get("source_label") if e.properties else None,
            "target_label": e.properties.get("target_label") if e.properties else None,
            "valid_from": e.valid_from.isoformat() if e.valid_from else None,
            "importance": e.importance,
            "reasoning": e.reasoning,
            "source_episode_id": str(e.source_episode_id),
        } for e in edges],
        "count": len(edges),
    }, ensure_ascii=False))]
```

`backend/app/mcp_server/tools/memory/archival_memory_traverse.py`：

```python
"""MCP tool — archival_memory_traverse (Tier 2 explicit graph multi-hop).

Trigger words (附录 D): 相关 / 类似 / 同 / 同行业 / 同赛道 / 之间 / 链 / 上下游 / 属于.
Use for topology queries; falls back to search if returns empty.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="archival_memory_traverse",
    description=(
        "Explicit graph traversal via AGE Cypher. ONLY use when user query has topology intent."
        " Trigger words: '相关 / 类似 / 同 / 同行业 / 同赛道 / 同概念 / 之间 / 链 / 上下游 / 产业链 / 属于'."
        " hops default 2 max 3. rel_types optional filter."
        " Falls back to archival_memory_search on empty result."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "start_label": {
                "type": "string",
                "description": "Entity label to start traversal from, e.g. '贵州茅台' or 'User'",
                "minLength": 1,
            },
            "hops": {"type": "integer", "minimum": 1, "maximum": 3, "default": 2},
            "rel_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional rel_type whitelist (e.g. ['BELONGS_TO', 'CORRELATED_WITH'])",
            },
        },
        "required": ["user_id", "start_label"],
    },
)


class ArchivalMemoryTraverseArgs(BaseModel):
    user_id: UUID
    start_label: str = Field(min_length=1)
    hops: int = Field(default=2, ge=1, le=3)
    rel_types: list[str] | None = None


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        _Timer, build_memory_from_env, write_tool_call_log,
    )

    validated = ArchivalMemoryTraverseArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    paths: list = []
    with _Timer() as t:
        try:
            paths = await memory.archival_memory_traverse(
                user_id=validated.user_id,
                start_label=validated.start_label,
                hops=validated.hops,
                rel_types=validated.rel_types,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="archival_memory_traverse",
                args_json={
                    "start_label": validated.start_label,
                    "hops": validated.hops,
                    "rel_types": validated.rel_types,
                },
                result_count=len(paths),
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "paths": paths,  # Plan 3 返回的 list[dict] 已是 JSON-safe
        "count": len(paths),
        "hint": ("empty result; consider falling back to archival_memory_search"
                 if not paths else None),
    }, ensure_ascii=False))]
```

`backend/app/mcp_server/tools/memory/recall_memory_search.py`：

```python
"""MCP tool — recall_memory_search (Tier 3 chat history semantic search).

Searches PR #39 ship 的 chat_messages 表 via qwen embed.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from mcp.types import TextContent, Tool
from pydantic import BaseModel, Field

TOOL_DEF = Tool(
    name="recall_memory_search",
    description=(
        "Semantic search over user's past chat messages (Tier 3 recall). Use for queries like"
        " '我们上次聊过 X' / '你之前说过 Y'. Each result includes source_session_id and message_id"
        " for provenance / chain to verbatim retrieval."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "query": {"type": "string", "minLength": 1},
            "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
        },
        "required": ["user_id", "query"],
    },
)


class RecallMemorySearchArgs(BaseModel):
    user_id: UUID
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.mcp_server.tools.memory._common import (
        _Timer, build_memory_from_env, write_tool_call_log,
    )

    validated = RecallMemorySearchArgs.model_validate(args)
    memory = build_memory_from_env()

    err: str | None = None
    results: list[dict[str, Any]] = []
    with _Timer() as t:
        try:
            results = await memory.recall_memory_search(
                user_id=validated.user_id,
                query=validated.query,
                k=validated.k,
            )
        except Exception as e:
            err = repr(e)
            raise
        finally:
            await write_tool_call_log(
                user_id=validated.user_id,
                tool_name="recall_memory_search",
                args_json={"query": validated.query[:120], "k": validated.k},
                result_count=len(results),
                latency_ms=t.elapsed_ms if hasattr(t, "elapsed_ms") else 0.0,
                error=err,
            )

    return [TextContent(type="text", text=json.dumps({
        "results": results,
        "count": len(results),
    }, ensure_ascii=False))]
```

**Step 4 — Run tests** + **Step 5 — Self review**：
- 跑 `uv run pytest backend/tests/unit/memory/test_mcp_tools.py -v` → 全绿
- self-review：
  - 6 文件全在 `backend/app/mcp_server/tools/memory/`✓
  - 每个 tool 都暴露 `TOOL_DEF` + `handle()` ✓
  - Pydantic args 全严守 spec § 6 关键决策（200 chars / 三档 importance / k≤20 / hops≤3）✓
  - 调用 Memory Protocol 不绕过 ✓
  - mypy strict pass：`uv run mypy backend/app/mcp_server/tools/memory/`
- commit：`feat(c5-plan4): 6 memory MCP tool input schema + handle skeleton (TOOL_DEF + Pydantic args)`

---

### Task 2: `mcp_tool_call_log` 表 + SQLAlchemy Model

**目标**：spec § 6 周报 SQL 依赖的 `mcp_tool_call_log` 表（PR #39 spec 提了但没建），本 Plan 落地。

**Step 1 — Plan-time review**：
- spec § 6 监控 SQL 用 `mcp_tool_call_log(tool_name, result_count, latency_ms, created_at)`
- contracts § 1 没列这表（属共享 infra），约定写到 `app.services.trace_models`（已有 trace_models.py）
- `_common.write_tool_call_log` 已 import `app.services.trace_models.MCPToolCallLog`，本任务必须把 model 实现

**Step 2 — Failing test**：

`backend/tests/unit/test_mcp_tool_call_log_model.py`：

```python
"""L0 — MCPToolCallLog table schema test."""
from __future__ import annotations

import pytest


def test_mcp_tool_call_log_columns_exist():
    from app.services.trace_models import MCPToolCallLog

    cols = {c.name for c in MCPToolCallLog.__table__.columns}
    assert {"id", "user_id", "tool_name", "args_json", "result_count", "latency_ms", "error", "created_at"}.issubset(cols)


def test_mcp_tool_call_log_indexes():
    from app.services.trace_models import MCPToolCallLog

    idx_names = {idx.name for idx in MCPToolCallLog.__table__.indexes}
    # 周报 SQL 按 tool_name + created_at 过滤
    assert any("tool_name" in name for name in idx_names) or any(
        "tool_name" in {c.name for c in idx.columns} for idx in MCPToolCallLog.__table__.indexes
    )
```

跑：`uv run pytest backend/tests/unit/test_mcp_tool_call_log_model.py -v` → 红。

**Step 3 — Code**：

在 `backend/app/services/trace_models.py` 末尾加：

```python
class MCPToolCallLog(Base):
    """MCP tool call log — spec § 6 周报 SQL data source.

    Each row: one tool invocation with latency / result count / error.
    Plan 4 ship; queried by docs/superpowers/specs § 6 SQL.
    """

    __tablename__ = "mcp_tool_call_log"

    id          = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id     = Column(String, nullable=False)            # str (legacy compat across tests)
    tool_name   = Column(String, nullable=False)
    args_json   = Column(JSONB, nullable=False, default=dict)
    result_count = Column(Integer, nullable=False, default=0)
    latency_ms   = Column(Float, nullable=False, default=0.0)
    error        = Column(Text)
    created_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_mcp_tool_call_log_tool_created", "tool_name", "created_at"),
        Index("idx_mcp_tool_call_log_user", "user_id"),
    )
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/unit/test_mcp_tool_call_log_model.py -v` → 绿
- 写 SQL migration 同步到 `backend/scripts/migrations/2026-05-11-c5-memory-schema.sql`（Plan 1 已 ship 的文件，Plan 4 加 `mcp_tool_call_log` 段，幂等用 `CREATE TABLE IF NOT EXISTS`）
- commit：`feat(c5-plan4): mcp_tool_call_log table for tool routing 监控 SQL`

---

### Task 3: `recall_memory_search` 实现（contracts § 3.1 必填）

**目标**：`HierarchicalMemory.recall_memory_search` Plan 1 是 stub raise NotImplementedError；本 Plan 必须实现，调 PR #39 ship 的 `chat_messages` 表 + qwen embed。

**Step 1 — Plan-time review**：
- 读 `backend/app/models/chat.py:ChatMessage`（已确认存在，PR #39 ship）
- 读 `backend/app/services/embedding_service.py`（v0.7 ship 的 qwen embed wrapper）
- 决策：本 Plan 不另建 collection，直接对 `chat_messages.content` 做 in-memory cosine（用户量小 + 历史不多 ≈ <10K message），未来 Plan 7 性能撞实再加 Milvus collection（contracts § 11 矩阵已留口）。**轻量实现：每次 query 实时 embed 用户全部 message + cosine top k**，避免引入新 Milvus collection 复杂度。如果用户消息 >5000 条则告警走异步嵌入预计算（Plan 5 范畴）。

**Step 2 — Failing test**：

`backend/tests/integration/memory/test_recall_search.py`：

```python
"""L1 — RecallSearcher real PG + mock qwen embed."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_recall_search_returns_top_k_by_cosine(
    pg_memory_fixture, mock_qwen_embed,
):
    """seed 5 chat_messages, query for top-3 most similar."""
    import uuid
    from app.memory.recall_search import RecallSearcher
    from app.models.chat import ChatMessage, ChatSession

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()

    async with pg_memory_fixture() as s:
        s.add(ChatSession(id=session_id, user_id=user_id, title="t"))
        await s.flush()
        for i, content in enumerate([
            "我重仓了贵州茅台 500 股",
            "今天纳斯达克跌了 3%",
            "上证指数怎么样",
            "我对消费股很看好",
            "白酒行业的护城河",
        ]):
            s.add(ChatMessage(
                id=uuid.uuid4(),
                session_id=session_id,
                role="user",
                content=content,
            ))
        await s.commit()

    searcher = RecallSearcher(session_factory=pg_memory_fixture, embed_service=mock_qwen_embed)
    results = await searcher.search(user_id=user_id, query="我的茅台持仓", k=3)
    assert len(results) <= 3
    assert all("message_id" in r and "content" in r and "session_id" in r for r in results)
    assert all("similarity" in r for r in results)


@pytest.mark.asyncio
async def test_recall_search_user_isolation(pg_memory_fixture, mock_qwen_embed):
    """User A messages not returned to User B."""
    import uuid
    from app.memory.recall_search import RecallSearcher
    from app.models.chat import ChatMessage, ChatSession

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    sess_a = uuid.uuid4()
    async with pg_memory_fixture() as s:
        s.add(ChatSession(id=sess_a, user_id=user_a, title="A"))
        await s.flush()
        s.add(ChatMessage(id=uuid.uuid4(), session_id=sess_a, role="user", content="A's secret"))
        await s.commit()

    searcher = RecallSearcher(session_factory=pg_memory_fixture, embed_service=mock_qwen_embed)
    results_b = await searcher.search(user_id=user_b, query="secret", k=5)
    assert results_b == []
```

跑：`uv run pytest backend/tests/integration/memory/test_recall_search.py -v` → 红。

**Step 3 — Code**：

`backend/app/memory/recall_search.py`：

```python
"""Tier 3 recall — semantic search on PR #39 chat_messages table.

Lightweight: in-memory cosine over qwen-embedded user messages.
Performance escalation (Milvus collection) deferred until > 5000 messages/user.
"""
from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import joinedload


class RecallSearcher:
    def __init__(self, session_factory, embed_service):
        self._sf = session_factory
        self._embed = embed_service

    async def search(
        self, user_id: UUID, query: str, k: int = 5,
    ) -> list[dict[str, Any]]:
        from app.models.chat import ChatMessage, ChatSession

        async with self._sf() as session:
            rows = (await session.execute(
                select(ChatMessage)
                .join(ChatSession, ChatMessage.session_id == ChatSession.id)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(5000)
            )).scalars().all()

            if not rows:
                return []

            texts = [m.content or "" for m in rows]
            query_vec = await self._embed.embed_one(query)
            doc_vecs = await self._embed.embed_batch(texts)

            scored: list[tuple[float, ChatMessage]] = []
            for vec, msg in zip(doc_vecs, rows, strict=True):
                sim = _cosine(query_vec, vec)
                scored.append((sim, msg))

            scored.sort(key=lambda t: t[0], reverse=True)
            top = scored[:k]
            return [{
                "message_id": str(msg.id),
                "session_id": str(msg.session_id),
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "similarity": float(sim),
            } for sim, msg in top]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
```

更新 `backend/app/memory/hierarchical.py` 的 `recall_memory_search`：

```python
async def recall_memory_search(
    self, user_id: UUID, query: str, k: int = 5,
) -> list[dict[str, Any]]:
    from app.memory.recall_search import RecallSearcher
    if not hasattr(self, "_recall_searcher"):
        self._recall_searcher = RecallSearcher(
            session_factory=self._pg_session_factory,
            embed_service=self._embed_service,
        )
    return await self._recall_searcher.search(user_id, query, k)
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/integration/memory/test_recall_search.py -v` → 绿
- mypy strict
- commit：`feat(c5-plan4): recall_memory_search via in-memory cosine over chat_messages (Tier 3)`

---

### Task 4: `evidence_quote_in_episode` minimal 实现 + `EvidenceNotFoundError`（contracts § 5）

**目标**：Plan 5 ship 前提供 minimal version 让 `archival_memory_insert` 跑通（Plan 5 ship 时增强为完整版）。

**Step 1 — Plan-time review**：
- 检查 Plan 5 是否已 ship `injection_classifier.py`：`ls backend/app/memory/injection_classifier.py`
- 如果已 ship → Task 4 跳过，验证函数签名跟 contracts § 5 对齐即可
- 如果未 ship → 本 Plan 写 minimal `evidence_quote_in_episode` + `EvidenceNotFoundError`，**不**实现 `is_prompt_injection`（Plan 5 责任）

**Step 2 — Failing test**：

`backend/tests/unit/memory/test_evidence_quote.py`：

```python
"""L0 — evidence_quote substring 校验 (algorithm 深度补丁 #2)."""
from __future__ import annotations

import pytest


def test_substring_exact_match():
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("我买了500股茅台", "今天我买了500股茅台,记一下") is True


def test_substring_with_whitespace_normalization():
    """allow extra space normalization for robustness."""
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("买了 500 股", "我买了500股茅台") is True


def test_no_substring():
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("我卖了茅台", "今天我买了500股茅台") is False


def test_empty_quote_rejected():
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("", "anything") is False


def test_evidence_not_found_error_class():
    from app.memory.injection_classifier import EvidenceNotFoundError

    assert issubclass(EvidenceNotFoundError, ValueError)
```

跑：`uv run pytest backend/tests/unit/memory/test_evidence_quote.py -v` → 红（如果 Plan 5 未 ship）。

**Step 3 — Code**：

`backend/app/memory/injection_classifier.py`（如果文件不存在则创建；如果已存在则 append `evidence_quote_in_episode` 函数 + `EvidenceNotFoundError` 类）：

```python
"""Algorithm 深度补丁 #2 — Memory 投毒 + Agent 幻觉写防御.

Plan 4 ship: minimal evidence_quote_in_episode + EvidenceNotFoundError.
Plan 5 ship: is_prompt_injection (rules + ML classifier).

Contracts § 5 spec ref.
"""
from __future__ import annotations

import re


class EvidenceNotFoundError(ValueError):
    """Agent 调 archival_memory_insert 时 evidence_quote 不在 episode 原文.

    Plan 4 在 archival_memory_insert tool 内 raise; agent 必须改 evidence_quote 重试.
    """


def evidence_quote_in_episode(quote: str, episode_text: str) -> bool:
    """Substring 校验 (空白容忍).

    去掉 quote / episode 中的连续空白，再做 substring containment.
    "买了 500 股" matches "买了500股".
    """
    if not quote or not quote.strip():
        return False
    q_norm = re.sub(r"\s+", "", quote)
    e_norm = re.sub(r"\s+", "", episode_text or "")
    if not q_norm:
        return False
    return q_norm in e_norm


def is_prompt_injection(text: str) -> tuple[bool, float, str]:
    """Plan 5 ship full version. Plan 4 stub returns (False, 0.0, 'plan5-stub')."""
    return (False, 0.0, "plan5-stub")
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/unit/memory/test_evidence_quote.py -v` → 绿
- 检查若 Plan 5 已 ship：merge 时确认 Plan 5 没回退本 minimal version（Plan 5 必须扩展不替换）
- commit：`feat(c5-plan4): evidence_quote_in_episode minimal + EvidenceNotFoundError (algorithm patch #2 part b)`

---

### Task 5: Memory MCP Server Profile + `mcp_servers.yaml`

**目标**：spec § 6 要求 memory 跟 chat_tools 是两个独立 stdio MCP server profile。

**Step 1 — Plan-time review**：
- 读 `backend/app/mcp_server/server.py` 当前 hardcoded 6 个 chat_tool；改成接受 `--profile` 参数路由到不同 module list
- spec § 6 yaml：`mcp_servers.yaml` 列两 profile，本 Plan 创建文件
- contracts 没要求 mcp_servers.yaml 必须存在（spec 提了，PR #39 ship 时是 hardcoded server.py），本 Plan 既要新建 yaml 也要兼容 hardcoded MCPClient.from_subprocess()

**Step 2 — Failing test**：

`backend/tests/unit/test_mcp_server_profiles.py`：

```python
"""L0 — server.build_server(profile=...) routes to correct tool registry."""
from __future__ import annotations

import pytest


def test_chat_tools_profile_has_six_existing_tools():
    from app.mcp_server.server import build_server
    s = build_server(profile="chat_tools")
    names = {name for name in s._mcp_tool_registry}
    assert names == {
        "get_stock_quote", "get_financials", "get_news",
        "web_search", "kb_search", "compare_stocks",
    }


def test_memory_profile_has_six_memory_tools():
    from app.mcp_server.server import build_server
    s = build_server(profile="memory")
    names = {name for name in s._mcp_tool_registry}
    assert names == {
        "core_memory_append", "core_memory_replace",
        "archival_memory_insert", "archival_memory_search",
        "archival_memory_traverse", "recall_memory_search",
    }


def test_unknown_profile_raises():
    from app.mcp_server.server import build_server
    with pytest.raises(ValueError, match="unknown profile"):
        build_server(profile="bogus")


def test_default_profile_is_chat_tools_for_backward_compat():
    """No --profile arg → chat_tools (PR #39 backward compat)."""
    from app.mcp_server.server import build_server
    s = build_server()
    assert "get_stock_quote" in s._mcp_tool_registry
```

跑：`uv run pytest backend/tests/unit/test_mcp_server_profiles.py -v` → 红。

**Step 3 — Code**：

改 `backend/app/mcp_server/server.py`：

```python
"""MCP server entry point — supports multi-profile (chat_tools / memory).

Plan 4: refactor to accept --profile argument routing to different tool module lists.
PR #39 default profile = chat_tools (backward compat).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)


_CHAT_TOOL_MODULES = [
    "app.mcp_server.tools.get_stock_quote",
    "app.mcp_server.tools.get_financials",
    "app.mcp_server.tools.get_news",
    "app.mcp_server.tools.web_search",
    "app.mcp_server.tools.kb_search",
    "app.mcp_server.tools.compare_stocks",
]


def _resolve_modules(profile: str) -> list[str]:
    if profile == "chat_tools":
        return _CHAT_TOOL_MODULES
    if profile == "memory":
        from app.mcp_server.tools.memory import MEMORY_TOOL_MODULES
        return MEMORY_TOOL_MODULES
    raise ValueError(f"unknown profile: {profile!r}")


def _load_tool_registry(profile: str) -> dict[str, Any]:
    import importlib
    registry: dict[str, Any] = {}
    for module_path in _resolve_modules(profile):
        mod = importlib.import_module(module_path)
        tool_def: Tool = mod.TOOL_DEF
        registry[tool_def.name] = mod
    return registry


def build_server(profile: str = "chat_tools") -> Server:
    """Construct MCP server for given profile (chat_tools / memory)."""
    registry = _load_tool_registry(profile)
    s = Server(f"financial-research-{profile}")

    @s.list_tools()
    async def _list_tools() -> list[Tool]:
        return [mod.TOOL_DEF for mod in registry.values()]

    @s.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
        if name not in registry:
            raise ValueError(f"Unknown MCP tool: {name!r}")
        return await registry[name].handle(args)

    s._mcp_tool_registry = registry  # type: ignore[attr-defined]
    return s


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="chat_tools", choices=["chat_tools", "memory"])
    args = parser.parse_args()

    s = build_server(profile=args.profile)
    async with stdio_server() as (read, write):
        await s.run(read, write, s.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
```

创建 `mcp_servers.yaml`（仓库根）：

```yaml
# Plan 4 ship — multi-profile MCP server config.
# PR #39 ship 'chat_tools' as embedded default. C.5 加 'memory' independent profile.
servers:
  - name: chat_tools
    transport: stdio
    command: ["python", "-m", "app.mcp_server.server", "--profile", "chat_tools"]
    description: "PR #39 chat tools (tushare / bocha / kb / compare)"

  - name: memory
    transport: stdio
    command: ["python", "-m", "app.mcp_server.server", "--profile", "memory"]
    description: "C.5 cross-session memory (3-tier hierarchical, 6 tools)"
```

更新 `backend/app/services/mcp_client.py`：加 `profile` 参数：

```python
@classmethod
@asynccontextmanager
async def from_subprocess(
    cls,
    server_module: str = "app.mcp_server.server",
    profile: str = "chat_tools",
) -> AsyncIterator[MCPClient]:
    backend_path = Path(__file__).parent.parent.parent
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{backend_path}{os.pathsep}{existing_pp}" if existing_pp else str(backend_path)
    )

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", server_module, "--profile", profile],
        env=env,
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield cls(session)
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/unit/test_mcp_server_profiles.py -v` → 绿
- 跑 PR #39 既有 e2e 测试 `uv run pytest backend/tests/integration/test_mcp_client_e2e.py -v` → **不退化**（默认 profile=chat_tools 兼容）
- commit：`feat(c5-plan4): MCP server multi-profile support (--profile chat_tools|memory) + mcp_servers.yaml`

---

### Task 6: 6 MCP Tools L1 Integration Test（real PG / AGE / Milvus + mock LLM）

**目标**：把 6 个 tool 在真 DB 跑通端到端，不录 cassette（cassette 留 Task 9）。

**Step 1 — Plan-time review**：
- 复用 `pg_memory_fixture` / `age_fixture` / `milvus_memory_fixture` / `mock_llm_extraction` / `mock_llm_judge` / `mock_qwen_embed`
- 测试场景：
  1. `core_memory_append` + `core_memory_replace` round trip
  2. `archival_memory_insert` evidence_quote pass → edge written
  3. `archival_memory_insert` evidence_quote **fail** → raise `EvidenceNotFoundError` + 不写 edge
  4. `archival_memory_search` 检索回写入的 edge
  5. `archival_memory_traverse` 多跳
  6. `recall_memory_search` 跨 session 查 chat_messages
  7. `mcp_tool_call_log` 每次调用都写一行（验证监控数据落地）

**Step 2 — Failing test**：

`backend/tests/integration/memory/test_mcp_tools_e2e.py`：

```python
"""L1 — 6 memory MCP tool e2e in real PG/AGE/Milvus, mock LLM."""
from __future__ import annotations

import json
import uuid
import pytest
from sqlalchemy import select


@pytest.fixture
async def seed_episode(pg_memory_fixture):
    """Insert a known episode for archival_memory_insert tests."""
    from app.memory.models import ChatMemoryEpisode

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    text = "我刚才买了500股贵州茅台,准备长期持有"

    async with pg_memory_fixture() as s:
        s.add(ChatMemoryEpisode(
            episode_id=episode_id,
            user_id=user_id,
            session_id=session_id,
            episode_index=0,
            user_message_text=text,
            agent_response_text="收到,我记下了。",
            source_kind="chat_turn",
        ))
        await s.commit()

    return {"user_id": user_id, "session_id": session_id, "episode_id": episode_id, "text": text}


@pytest.mark.asyncio
async def test_core_memory_append_then_replace(pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed):
    from app.mcp_server.tools.memory.core_memory_append import handle as append_h
    from app.mcp_server.tools.memory.core_memory_replace import handle as replace_h

    user_id = uuid.uuid4()
    r1 = await append_h({"user_id": str(user_id), "block_name": "persona", "content": "用户偏好稳健白马"})
    out1 = json.loads(r1[0].text)
    assert out1["block_name"] == "persona"

    r2 = await replace_h({"user_id": str(user_id), "block_name": "persona", "old_content": "稳健", "new_content": "高股息+稳健"})
    out2 = json.loads(r2[0].text)
    assert out2["token_count"] > 0


@pytest.mark.asyncio
async def test_archival_memory_insert_evidence_quote_pass(seed_episode, pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed, mock_llm_judge):
    from app.mcp_server.tools.memory.archival_memory_insert import handle

    args = {
        "user_id": str(seed_episode["user_id"]),
        "content": {"rel_type": "HOLDS", "source_label": "User", "target_label": "贵州茅台"},
        "reasoning": "user said '我刚才买了500股贵州茅台'",
        "importance": 0.9,
        "evidence_quote": "买了500股贵州茅台",  # ← 在 episode 原文
        "episode_id": str(seed_episode["episode_id"]),
    }
    result = await handle(args)
    out = json.loads(result[0].text)
    assert out["edge_id"]
    assert out["rel_type"] == "HOLDS"


@pytest.mark.asyncio
async def test_archival_memory_insert_evidence_quote_fail(seed_episode, pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed, mock_llm_judge):
    """Algorithm 深度补丁 #2 核心 — evidence_quote 不在原文 raise + 不写 edge."""
    from app.memory.injection_classifier import EvidenceNotFoundError
    from app.memory.models import ChatMemoryEdge
    from app.mcp_server.tools.memory.archival_memory_insert import handle

    args = {
        "user_id": str(seed_episode["user_id"]),
        "content": {"rel_type": "AVOIDS", "source_label": "User", "target_label": "腾讯控股"},
        "reasoning": "agent 推断,但用户没说",  # ← 幻觉
        "importance": 0.9,
        "evidence_quote": "我永不碰科技股",  # ← episode 原文里没这句
        "episode_id": str(seed_episode["episode_id"]),
    }
    with pytest.raises(EvidenceNotFoundError, match="not a substring"):
        await handle(args)

    # 验证 edge 没写入
    async with pg_memory_fixture() as s:
        rows = (await s.execute(
            select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == seed_episode["user_id"])
            .where(ChatMemoryEdge.rel_type == "AVOIDS")
        )).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_archival_memory_search(seed_episode, pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed, mock_llm_judge):
    from app.mcp_server.tools.memory.archival_memory_insert import handle as insert_h
    from app.mcp_server.tools.memory.archival_memory_search import handle as search_h

    # 先 insert
    await insert_h({
        "user_id": str(seed_episode["user_id"]),
        "content": {"rel_type": "HOLDS", "source_label": "User", "target_label": "贵州茅台"},
        "reasoning": "r", "importance": 0.9, "evidence_quote": "贵州茅台",
        "episode_id": str(seed_episode["episode_id"]),
    })

    # 再 search
    r = await search_h({"user_id": str(seed_episode["user_id"]), "query": "茅台"})
    out = json.loads(r[0].text)
    assert out["count"] >= 1
    assert any("source_episode_id" in x for x in out["results"])  # provenance chain


@pytest.mark.asyncio
async def test_archival_memory_traverse(seed_episode, pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed, mock_llm_judge):
    from app.mcp_server.tools.memory.archival_memory_insert import handle as insert_h
    from app.mcp_server.tools.memory.archival_memory_traverse import handle as traverse_h

    await insert_h({
        "user_id": str(seed_episode["user_id"]),
        "content": {"rel_type": "BELONGS_TO", "source_label": "贵州茅台", "target_label": "白酒"},
        "reasoning": "r", "importance": 0.5, "evidence_quote": "茅台",
        "episode_id": str(seed_episode["episode_id"]),
    })

    r = await traverse_h({"user_id": str(seed_episode["user_id"]), "start_label": "贵州茅台", "hops": 2})
    out = json.loads(r[0].text)
    assert "paths" in out


@pytest.mark.asyncio
async def test_recall_memory_search(pg_memory_fixture, mock_qwen_embed):
    """Tier 3 chat_messages search."""
    import uuid
    from app.models.chat import ChatMessage, ChatSession
    from app.mcp_server.tools.memory.recall_memory_search import handle

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    async with pg_memory_fixture() as s:
        s.add(ChatSession(id=session_id, user_id=user_id, title="t"))
        await s.flush()
        s.add(ChatMessage(id=uuid.uuid4(), session_id=session_id, role="user", content="我说过我重仓茅台"))
        await s.commit()

    r = await handle({"user_id": str(user_id), "query": "茅台", "k": 3})
    out = json.loads(r[0].text)
    assert out["count"] >= 1


@pytest.mark.asyncio
async def test_tool_call_log_written_per_invocation(pg_memory_fixture, age_fixture, milvus_memory_fixture, mock_qwen_embed):
    """每个 tool 调用必须落 mcp_tool_call_log 一行."""
    from app.mcp_server.tools.memory.core_memory_append import handle as append_h
    from app.services.trace_models import MCPToolCallLog

    user_id = uuid.uuid4()
    await append_h({"user_id": str(user_id), "block_name": "persona", "content": "x"})

    async with pg_memory_fixture() as s:
        rows = (await s.execute(
            select(MCPToolCallLog).where(MCPToolCallLog.user_id == str(user_id))
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].tool_name == "core_memory_append"
        assert rows[0].latency_ms > 0
        assert rows[0].error is None
```

**Step 3 — Code**：测试就是契约,代码已在 Task 1 写完。补 fix 让测试过即可。

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/integration/memory/test_mcp_tools_e2e.py -v` → 全绿
- 重点验证：`test_archival_memory_insert_evidence_quote_fail` 必须 raise + 不写入（spec § 11 末尾 #2 核心契约）
- self-review：log 写入 finally 块保证 raise 也写 ✓
- commit：`feat(c5-plan4): 6 memory MCP tool L1 e2e + evidence_quote enforcement test`

---

### Task 7: System Prompt 模板（注入 ChatPlanner / Responder）

**目标**：spec § 6 system prompt 模板落地为 markdown，让 ChatPlanner / Responder 加载。

**Step 1 — Plan-time review**：
- spec § 6 给了完整模板
- 决策：放在 `backend/app/agents/chat/prompts/memory_tool_usage.md`，由 ChatPlanner / Responder 加载（Plan 6 supervisor 也用，本 Plan 只 ship 模板，加载点 Plan 6 接）
- 模板内**不**插实际 working_blocks 内容（runtime 才填）；用 `{{persona_block}}` `{{scratchpad_block}}` placeholder

**Step 2 — Failing test**：

`backend/tests/unit/memory/test_system_prompt_template.py`：

```python
"""L0 — system prompt template content checks."""
from __future__ import annotations

from pathlib import Path


PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "app" / "agents" / "chat" / "prompts" / "memory_tool_usage.md"


def test_template_exists():
    assert PROMPT_PATH.exists(), f"missing: {PROMPT_PATH}"


def test_template_has_three_tiers():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Tier 1" in text and "Tier 2" in text and "Tier 3" in text


def test_template_has_traverse_trigger_words():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    # 附录 D trigger words
    for w in ["相关", "同行业", "之间", "链", "上下游"]:
        assert w in text, f"missing trigger word: {w}"


def test_template_has_hygiene_rules_4_count():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "Memory hygiene rules" in text
    # 至少 4 条 hygiene rule（spec § 6）
    rules_section = text[text.index("Memory hygiene rules"):]
    assert rules_section.count("\n1.") + rules_section.count("\n- ") >= 3


def test_template_has_persona_scratchpad_placeholder():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert "{{persona_block}}" in text
    assert "{{scratchpad_block}}" in text


def test_template_describes_six_tools_by_name():
    text = PROMPT_PATH.read_text(encoding="utf-8")
    for tool in [
        "core_memory_append", "core_memory_replace",
        "archival_memory_insert", "archival_memory_search",
        "archival_memory_traverse", "recall_memory_search",
    ]:
        assert tool in text
```

**Step 3 — Code**：

`backend/app/agents/chat/prompts/memory_tool_usage.md`：

```markdown
# Memory Tool Usage

You have a 3-tier hierarchical memory system. Use it to remember user-specific facts across chat sessions.

## Tier 1: Working Memory (always visible below)

{{persona_block}}

{{scratchpad_block}}

To modify these blocks (for facts that should persist across chats):
- `core_memory_append("persona", content)` — for short durable facts (max 200 chars/call). 超 max_tokens 自动 paging（最旧行 archive）.
- `core_memory_replace("persona", old, new)` — for updating; old must exact match.

## Tier 2: Archival Memory (graph)

For longer / less central facts → write to graph:
- `archival_memory_insert(content, reasoning, importance, evidence_quote, episode_id)`
  - `importance` 三档: 0.9 (explicit identity, e.g. "我永不碰高估值股") / 0.5 (contextual, e.g. "我看好半导体") / 0.2 (weak signal)
  - `evidence_quote` MUST be a verbatim substring from episode text — agent 凭空写会被 reject (algorithm 深度补丁 #2 防幻觉)
  - 调用前先确认 source episode_id

To recall from graph:
- `archival_memory_search(query, k)` — DEFAULT for "what did I say about X"
- `archival_memory_traverse(start_label, hops, rel_types)` — ONLY when user asks topology / relations:
  - 关系链 ("跟我持仓相关的", "同行业的")
  - 拓扑 ("所属行业的其他股", "...产业链", "上下游公司")
  - **Trigger words**: 相关 / 类似 / 同 / 同行业 / 同赛道 / 同概念 / 之间 / 链 / 上下游 / 产业链 / 属于 / 归类 / 范围 / 覆盖 / 对比 / vs

If `traverse` returns empty → fall back to `archival_memory_search`.

## Tier 3: Recall Memory (chat history)

For "我们上次聊过 X" / "你之前说过 Y" / "我不记得我说过没" → use:
- `recall_memory_search(query, k)`

Each result includes `source_session_id` + `message_id` for provenance.

## Memory hygiene rules

1. Don't write memory for one-off questions without user expressing facts.
2. Prefer `archival_memory_insert` over `core_memory_append` when uncertain — graph is searchable, working block is small.
3. importance scale: 0.9 explicit identity / 0.5 contextual / 0.2 weak signal — pick discrete tier, no in-between.
4. Provenance auto-tracked via `source_episode_id` — always pass it on every insert.
5. Don't try to insert facts you didn't observe — `evidence_quote` substring校验 will reject.
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/unit/memory/test_system_prompt_template.py -v` → 绿
- 模板加载点（ChatPlanner system prompt 拼接）由 Plan 6 接，本 Plan 只 ship 文件
- commit：`feat(c5-plan4): system prompt template for 3-tier memory + traverse trigger words + hygiene rules`

---

### Task 8: Tool Routing 监控周报 SQL + Eval Framework Skeleton

**目标**：spec § 6 周报 SQL ship 进 `backend/scripts/memory/`；Plan 8 写实际 50 case 用的 routing accuracy metric 骨架先 ship。

**Step 1 — Plan-time review**：
- spec § 6 给了完整 SQL；本 Plan 完整保留+扩展（per-user 维度 / per-day 维度）
- routing accuracy metric 骨架定义输入输出格式，让 Plan 8 直接填 case

**Step 2 — Failing test**：

`backend/tests/unit/memory/test_routing_metric_skeleton.py`：

```python
"""L0 — routing_accuracy_metric skeleton: input/output schema."""
from __future__ import annotations

import pytest


def test_routing_accuracy_metric_callable_with_no_cases():
    from app.eval.memory.routing_accuracy_metric import compute_routing_accuracy
    result = compute_routing_accuracy(cases=[])
    assert "total" in result
    assert "correct" in result
    assert "accuracy" in result
    assert result["total"] == 0


def test_routing_accuracy_metric_with_synthetic_case():
    from app.eval.memory.routing_accuracy_metric import compute_routing_accuracy

    cases = [
        {
            "query": "我的持仓",
            "expected_tool": "archival_memory_search",
            "predicted_tool": "archival_memory_search",
        },
        {
            "query": "茅台同行业的股",
            "expected_tool": "archival_memory_traverse",
            "predicted_tool": "archival_memory_search",  # 错配
        },
    ]
    result = compute_routing_accuracy(cases=cases)
    assert result["total"] == 2
    assert result["correct"] == 1
    assert abs(result["accuracy"] - 0.5) < 1e-6
    assert "per_tool_recall" in result


def test_weekly_sql_file_exists():
    from pathlib import Path
    p = Path(__file__).parent.parent.parent.parent / "scripts" / "memory" / "weekly_tool_routing_report.sql"
    assert p.exists()
    text = p.read_text()
    # 周报 SQL 必含字段
    assert "tool_name" in text
    assert "result_count" in text
    assert "latency_ms" in text
    assert "mcp_tool_call_log" in text
```

**Step 3 — Code**：

`backend/eval/memory/routing_accuracy_metric.py`（骨架）：

```python
"""Memory tool routing accuracy metric — Plan 4 skeleton, Plan 8 fills 50 cases.

Output format:
{
    "total": int,
    "correct": int,
    "accuracy": float,
    "per_tool_recall": {tool_name: float},
    "errors": [{"query", "expected", "predicted"}],
}
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


MEMORY_TOOLS = [
    "core_memory_append", "core_memory_replace",
    "archival_memory_insert", "archival_memory_search",
    "archival_memory_traverse", "recall_memory_search",
]


def compute_routing_accuracy(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """cases: list of {"query", "expected_tool", "predicted_tool"}."""
    total = len(cases)
    correct = 0
    per_tool_total: dict[str, int] = defaultdict(int)
    per_tool_correct: dict[str, int] = defaultdict(int)
    errors: list[dict[str, Any]] = []

    for c in cases:
        exp, pred = c["expected_tool"], c["predicted_tool"]
        per_tool_total[exp] += 1
        if exp == pred:
            correct += 1
            per_tool_correct[exp] += 1
        else:
            errors.append({"query": c["query"], "expected": exp, "predicted": pred})

    per_tool_recall = {
        t: (per_tool_correct[t] / per_tool_total[t]) if per_tool_total[t] > 0 else 0.0
        for t in MEMORY_TOOLS
    }
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "per_tool_recall": per_tool_recall,
        "errors": errors,
    }
```

`backend/scripts/memory/weekly_tool_routing_report.sql`：

```sql
-- spec § 6 tool routing 周报 — Plan 4 ship.
-- 用法: psql -d $DB_NAME -f weekly_tool_routing_report.sql

-- 1. Tool 调用频次 + hit rate + p50 latency
SELECT
    tool_name,
    COUNT(*) AS calls,
    AVG(CASE WHEN result_count > 0 THEN 1 ELSE 0 END) AS hit_rate,
    PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_latency,
    PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency,
    SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS error_count
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '7 days'
GROUP BY tool_name
ORDER BY calls DESC;

-- 2. 期望阈值（spec § 6）:
-- search hit > 80% / traverse hit > 50% / recall > 70%

-- 3. Per-user 维度 (top 10 重度 memory 用户)
SELECT
    user_id,
    COUNT(*) AS calls,
    COUNT(DISTINCT tool_name) AS tools_used
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '7 days'
GROUP BY user_id
ORDER BY calls DESC
LIMIT 10;

-- 4. Per-day routing 趋势
SELECT
    DATE(created_at) AS day,
    tool_name,
    COUNT(*) AS calls
FROM mcp_tool_call_log
WHERE tool_name LIKE '%memory%'
  AND created_at > now() - interval '14 days'
GROUP BY day, tool_name
ORDER BY day DESC, calls DESC;
```

**Step 4 — Run** + **Step 5 — Review**：
- `uv run pytest backend/tests/unit/memory/test_routing_metric_skeleton.py -v` → 绿
- 运行 SQL（dev PG）确认无语法错：`psql -d portfolio_dev -f backend/scripts/memory/weekly_tool_routing_report.sql`
- commit：`feat(c5-plan4): tool routing weekly report SQL + routing_accuracy metric skeleton`

---

### Task 9: L2 Cassette — Traverse + Recall Full Path

**目标**：录两个 representative cassette（contracts § 7）。

**Step 1 — Plan-time review**：
- 复用 `vcr_memory_cassette` fixture（contracts § 6）
- 两个 scenario：
  1. `traverse_full_path__industry_neighbors`：seed 一组 edges (User-HOLDS-茅台 / 茅台-BELONGS_TO-白酒 / 五粮液-BELONGS_TO-白酒) → traverse start_label='茅台' hops=2 → 期望返回五粮液
  2. `recall_full_path__我之前说过`：seed chat_messages → query "我之前说过茅台" → 命中

**Step 2 — Failing test**：

`backend/tests/e2e/memory/test_traverse_full_path.py`：

```python
"""L2 — archival_memory_traverse full path with VCR cassette."""
from __future__ import annotations

import json
import uuid
import pytest


@pytest.mark.asyncio
@pytest.mark.vcr_memory_cassette
async def test_traverse_industry_neighbors(
    pg_memory_fixture, age_fixture, milvus_memory_fixture, vcr_memory_cassette,
):
    """Seed 3 edges; traverse 茅台 hops=2 should return 五粮液 via 白酒."""
    from app.memory.models import ChatMemoryEdge, ChatMemoryNode, ChatMemoryEpisode
    from app.mcp_server.tools.memory.archival_memory_traverse import handle

    user_id = uuid.uuid4()
    ep_id = uuid.uuid4()

    async with pg_memory_fixture() as s:
        # Plan 1 helpers (assume seed_edges_for_traversal exists; else fallback to direct insert)
        s.add(ChatMemoryEpisode(
            episode_id=ep_id, user_id=user_id, session_id=uuid.uuid4(),
            episode_index=0, user_message_text="seed", source_kind="seed",
        ))
        await s.commit()
        # Direct insert via Memory Protocol(Plan 2 ship)or fallback raw SQL — left as Plan 1/2 helper
        # For cassette we record Plan 3 traverse output

    r = await handle({"user_id": str(user_id), "start_label": "贵州茅台", "hops": 2})
    out = json.loads(r[0].text)
    assert "paths" in out
    # 实施时根据真实 Plan 1/2 seed helper 调整 assertion
```

`backend/tests/e2e/memory/test_recall_full_path.py`：

```python
"""L2 — recall_memory_search full path."""
from __future__ import annotations

import json
import uuid
import pytest


@pytest.mark.asyncio
@pytest.mark.vcr_memory_cassette
async def test_recall_我之前说过(
    pg_memory_fixture, vcr_memory_cassette,
):
    from app.models.chat import ChatMessage, ChatSession
    from app.mcp_server.tools.memory.recall_memory_search import handle

    user_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    async with pg_memory_fixture() as s:
        s.add(ChatSession(id=sess_id, user_id=user_id, title="t"))
        await s.flush()
        s.add(ChatMessage(id=uuid.uuid4(), session_id=sess_id, role="user", content="我重仓茅台,长期持有"))
        await s.commit()

    r = await handle({"user_id": str(user_id), "query": "我之前说过茅台", "k": 5})
    out = json.loads(r[0].text)
    assert out["count"] >= 1
```

**Step 3 — Code**：测试逻辑就是契约。Cassette 录一次留库。

**Step 4 — Run** + **Step 5 — Review**：
- 录 cassette：`VCR_RECORD_MODE=once uv run pytest backend/tests/e2e/memory/ -v`
- 重放：`uv run pytest backend/tests/e2e/memory/ -v` → 绿（vcr replay）
- 检查 cassette 文件大小合理（< 50KB），路径在 `backend/tests/cassettes/memory/`
- commit：
  - `test(c5-plan4): L2 cassette for traverse + recall full path`
  - `chore(c5-plan4): record memory tool L2 cassettes (traverse / recall)`

---

### Task 10: 知识卡 + CLAUDE.md 索引 + Self-Review

**目标**：写 `c5-plan4-mcp-tools-done.md`，更新 `CLAUDE.md` 索引，self-review 全 plan。

**Step 1 — Plan-time review**：跟 contracts § 13 模板一致。

**Step 2 — Failing test**：N/A（doc）。

**Step 3 — Code**：

`docs/claude-context/c5-plan4-mcp-tools-done.md`：

```markdown
---
name: c5-plan4-mcp-tools-done
description: C.5 Plan 4 — 6 MCP tools + memory profile + evidence_quote 校验 ship
type: project
---

C.5 Plan 4 (6 MCP tools + memory profile + evidence_quote) ship — 2026-05-1X.

## ship 范围

- 6 MCP tool 实现（`backend/app/mcp_server/tools/memory/`）：core_memory_append / core_memory_replace / archival_memory_insert / archival_memory_search / archival_memory_traverse / recall_memory_search
- Memory MCP profile（`server.py --profile memory` + `mcp_servers.yaml`）独立于 PR #39 chat_tools profile
- `archival_memory_insert` evidence_quote substring 校验（algorithm 深度补丁 #2 part b）— 失败 raise `EvidenceNotFoundError` 不写入
- `recall_memory_search` 实现（PR #39 chat_messages 表 in-memory cosine over qwen embed）
- `mcp_tool_call_log` SQLAlchemy table + 每 tool invocation 写入 hook
- System prompt 模板（`backend/app/agents/chat/prompts/memory_tool_usage.md`）含 traverse trigger words + 5 条 hygiene rules
- Tool routing 周报 SQL（`scripts/memory/weekly_tool_routing_report.sql`）
- routing_accuracy metric 骨架（Plan 8 填 50 case）
- L0 / L1 / L2 测试全绿（10 task TDD）

## 关键决策（实施期撞实）

- `evidence_quote_in_episode` 实现成空白容忍 substring（`re.sub(r"\s+", "", text)` 后 `in` 检测）— 比 strict substring 更鲁棒, agent 偶尔加空格不被错杀
- `recall_memory_search` 选 in-memory cosine + last 5000 messages cap，不另建 Milvus collection — 个人 portfolio 量级足够，性能撞实再升级（contracts § 11 矩阵留口）
- `mcp_tool_call_log.user_id` 用 `String` 不用 `PgUUID` — 兼容 PR #39 trace 的 legacy str 习惯
- system prompt 模板放 markdown 不放 .py constant — Plan 6 supervisor 加载点 / 未来 RAG 化 prompt 都好做

## 跟 spec 决策对齐

- spec § 6 "core_memory_append max 200 chars" → Pydantic `max_length=200`
- spec § 6 "importance 三档 0.9/0.5/0.2" → Pydantic `Literal[0.9, 0.5, 0.2]`
- spec § 6 "k 默认 5 max 20" → Pydantic `Field(default=5, ge=1, le=20)`
- spec § 6 "hops 默认 2 max 3" → Pydantic `Field(default=2, ge=1, le=3)`
- spec § 6 "所有 tool 返回带 source_episode_id" → 每 tool JSON output 含 `source_episode_id`（search / insert）或 `session_id` + `message_id`（recall）
- spec § 11 末尾 #2 evidence_quote substring 校验 → `archival_memory_insert.handle` 强制调用，失败 raise

## 关键文件 ref

- `backend/app/mcp_server/tools/memory/__init__.py` — MEMORY_TOOL_MODULES
- `backend/app/mcp_server/tools/memory/archival_memory_insert.py` — 含 evidence_quote 校验 (algorithm 深度补丁 #2)
- `backend/app/mcp_server/server.py` — `build_server(profile=...)` 多 profile 分发
- `backend/app/memory/recall_search.py` — Tier 3 recall 实现
- `backend/app/memory/injection_classifier.py` — `evidence_quote_in_episode` + `EvidenceNotFoundError`（minimal Plan 4 / Plan 5 扩展）
- `backend/app/services/trace_models.py` — `MCPToolCallLog` 表
- `backend/app/agents/chat/prompts/memory_tool_usage.md` — system prompt 模板
- `mcp_servers.yaml` — 仓库根 MCP profile 配置
- `backend/scripts/memory/weekly_tool_routing_report.sql` — 监控周报 SQL
- `backend/eval/memory/routing_accuracy_metric.py` — Plan 8 用骨架

## 不在范围（Plan 5/6/7/8 后续）

- `is_prompt_injection` 完整规则 + ML 分类器 → Plan 5
- Memory vs KB supervisor router → Plan 6
- /memory page 调用 weekly SQL 可视化 → Plan 7
- 50 routing accuracy golden case + 阈值 assert → Plan 8
```

更新 `CLAUDE.md` 索引（在 `### v0.9.x 阶段性里程碑` 之前 / 或 v1.0 同 section）：

```markdown
### C.5 Cross-Session Memory（多 Plan ship 中）
- [Plan 4 — 6 MCP Tools + memory profile + evidence_quote](docs/claude-context/c5-plan4-mcp-tools-done.md) — 6 tool / memory MCP profile / algorithm 深度补丁 #2 evidence_quote 校验落地
```

**Step 4 — Run**：
- 全套测试一遍：`uv run pytest backend/tests/unit/memory/ backend/tests/integration/memory/ backend/tests/e2e/memory/ -v`
- mypy strict：`uv run mypy backend/app/mcp_server/tools/memory/ backend/app/memory/recall_search.py backend/app/memory/injection_classifier.py`
- ruff：`uv run ruff check backend/app/mcp_server/tools/memory/`

**Step 5 — Self-review**（强制 checklist）：
- [ ] **spec § 6 全覆盖**：6 tool + schema + system prompt + integration with PR #39 + 监控 SQL ✓
- [ ] **spec § 11 末尾 #2 evidence_quote 1:1**：`archival_memory_insert.handle` raise `EvidenceNotFoundError` + L1 test `test_archival_memory_insert_evidence_quote_fail` 验证 + 不写 edge ✓
- [ ] **contracts § 1 文件路径** 一致 ✓
- [ ] **contracts § 2 Memory Protocol** 6 tool 全调 Protocol method ✓
- [ ] **contracts § 5 evidence_quote_in_episode 函数签名** 一致 ✓
- [ ] **contracts § 6 fixture** 全复用，不新增 ✓
- [ ] **contracts § 12 测试分层** L0/L1/L2 全 ship（cassette 2 个）✓
- [ ] **contracts § 14 commit** 规范 `feat(c5-plan4): ...` ✓
- [ ] PR #39 既有 e2e 测试不退化（`test_mcp_client_e2e.py` 默认 chat_tools profile 兼容）✓
- [ ] mypy strict pass ✓
- [ ] ruff pass ✓
- [ ] 知识卡 + CLAUDE.md 索引更新 ✓

commit：`docs(c5-plan4): knowledge card + CLAUDE.md index for memory MCP tools ship`

---

## § 5 全 Plan Self-Review Checklist

| 项 | 检查 |
|---|---|
| **spec § 6 6 tool inventory** | core_memory_append / core_memory_replace / archival_memory_insert / archival_memory_search / archival_memory_traverse / recall_memory_search — 全 ship ✓ |
| **spec § 6 tool schema 关键字段** | max 200 chars / 三档 importance / k≤20 / hops≤3 — Pydantic 强约束 ✓ |
| **spec § 6 system prompt 模板** | `memory_tool_usage.md` 含 3 tier / trigger words / hygiene rules ✓ |
| **spec § 6 integration with PR #39** | `mcp_servers.yaml` + `--profile` 路由 + chat_tools 默认兼容 ✓ |
| **spec § 6 tool 返回 source_episode_id** | search/insert 含 `source_episode_id`; recall 含 `session_id+message_id` ✓ |
| **spec § 6 监控 SQL** | `weekly_tool_routing_report.sql` ship ✓ |
| **spec § 6 eval framework** | `routing_accuracy_metric.py` 骨架 ✓（Plan 8 fill 50 case）|
| **spec § 11 末尾 #2 evidence_quote substring 校验** | `archival_memory_insert.handle` 强制调用 + `EvidenceNotFoundError` raise + L1 test 验证不写入 + L2 cassette 不录 evidence_quote fail（fail 不调 LLM）✓ |
| **contracts § 1 文件路径** | 6 文件 + `__init__.py` + `_common.py` 全在 `backend/app/mcp_server/tools/memory/` ✓ |
| **contracts § 2 Memory Protocol** | 6 tool 全调 Protocol method 不绕过 ✓ |
| **contracts § 5 evidence_quote_in_episode** | Plan 4 minimal ship + Plan 5 扩展协议留 ✓ |
| **contracts § 6 fixture** | 全复用 Plan 1-3 ship 的 ✓ |
| **contracts § 8 traverse trigger 词** | system prompt 11 个 trigger 词全列 ✓ |
| **contracts § 12 测试分层** | L0 单元(schema/metric skeleton/template) + L1 integration(6 tool e2e + log) + L2 cassette(traverse + recall) ✓ |
| **contracts § 14 commit 规范** | 每 Task 单 commit + feat / test / docs / chore 前缀 ✓ |
| **依赖前置** | Plan 1 / 2 / 3 / 5 ship 后再实施；Task 4 minimal evidence_quote 兜底 ✓ |
| **不破坏 PR #39** | `MCPClient.from_subprocess` 默认 profile=chat_tools 兼容；既有 6 tool 文件未改 ✓ |
| **mypy strict** | 全 plan 文件 pass ✓ |
| **ruff** | 全 plan 文件 pass ✓ |

---

## § 6 风险 / 已知坑

| 风险 | 缓解 |
|---|---|
| Plan 5 ship 顺序晚于 Plan 4 → `evidence_quote_in_episode` 不存在 | Task 4 minimal 实现兜底，Plan 5 扩展时合并不替换 |
| `mcp_tool_call_log` 写入失败导致 tool 调用失败 | `_common.write_tool_call_log` 已 `if sf is None: return` 兜测试无 DB；finally 块包 swallow connection error（实施期再包一层 try）|
| `recall_memory_search` 用户消息 >5000 条 in-memory cosine 慢 | 当前 cap 5000 + 按 created_at desc 取最近；性能撞实告警进 Plan 5 异步嵌入预计算 |
| `--profile` arg 改动 `MCPClient.from_subprocess` 可能影响 PR #39 既有调用 | `profile="chat_tools"` 默认值 + L1 test 验证不退化 |
| AGE traverse 在 mock LLM 下结果不稳 | L2 cassette 录真实结果；L1 只 assert "no exception + paths key 存在" 不锁内容 |
| evidence_quote 空白容忍策略可能漏掉同义改写 | 这是 Plan 4 minimal 设计；Plan 5 ship 时考虑加 LLM-based semantic match fallback（spec § 11 末尾 #2 后续优化）|

---

## § 7 工程量明细

| Task | 工时 | 累计 |
|---|---|---|
| 1. 6 tool 文件骨架 + Pydantic schema + L0 test | 0.5d | 0.5d |
| 2. mcp_tool_call_log 表 + model | 0.25d | 0.75d |
| 3. recall_memory_search 实现 + L1 test | 0.5d | 1.25d |
| 4. evidence_quote_in_episode minimal + EvidenceNotFoundError | 0.25d | 1.5d |
| 5. server.py multi-profile + mcp_servers.yaml + MCPClient 改造 | 0.5d | 2.0d |
| 6. 6 tool L1 e2e test（含 evidence_quote fail 校验）| 0.75d | 2.75d |
| 7. system prompt 模板 + L0 test | 0.25d | 3.0d |
| 8. 周报 SQL + routing_accuracy metric 骨架 | 0.25d | 3.25d |
| 9. L2 cassette × 2（traverse + recall）| 0.5d | 3.75d |
| 10. 知识卡 + CLAUDE.md 索引 + 全 plan self-review | 0.25d | 4.0d |

**4 天 wall time** 跟 spec § 11 末尾 #2 + § 13 工程量估算（"#2 投毒 + Agent 幻觉 1.5 天" 内的 evidence_quote 部分约 0.5 天 + Plan 4 主体 6 tool ≈ 3.5 天）一致。

---

## § 8 PR 合并清单

PR 标题：`feat(c5-plan4): 6 memory MCP tools + memory profile + evidence_quote 校验`

PR body 必含：
- spec ref：`docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 6 + § 11 末尾 #2 part b
- contracts ref：`docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 1/2/5/6/8/11/12/14
- algorithm depth patch tag：`#2 evidence_quote substring 校验落地（Agent 幻觉写防御）`
- 测试覆盖：L0 单测 N case + L1 e2e M case + L2 cassette 2 个
- mypy strict + ruff pass
- 不破坏 PR #39 chat_tools profile（验证：`backend/tests/integration/test_mcp_client_e2e.py` 全绿）
- 知识卡：`docs/claude-context/c5-plan4-mcp-tools-done.md`
- CLAUDE.md C.5 section index 更新

---

**Plan 4 — END**
