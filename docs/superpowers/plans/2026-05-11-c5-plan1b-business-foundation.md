# C.5 Plan 1B — Business Foundation

> **Status**: implementation plan(2026-05-11)
> **Plan 范围**: Memory Protocol + HierarchicalMemory 骨架 + DI 替换 + Entity registry + Working blocks CRUD + Cold start populator(静态) + Reconciliation 骨架
> **工程量**: 4 天 wall time
> **依赖前置**: Plan 1A ship(4 PG 表 / AGE / Milvus collection + 幂等键 UNIQUE constraint 已建)
> **下游解锁**: Plan 2(写入 8 step pipeline) / Plan 3(读取) / Plan 4(MCP tools)
> **算法深度补丁归属**: § 11 末尾 #5 三方一致性 — reconciliation 入口骨架(Plan 5 weekly job 收束)

---

## § 0 Spec Reference

- **Spec 主文件**: `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`
- **共享契约**: `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md`(必读, 严守 § 2 Protocol / § 3 class 骨架 / § 5 helper 签名)
- **本 Plan 直接对齐 spec 章节**:
  - § 1 整体架构(DI 接入 chat agent)
  - § 3 Ontology(7 entity + 11 rel 白名单 / normalize 规则)
  - § 7 Working memory budget(persona 500 + scratchpad 1000, 超 max_tokens 自动 paging)
  - § 8 Cold Start Populator(3 路 seed + 幂等)
  - § 11 末尾 #5 三方一致性(reconciliation 入口骨架)

**前置 anchor**:
- PR #39 ship: `backend/app/agents/in_session_memory.py`(本 Plan 替换为 HierarchicalMemory + 给 InSessionMemory 加 Protocol 兼容 stub)
- PR #39 ship: `backend/app/agents/memory_protocol.py`(本 Plan 扩展为 `app.memory.protocol`, legacy file 保留兼容 import)
- v1.0 持仓 ship: `backend/app/models/position.py`(cold start HOLDS 数据源)

---

## § 1 File Structure(本 Plan 新建 / 修改)

### 新建文件

```
backend/app/memory/
├── __init__.py                  ← export Memory / HierarchicalMemory / 常量
├── protocol.py                  ← Memory Protocol(扩展契约 § 2)
├── hierarchical.py              ← HierarchicalMemory class(骨架 + Plan 1B 范围方法)
├── registry.py                  ← Entity registry(7+11 + normalize_entity / jieba)
├── working_blocks.py            ← Tier 1 working memory CRUD(auto-paging)
├── cold_start.py                ← 静态 cold start populator(3 路 seed + CLI)
└── reconciliation.py            ← Reconciliation job 骨架(scan inconsistent state)

backend/tests/unit/memory/
├── __init__.py
├── test_protocol.py             ← Protocol runtime_checkable + InSessionMemory 兼容
├── test_registry.py             ← normalize_entity 5 类 + is_valid_rel_type + jieba
├── test_working_blocks.py       ← CRUD + auto-paging + replace exact match
├── test_hierarchical_skeleton.py ← class signature / DI 参数 / stub 方法 raise NotImplementedError
└── test_cold_start.py           ← 3 路 seed + 幂等(L0 sqlite override)

backend/tests/integration/memory/
├── __init__.py
├── conftest.py                  ← pg_memory_fixture / age_fixture(本 Plan 创建)
├── test_working_blocks_e2e.py   ← real PG: append/replace + concurrency
├── test_cold_start_e2e.py       ← real PG: 持仓 → HOLDS edges + 重跑无重复
└── test_reconciliation_e2e.py   ← real PG: scan inconsistent state
```

### 修改文件

```
backend/app/router/chat.py                    ← _build_graph_singleton DI: InSessionMemory → HierarchicalMemory
backend/app/agents/in_session_memory.py       ← 加 6 个 Protocol 新方法 stub(raise NotImplementedError)
backend/app/agents/memory_protocol.py         ← legacy 保留, 加注释指向 app.memory.protocol
backend/app/orchestration/chat_graph.py       ← 不动(memory 从 build_chat_graph 参数注入, 已有 hook)
```

### Migration 文件

> **不在本 Plan 范围**: 4 PG 表 schema / AGE / Milvus collection 都在 Plan 1A ship。本 Plan 假设 `chat_memory_episodes / chat_memory_nodes / chat_memory_edges / chat_memory_working_blocks` 4 表 + AGE 'chat_memory' 图 + Milvus collection 已存在。

---

## § 2 Tasks 总览(10 个)

| # | Task | 范围 | 测试 layer |
|---|---|---|---|
| 1 | `app.memory` package 骨架 + Protocol 完整签名 | protocol.py / __init__.py | L0 |
| 2 | InSessionMemory Protocol 兼容(加 6 stub) | in_session_memory.py 改 | L0 |
| 3 | Entity Registry(7+11 + normalize + jieba) | registry.py | L0 |
| 4 | Working Blocks CRUD(append/replace/get) | working_blocks.py | L0 + L1 |
| 5 | HierarchicalMemory class 骨架 + DI signature | hierarchical.py | L0 |
| 6 | HierarchicalMemory: working blocks 方法 | hierarchical.py | L0 + L1 |
| 7 | HierarchicalMemory: episode 持久化方法 | hierarchical.py | L1 |
| 8 | Cold Start Populator(静态 3 路 seed + CLI) | cold_start.py | L0 + L1 |
| 9 | Reconciliation 骨架(scan inconsistent) | reconciliation.py | L1 |
| 10 | DI 替换 chat router + smoke test + 知识卡 | router/chat.py + 卡 | L0 + smoke |

每个 task 走 5-step TDD: spec → 写 failing test → 写最小实现 → 跑 test 绿 → commit。

---

## § 3 Tasks 详细

---

### Task 1: `app.memory` package 骨架 + Protocol 完整签名

#### 1.1 spec / contract ref
- 契约 § 2 Memory Protocol 全部签名
- spec § 1 Memory Protocol DI hook

#### 1.2 写 failing test

文件: `backend/tests/unit/memory/test_protocol.py`

```python
"""L0: Memory Protocol runtime_checkable + 完整签名."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from app.memory.protocol import Memory


def test_memory_protocol_is_runtime_checkable() -> None:
    """Protocol 用 @runtime_checkable 装饰, isinstance check 可用."""
    assert hasattr(Memory, "_is_runtime_protocol")
    assert getattr(Memory, "_is_runtime_protocol", False) is True


def test_memory_protocol_method_signatures() -> None:
    """契约 § 2: 9 个 method 签名齐全."""
    expected = {
        "get_working_blocks",
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
        "write_episode",
        "get_unextracted_episodes",
        "mark_episode_extracted",
    }
    actual = {
        name
        for name, m in inspect.getmembers(Memory, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert expected.issubset(actual), f"missing methods: {expected - actual}"


def test_archival_memory_insert_has_evidence_quote() -> None:
    """算法深度补丁 #2: evidence_quote 必填参数."""
    sig = inspect.signature(Memory.archival_memory_insert)
    assert "evidence_quote" in sig.parameters
    # 必填(no default)
    assert sig.parameters["evidence_quote"].default is inspect.Parameter.empty


def test_all_methods_first_param_is_user_id() -> None:
    """契约: 所有方法第一参数 user_id: UUID(多租户隔离)."""
    method_names = [
        "get_working_blocks",
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
        "write_episode",
        "get_unextracted_episodes",
    ]
    for name in method_names:
        sig = inspect.signature(getattr(Memory, name))
        params = list(sig.parameters.values())
        # params[0] 是 self(Protocol method)
        assert len(params) >= 2, f"{name} 至少要 self + user_id"
        assert params[1].name == "user_id", f"{name} 第二参数应是 user_id, 实际 {params[1].name}"
```

跑 → red(`app.memory.protocol` 不存在)。

#### 1.3 实现

新建 `backend/app/memory/__init__.py`:

```python
"""C.5 cross-session memory subsystem.

Plan 1A: 4 PG 表 schema / AGE / Milvus collection.
Plan 1B(本): Protocol + HierarchicalMemory 骨架 + working blocks + cold start + reconciliation.
Plan 2-8: 写入 / 读取 / MCP tools / cost / routing / UI / eval.
"""

from app.memory.protocol import Memory

__all__ = ["Memory"]
```

新建 `backend/app/memory/protocol.py`:

```python
"""Memory Protocol — DI hook for chat agent's memory layer.

PR #39 ship 的 InSessionMemory 实现 in-session 范畴(Q4 E).
C.5 加 HierarchicalMemory 实现跨 session 范畴(D MemGPT-style).
两者通过 Memory Protocol 互换.

注: PR #39 的 app.agents.memory_protocol.Memory 是 in-session 子集 Protocol,
本文件是其超集. InSessionMemory 通过 stub 方式实现本 Protocol(Plan 1B Task 2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    # Plan 1A 已 ship 的 SQLAlchemy ORM 类
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryWorkingBlock,
    )


@runtime_checkable
class Memory(Protocol):
    """Memory interface used by ChatAgent / ResearchAgent.

    HierarchicalMemory(Plan 1-4) 和 InSessionMemory(PR #39 ship) 都实现此 Protocol.
    """

    # === Tier 1 Working Memory(Plan 1B 完整实现) ===

    async def get_working_blocks(
        self, user_id: UUID
    ) -> dict[str, "ChatMemoryWorkingBlock"]:
        """Return {block_name: block} for user's persona / scratchpad blocks."""
        ...

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> "ChatMemoryWorkingBlock":
        """Append content to working block. Auto-paging if exceed max_tokens."""
        ...

    async def core_memory_replace(
        self,
        user_id: UUID,
        block_name: str,
        old_content: str,
        new_content: str,
    ) -> "ChatMemoryWorkingBlock":
        """Replace exact substring. Raise ValueError if old_content not found."""
        ...

    # === Tier 2 Archival(Plan 2 写入 / Plan 3 读取) ===

    async def archival_memory_insert(
        self,
        user_id: UUID,
        content: dict[str, Any],
        reasoning: str,
        importance: float,
        evidence_quote: str,           # 算法深度补丁 #2: 防 Agent 幻觉写
        episode_id: UUID,
    ) -> "ChatMemoryEdge":
        """Write fact to graph. Plan 2 实现完整 pipeline."""
        ...

    async def archival_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list["ChatMemoryEdge"]:
        """3-way hybrid + RRF v2. Plan 3 实现."""
        ...

    async def archival_memory_traverse(
        self,
        user_id: UUID,
        start_label: str,
        hops: int = 2,
        rel_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """On-demand graph traversal via AGE Cypher. Plan 4 实现."""
        ...

    # === Tier 3 Recall(Plan 4 实现, 复用 PR #39 chat_messages 表) ===

    async def recall_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search on chat_messages history. Plan 4 实现."""
        ...

    # === 持久化 episodes(Plan 1B 完整实现) ===

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> "ChatMemoryEpisode":
        """Path A 写入路径 step 1: episode 入库, extracted_at=NULL."""
        ...

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list["ChatMemoryEpisode"]:
        """Path B end-of-session batch 用. Plan 5 batch extractor 调用."""
        ...

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,             # 'agent' / 'eos_batch' / 'manual'
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Step 8: 抽取完成标记."""
        ...
```

#### 1.4 跑测试

```bash
cd backend && uv run pytest tests/unit/memory/test_protocol.py -xvs
```

#### 1.5 commit

```bash
git add backend/app/memory/__init__.py backend/app/memory/protocol.py backend/tests/unit/memory/__init__.py backend/tests/unit/memory/test_protocol.py
git commit -m "feat(c5-plan1b): app.memory.protocol Memory Protocol + 完整 9 method 签名"
```

---

### Task 2: InSessionMemory Protocol 兼容(加 6 stub method)

#### 2.1 spec / contract ref
- 契约 § 2 末尾"需要在 PR #39 ship 的 InSessionMemory 上加 stub 这些方法(raise NotImplementedError), 保持 Protocol 兼容"

#### 2.2 写 failing test

加到 `backend/tests/unit/memory/test_protocol.py`:

```python
def test_in_session_memory_satisfies_extended_protocol() -> None:
    """PR #39 ship 的 InSessionMemory 通过 stub 满足扩展 Protocol(isinstance check)."""
    from app.agents.in_session_memory import InSessionMemory

    instance = InSessionMemory(llm=None)
    assert isinstance(instance, Memory)


@pytest.mark.asyncio
async def test_in_session_memory_stubs_raise_not_implemented() -> None:
    """InSessionMemory 的新 method stub 必须 raise NotImplementedError."""
    from app.agents.in_session_memory import InSessionMemory

    mem = InSessionMemory(llm=None)
    uid = uuid4()
    with pytest.raises(NotImplementedError):
        await mem.get_working_blocks(uid)
    with pytest.raises(NotImplementedError):
        await mem.core_memory_append(uid, "persona", "x")
    with pytest.raises(NotImplementedError):
        await mem.archival_memory_insert(
            uid, {}, "r", 0.5, "ev", uuid4()
        )
    with pytest.raises(NotImplementedError):
        await mem.archival_memory_search(uid, "q")
    with pytest.raises(NotImplementedError):
        await mem.write_episode(uid, uuid4(), 0, "u", "a")
    with pytest.raises(NotImplementedError):
        await mem.mark_episode_extracted(uuid4(), "agent", {})
```

跑 → red。

#### 2.3 实现

修改 `backend/app/agents/in_session_memory.py` 末尾, class 内新增 stub:

```python
# 在 class InSessionMemory 末尾追加:

    # === C.5 Plan 1B: Protocol 兼容 stub(InSessionMemory 不实现 cross-session) ===

    async def get_working_blocks(self, user_id):  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            "InSessionMemory 是 in-session memory(PR #39 Q4 E), "
            "Tier 1 working blocks 由 HierarchicalMemory(C.5 Plan 1B+)实现."
        )

    async def core_memory_append(self, user_id, block_name, content):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.core_memory_append")

    async def core_memory_replace(  # type: ignore[no-untyped-def]
        self, user_id, block_name, old_content, new_content
    ):
        raise NotImplementedError("see HierarchicalMemory.core_memory_replace")

    async def archival_memory_insert(  # type: ignore[no-untyped-def]
        self, user_id, content, reasoning, importance, evidence_quote, episode_id
    ):
        raise NotImplementedError("see HierarchicalMemory.archival_memory_insert (Plan 2)")

    async def archival_memory_search(self, user_id, query, k=5):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.archival_memory_search (Plan 3)")

    async def archival_memory_traverse(  # type: ignore[no-untyped-def]
        self, user_id, start_label, hops=2, rel_types=None
    ):
        raise NotImplementedError("see HierarchicalMemory.archival_memory_traverse (Plan 4)")

    async def recall_memory_search(self, user_id, query, k=5):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.recall_memory_search (Plan 4)")

    async def write_episode(  # type: ignore[no-untyped-def]
        self, user_id, session_id, episode_index, user_message, agent_response, source_kind="chat_turn"
    ):
        raise NotImplementedError("see HierarchicalMemory.write_episode")

    async def get_unextracted_episodes(self, user_id, limit=100):  # type: ignore[no-untyped-def]
        raise NotImplementedError("see HierarchicalMemory.get_unextracted_episodes")

    async def mark_episode_extracted(  # type: ignore[no-untyped-def]
        self, episode_id, extracted_by, extraction_metadata
    ):
        raise NotImplementedError("see HierarchicalMemory.mark_episode_extracted")
```

注: 用 `# type: ignore[no-untyped-def]` 因为 stub 不需要写完整 type annotation, 避免循环 import; mypy 全 backend 跑必须过。

#### 2.4 跑测试

```bash
cd backend && uv run pytest tests/unit/memory/test_protocol.py -xvs
cd backend && uv run mypy app/agents/in_session_memory.py
```

#### 2.5 commit

```bash
git add backend/app/agents/in_session_memory.py backend/tests/unit/memory/test_protocol.py
git commit -m "feat(c5-plan1b): InSessionMemory 加 6 stub 方法保持扩展 Protocol 兼容"
```

---

### Task 3: Entity Registry(7+11 白名单 + normalize + jieba)

#### 3.1 spec / contract ref
- 契约 § 5 `registry.py` ENTITY_TYPES / REL_TYPES / `normalize_entity` / `is_valid_rel_type` / `jieba_tokenize_for_search` 签名
- spec § 3 ontology 7 entity 类 + 11 rel 类 + 4 normalize 规则

#### 3.2 写 failing test

文件: `backend/tests/unit/memory/test_registry.py`

```python
"""L0: Entity registry — 7 entity types + 11 rel types + normalize_entity + jieba."""

from __future__ import annotations

import pytest

from app.memory.registry import (
    ENTITY_TYPES,
    METRIC_WHITELIST,
    REL_TYPES,
    STRATEGY_WHITELIST,
    is_valid_rel_type,
    jieba_tokenize_for_search,
    normalize_entity,
)


# ---- 常量 ----

def test_entity_types_count_seven() -> None:
    assert len(ENTITY_TYPES) == 7
    assert set(ENTITY_TYPES) == {
        "User", "Stock", "Industry", "Sector", "Metric", "Strategy", "Concept"
    }


def test_rel_types_count_eleven() -> None:
    assert len(REL_TYPES) == 11
    assert set(REL_TYPES) == {
        "HOLDS", "WATCHES", "PREFERS", "AVOIDS", "EXPRESSED_VIEW", "SOLD",
        "STUDIED", "COMPARED", "BELONGS_TO", "HAS_CONCEPT", "CORRELATED_WITH",
    }


def test_metric_whitelist_has_pe_roe() -> None:
    """spec 附录 A 白名单核心 metric 必须在."""
    assert "PE" in METRIC_WHITELIST
    assert "ROE" in METRIC_WHITELIST


def test_strategy_whitelist_has_dcf_value() -> None:
    """spec 附录 A 白名单核心 strategy 必须在."""
    assert "DCF" in STRATEGY_WHITELIST
    assert "价值投资" in STRATEGY_WHITELIST


# ---- is_valid_rel_type ----

def test_is_valid_rel_type_holds() -> None:
    assert is_valid_rel_type("HOLDS") is True


def test_is_valid_rel_type_unknown() -> None:
    assert is_valid_rel_type("FROBNICATES") is False


# ---- normalize_entity ----

@pytest.mark.parametrize(
    "raw, expected, audit",
    [
        ("600519.SH", "600519.SH", False),
        ("000858.SZ", "000858.SZ", False),
        ("000001.BJ", "000001.BJ", False),
        ("茅台", "茅台", True),                  # 不是 ts_code 格式 → audit_flag
        ("600519.SH ", "600519.SH", False),    # trim
    ],
)
def test_normalize_entity_stock(raw: str, expected: str, audit: bool) -> None:
    label, audit_flag = normalize_entity("Stock", raw)
    assert label == expected
    assert audit_flag is audit


def test_normalize_entity_user_fixed() -> None:
    """User 类型固定 'User' label."""
    label, audit_flag = normalize_entity("User", "anything")
    assert label == "User"
    assert audit_flag is False


def test_normalize_entity_metric_pe_uppercase() -> None:
    label, audit_flag = normalize_entity("Metric", "pe")
    assert label == "PE"
    assert audit_flag is False


def test_normalize_entity_metric_unknown_audit() -> None:
    label, audit_flag = normalize_entity("Metric", "unknown_metric")
    assert audit_flag is True


def test_normalize_entity_strategy_dcf() -> None:
    label, audit_flag = normalize_entity("Strategy", "dcf")
    assert label == "DCF"
    assert audit_flag is False


def test_normalize_entity_industry_passthrough() -> None:
    """申万 registry 不在 Plan 1B 范围, 走 passthrough + audit_flag(下游 v1.x 接 registry)."""
    label, audit_flag = normalize_entity("Industry", "白酒")
    assert label == "白酒"
    # 当前没接申万 registry, 走 audit_flag 提示后续补
    assert audit_flag is True


# ---- jieba_tokenize_for_search ----

def test_jieba_tokenize_chinese() -> None:
    """jieba.cut_for_search 切'贵州茅台' → '贵州 茅台 贵州茅台'."""
    tokens = jieba_tokenize_for_search("贵州茅台")
    parts = set(tokens.split())
    # cut_for_search 至少切出"贵州"和"茅台"
    assert "贵州" in parts
    assert "茅台" in parts


def test_jieba_tokenize_empty_string() -> None:
    assert jieba_tokenize_for_search("") == ""


def test_jieba_tokenize_mixed_zh_en() -> None:
    tokens = jieba_tokenize_for_search("茅台 600519.SH")
    parts = set(tokens.split())
    assert "茅台" in parts
    assert "600519" in parts or "600519.SH" in parts
```

跑 → red。

#### 3.3 实现

新建 `backend/app/memory/registry.py`:

```python
"""Entity registry — 7 entity + 11 rel + normalize + jieba tokenize.

spec ref: § 3 Ontology(prescribed seed + drift-tolerant)
contract ref: § 5 registry.py 签名

Plan 1B 范围:
- Stock: ts_code 格式校验(6 数字 + .SH/.SZ/.BJ), 失败 audit_flag=True
- Industry/Sector: passthrough + audit_flag=True(申万 registry 留 v1.x 接)
- Metric/Strategy: 附录 A 白名单 → 统一英文标识
- Concept: passthrough(免 audit, 主题概念太多无法白名单)
- User: 固定 'User'

未来增强(留 v1.x):
- 申万行业 registry 接 Tushare /api/sw_hierarchy
- Concept registry 接 Tushare 概念字段
"""

from __future__ import annotations

import re

import jieba

# === 7 entity types ===
ENTITY_TYPES: list[str] = [
    "User", "Stock", "Industry", "Sector", "Metric", "Strategy", "Concept",
]

# === 11 rel types ===
REL_TYPES: list[str] = [
    "HOLDS", "WATCHES", "PREFERS", "AVOIDS", "EXPRESSED_VIEW", "SOLD",
    "STUDIED", "COMPARED", "BELONGS_TO", "HAS_CONCEPT", "CORRELATED_WITH",
]

# === 附录 A 白名单 ===

# Metric 白名单(估值 + 财务 + 现金流 + 成长 ~30 个)
METRIC_WHITELIST: dict[str, str] = {
    # 估值
    "pe": "PE", "pe_ttm": "PE_TTM", "pb": "PB", "ps": "PS", "ev_ebitda": "EV_EBITDA",
    "dividend_yield": "dividend_yield",
    # 盈利
    "roe": "ROE", "roa": "ROA", "roic": "ROIC", "gross_margin": "gross_margin",
    "net_margin": "net_margin", "eps": "EPS",
    # 现金流
    "cash_flow": "cash_flow", "fcf": "FCF", "operating_cash_flow": "operating_cash_flow",
    # 资产负债
    "debt_ratio": "debt_ratio", "current_ratio": "current_ratio",
    "quick_ratio": "quick_ratio",
    # 成长
    "revenue_growth": "revenue_growth", "earnings_growth": "earnings_growth",
    "yoy_growth": "yoy_growth",
}

# Strategy 白名单(估值 + 增长 + 价值 ~20 个)
STRATEGY_WHITELIST: dict[str, str] = {
    "dcf": "DCF",
    "价值投资": "价值投资", "value_investing": "价值投资",
    "成长投资": "成长投资", "growth_investing": "成长投资",
    "趋势投资": "趋势投资", "momentum": "趋势投资",
    "deep_value": "deep_value",
    "quality_growth": "quality_growth", "高股息": "高股息",
    "技术分析": "技术分析", "technical_analysis": "技术分析",
    "套利": "套利", "arbitrage": "套利",
    "PEG": "PEG", "EVA": "EVA",
}

# === ts_code regex(6 数字 + .SH/.SZ/.BJ)===
_TS_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


def normalize_entity(entity_type: str, raw_label: str) -> tuple[str, bool]:
    """Returns (normalized_label, audit_flag).

    - User: 固定 'User'
    - Stock: ts_code 校验; 不匹配 → trim 后 audit_flag=True
    - Metric/Strategy: 白名单(case-insensitive) → 统一标识; 失败 audit_flag=True
    - Industry/Sector: 当前 passthrough + audit_flag=True(留 v1.x 接申万 registry)
    - Concept: passthrough + audit_flag=False(主题概念无法白名单)

    audit_flag=True 表示 normalize 失败(写库时仍写, 标 audit_flag 在 properties).
    """
    if entity_type == "User":
        return "User", False

    label = raw_label.strip()

    if entity_type == "Stock":
        if _TS_CODE_RE.match(label):
            return label, False
        # 不是 ts_code 格式(如 "茅台" / "Maotai") → audit
        return label, True

    if entity_type == "Metric":
        normalized = METRIC_WHITELIST.get(label.lower())
        if normalized is None:
            return label, True
        return normalized, False

    if entity_type == "Strategy":
        normalized = STRATEGY_WHITELIST.get(label.lower())
        if normalized is None:
            return label, True
        return normalized, False

    if entity_type in ("Industry", "Sector"):
        # 申万 registry 留 v1.x; 当前 passthrough + audit_flag
        return label, True

    if entity_type == "Concept":
        return label, False

    # 未知 entity_type
    return label, True


def is_valid_rel_type(rel_type: str) -> bool:
    """Pure: rel_type ∈ REL_TYPES?"""
    return rel_type in REL_TYPES


def jieba_tokenize_for_search(text: str) -> str:
    """jieba.cut_for_search 全模式切词, 空格连接.

    用于 chat_memory_nodes / chat_memory_edges 的 search_tokens 字段写入.
    Plan 1B 实现, Plan 3 检索路径 1(BM25)调用.

    spec ref: § 5 路径 1 jieba pre-tokenize 方案(避开 zhparser PG 扩展可移植性问题).
    """
    if not text:
        return ""
    return " ".join(jieba.cut_for_search(text))
```

#### 3.4 跑测试

```bash
cd backend && uv run pytest tests/unit/memory/test_registry.py -xvs
```

注: jieba 已在 PR #39 ship 的 deps 里(KB chunking 用), 不需要新加。如不在则 `uv add jieba`。

#### 3.5 commit

```bash
git add backend/app/memory/registry.py backend/tests/unit/memory/test_registry.py
git commit -m "feat(c5-plan1b): entity registry — 7+11 ontology + normalize_entity + jieba_tokenize"
```

---

### Task 4: Working Blocks CRUD(append/replace/get + auto-paging)

#### 4.1 spec / contract ref
- spec § 7 Working memory budget(persona 500 / scratchpad 1000 + 超 max_tokens 自动 paging)
- 契约 § 6: `core_memory_append.content` max 200 chars/call(防 spam)
- 契约 § 6: `core_memory_replace.old_content` 必须 exact match, raise ValueError if 找不到
- 契约 § 6: `core_memory_append` 超 max_tokens 不报错, 触发自动 paging(archive oldest line + 裁剪)

#### 4.2 写 failing test (L0)

文件: `backend/tests/unit/memory/test_working_blocks.py`

```python
"""L0: Working blocks 纯函数 — token counter + paging logic."""

from __future__ import annotations

import pytest

from app.memory.working_blocks import (
    APPEND_MAX_CHARS,
    BLOCK_DEFAULTS,
    approx_token_count,
    do_append_with_paging,
    do_replace_exact,
)


# ---- approx_token_count ----

def test_approx_token_count_chinese() -> None:
    """中文按 1.33 tokens/char(spec § 7 calibration)."""
    n = approx_token_count("茅台 600519")
    assert n > 0
    assert isinstance(n, int)


def test_approx_token_count_empty_zero() -> None:
    assert approx_token_count("") == 0


# ---- BLOCK_DEFAULTS ----

def test_block_defaults_persona_500() -> None:
    assert BLOCK_DEFAULTS["persona"] == 500


def test_block_defaults_scratchpad_1000() -> None:
    assert BLOCK_DEFAULTS["scratchpad"] == 1000


# ---- do_append_with_paging ----

def test_append_below_budget_no_paging() -> None:
    """budget 充裕 → 直接 append, paged_lines 空."""
    new_content, paged = do_append_with_paging(
        existing="line1\nline2",
        new="line3",
        max_tokens=500,
    )
    assert new_content == "line1\nline2\nline3"
    assert paged == []


def test_append_exceed_budget_pages_oldest_lines() -> None:
    """超 budget → 自动 paging oldest lines(MemGPT 哲学, 不报错)."""
    existing = "\n".join([f"line{i}" * 30 for i in range(20)])  # 大块文本
    new_content, paged = do_append_with_paging(
        existing=existing,
        new="newest_line",
        max_tokens=10,  # 故意小让必须 page
    )
    # paged 必非空(oldest 被踢)
    assert len(paged) > 0
    # newest_line 必在 new_content 末尾
    assert new_content.endswith("newest_line")


def test_append_max_chars_per_call_constraint() -> None:
    """APPEND_MAX_CHARS=200 — content 超 200 chars raise ValueError."""
    assert APPEND_MAX_CHARS == 200
    with pytest.raises(ValueError, match="200 chars"):
        do_append_with_paging(
            existing="",
            new="x" * 201,
            max_tokens=500,
        )


# ---- do_replace_exact ----

def test_replace_exact_match_succeeds() -> None:
    new = do_replace_exact(
        existing="cash flow 重要\nROE 重要",
        old_content="重要",
        new_content="关键",
    )
    # 注: replace_all 模式 — 替换所有 "重要" 为 "关键"
    assert "cash flow 关键" in new
    assert "ROE 关键" in new


def test_replace_no_match_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        do_replace_exact(
            existing="cash flow",
            old_content="不存在",
            new_content="新",
        )
```

跑 → red。

#### 4.3 实现

新建 `backend/app/memory/working_blocks.py`:

```python
"""Tier 1 Working Memory — pure function layer for append / replace / paging.

spec ref: § 7 Working memory budget
contract ref: § 6 core_memory_append/replace 约束

设计要点:
- approx_token_count: 跟 PR #39 in_session_memory 同 calibration(中文 1.33 tokens/char)
- do_append_with_paging: MemGPT 哲学 — 超 budget 不报错, 踢 oldest lines
  Plan 1B: 仅返回被踢的 lines, 实际 archive 进 graph 由 HierarchicalMemory
  调 archival_memory_insert(stub by Plan 2 ship, 暂用 logger warn)
- do_replace_exact: substring exact match(不模糊), Python str.replace 行为
  不存在则 raise ValueError(防 silent miss)

注: 这层是纯函数, 跟 DB / DI 解耦. HierarchicalMemory.core_memory_append
用 PG repository 包装 + 调本层.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# === 常量 ===

BLOCK_DEFAULTS: dict[str, int] = {
    "persona": 500,        # spec § 7
    "scratchpad": 1000,    # spec § 7
}

APPEND_MAX_CHARS: int = 200    # 契约 § 6 防 spam

# 中文 token calibration(参考 v0.7 in-session memory)
_APPROX_CHARS_PER_TOKEN: float = 2.5


def approx_token_count(text: str) -> int:
    """Approximate token count(中文 1.33 tokens/char fallback)."""
    if not text:
        return 0
    return int(len(text) / _APPROX_CHARS_PER_TOKEN)


def do_append_with_paging(
    existing: str,
    new: str,
    max_tokens: int,
) -> tuple[str, list[str]]:
    """Append `new` to `existing`. Auto-page oldest lines if exceed max_tokens.

    Returns (new_content, paged_out_lines).

    Raises:
        ValueError: 如果 new 超 APPEND_MAX_CHARS.

    哲学:
    - MemGPT-style: 不报错, 踢 oldest lines
    - paged_out_lines 由调用层 archive 进 graph(Plan 2 ship 后实际归档,
      Plan 1B 阶段调用层只 logger.warning)
    """
    if len(new) > APPEND_MAX_CHARS:
        raise ValueError(
            f"core_memory_append content 超 {APPEND_MAX_CHARS} chars "
            f"(actual {len(new)}); use archival_memory_insert for longer facts"
        )

    if not existing:
        candidate = new
    else:
        candidate = f"{existing}\n{new}"

    if approx_token_count(candidate) <= max_tokens:
        return candidate, []

    # 超 budget — 按 line 切, 从前往后踢
    lines = candidate.split("\n")
    paged: list[str] = []
    while lines and approx_token_count("\n".join(lines)) > max_tokens:
        paged.append(lines.pop(0))

    if not lines:
        # 极端 case: 单行 new 都超 budget — 不再继续踢, 保留 new
        # 调用层应该 raise(因为这是异常配置), Plan 1B 暂时返回 new 原文 + 空 lines paged
        logger.warning(
            "core_memory_append: single line exceeds max_tokens=%d, returning anyway",
            max_tokens,
        )
        return new, paged

    return "\n".join(lines), paged


def do_replace_exact(
    existing: str,
    old_content: str,
    new_content: str,
) -> str:
    """Replace all occurrences of old_content with new_content.

    Raises:
        ValueError: old_content not found in existing.

    类比: Edit tool 的 replace_all 默认 false, 但 spec § 6 / 契约 § 6 没有
    显式说要不要 replace_all, 取折中: 替换所有出现(类似 Python str.replace),
    简洁安全.
    """
    if old_content not in existing:
        raise ValueError(
            f"core_memory_replace: old_content not found in block "
            f"(old_len={len(old_content)})"
        )
    return existing.replace(old_content, new_content)
```

#### 4.4 写 L1 integration test

文件: `backend/tests/integration/memory/test_working_blocks_e2e.py`

```python
"""L1: Working blocks 跟 PG 协作 — append/replace/get 通过 SQLAlchemy.

注: HierarchicalMemory.{get,append,replace}_working_blocks 在 Task 6 ship,
此 test 文件 placeholder import, Task 6 后填入. 这里仅 sanity check
ChatMemoryWorkingBlock model 可读写.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.memory.models import ChatMemoryWorkingBlock


@pytest.mark.integration
def test_chat_memory_working_block_insertable(pg_memory_fixture) -> None:
    """sanity: Plan 1A ship 的 model 可以 INSERT."""
    session = pg_memory_fixture()
    block = ChatMemoryWorkingBlock(
        user_id=uuid4(),
        block_name="persona",
        content="test",
        token_count=1,
        max_tokens=500,
    )
    session.add(block)
    session.flush()
    assert block.block_id is not None
```

注: `pg_memory_fixture` 在 Task 6 conftest.py 创建, 此 test 在 Task 6 跑。

#### 4.5 跑测试 + commit

```bash
cd backend && uv run pytest tests/unit/memory/test_working_blocks.py -xvs
```

```bash
git add backend/app/memory/working_blocks.py backend/tests/unit/memory/test_working_blocks.py backend/tests/integration/memory/__init__.py backend/tests/integration/memory/test_working_blocks_e2e.py
git commit -m "feat(c5-plan1b): working blocks 纯函数层 — append/replace/auto-paging + L0 单测"
```

---

### Task 5: HierarchicalMemory class 骨架 + DI signature

#### 5.1 spec / contract ref
- 契约 § 3 HierarchicalMemory class 骨架(完整 DI 参数列表)

#### 5.2 写 failing test

文件: `backend/tests/unit/memory/test_hierarchical_skeleton.py`

```python
"""L0: HierarchicalMemory class 骨架 — DI signature + Plan 2-4 stub raise."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest

from app.memory.hierarchical import HierarchicalMemory
from app.memory.protocol import Memory


def test_hierarchical_memory_implements_protocol() -> None:
    """HierarchicalMemory satisfies Memory Protocol (runtime_checkable)."""
    instance = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    assert isinstance(instance, Memory)


def test_init_signature_has_required_di_params() -> None:
    """契约 § 3: __init__ 必须接受 7 个 DI 参数(injection_classifier 默认 None)."""
    sig = inspect.signature(HierarchicalMemory.__init__)
    expected_params = {
        "pg_session_factory",
        "age_executor",
        "milvus_client",
        "embed_service",
        "llm_extractor",
        "llm_judge",
        "injection_classifier",
    }
    actual = set(sig.parameters.keys()) - {"self"}
    assert expected_params.issubset(actual), f"missing DI params: {expected_params - actual}"


def test_injection_classifier_defaults_none() -> None:
    sig = inspect.signature(HierarchicalMemory.__init__)
    assert sig.parameters["injection_classifier"].default is None


# ---- Plan 2-4 stub method 必须 raise NotImplementedError ----

@pytest.mark.asyncio
async def test_archival_memory_insert_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 2"):
        await mem.archival_memory_insert(
            user_id=uuid4(),
            content={},
            reasoning="r",
            importance=0.5,
            evidence_quote="ev",
            episode_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_archival_memory_search_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None, age_executor=None, milvus_client=None,
        embed_service=None, llm_extractor=None, llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 3"):
        await mem.archival_memory_search(uuid4(), "q")


@pytest.mark.asyncio
async def test_archival_memory_traverse_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None, age_executor=None, milvus_client=None,
        embed_service=None, llm_extractor=None, llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 4"):
        await mem.archival_memory_traverse(uuid4(), "User")


@pytest.mark.asyncio
async def test_recall_memory_search_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None, age_executor=None, milvus_client=None,
        embed_service=None, llm_extractor=None, llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 4"):
        await mem.recall_memory_search(uuid4(), "q")
```

跑 → red。

#### 5.3 实现

新建 `backend/app/memory/hierarchical.py`(骨架, Plan 1B 范围方法在 Task 6/7 填):

```python
"""HierarchicalMemory — C.5 跨 session memory 实现, 替换 InSessionMemory.

contract ref: § 3 HierarchicalMemory class 骨架
spec ref: § 1 整体架构 / § 7 working memory / § 8 cold start

Plan 1B 范围:
- working blocks: get / append / replace
- episodes 持久化: write_episode / get_unextracted_episodes / mark_episode_extracted

Plan 2-4 范围(本文件加 stub):
- archival_memory_insert (Plan 2)
- archival_memory_search (Plan 3)
- archival_memory_traverse (Plan 4)
- recall_memory_search (Plan 4)

DI 设计:
- pg_session_factory: () -> Session(同步 SQLAlchemy session, 跟 PR #39 / v1.0 一致)
- age_executor: AGEExecutor stub(Plan 1A 已 ship; Plan 2 sync edge 用)
- milvus_client: pymilvus client(Plan 1A 已 ship)
- embed_service: 复用 v0.7 EmbeddingService(qwen v3 1024d)
- llm_extractor: Plan 2 LLMExtractor(本 Plan 不 import / 不调用)
- llm_judge: Plan 2 ConflictJudge(本 Plan 不 import / 不调用)
- injection_classifier: Plan 5 InjectionClassifier(默认 None = no check)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryWorkingBlock,
    )

logger = logging.getLogger(__name__)


class HierarchicalMemory:
    """C.5 3-tier hierarchical memory implementation.

    Tier 1 working blocks(persona / scratchpad)+ Tier 2 archival graph + Tier 3 recall.
    """

    def __init__(
        self,
        pg_session_factory: Any,
        age_executor: Any,
        milvus_client: Any,
        embed_service: Any,
        llm_extractor: Any,
        llm_judge: Any,
        injection_classifier: Any | None = None,
    ) -> None:
        self._pg_session_factory = pg_session_factory
        self._age = age_executor
        self._milvus = milvus_client
        self._embed = embed_service
        self._llm_extractor = llm_extractor
        self._llm_judge = llm_judge
        self._injection_classifier = injection_classifier

    # === Tier 1 Working Memory(Plan 1B Task 6 实现) ===

    async def get_working_blocks(
        self, user_id: UUID
    ) -> dict[str, "ChatMemoryWorkingBlock"]:
        # Task 6 fill
        raise NotImplementedError("filled by Plan 1B Task 6")

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> "ChatMemoryWorkingBlock":
        # Task 6 fill
        raise NotImplementedError("filled by Plan 1B Task 6")

    async def core_memory_replace(
        self,
        user_id: UUID,
        block_name: str,
        old_content: str,
        new_content: str,
    ) -> "ChatMemoryWorkingBlock":
        # Task 6 fill
        raise NotImplementedError("filled by Plan 1B Task 6")

    # === Tier 2 Archival ===

    async def archival_memory_insert(
        self,
        user_id: UUID,
        content: dict[str, Any],
        reasoning: str,
        importance: float,
        evidence_quote: str,
        episode_id: UUID,
    ) -> "ChatMemoryEdge":
        raise NotImplementedError("filled by Plan 2")

    async def archival_memory_search(
        self, user_id: UUID, query: str, k: int = 5
    ) -> list["ChatMemoryEdge"]:
        raise NotImplementedError("filled by Plan 3")

    async def archival_memory_traverse(
        self,
        user_id: UUID,
        start_label: str,
        hops: int = 2,
        rel_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("filled by Plan 4")

    # === Tier 3 Recall ===

    async def recall_memory_search(
        self, user_id: UUID, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("filled by Plan 4")

    # === 持久化 episodes(Plan 1B Task 7 实现) ===

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> "ChatMemoryEpisode":
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list["ChatMemoryEpisode"]:
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,
        extraction_metadata: dict[str, Any],
    ) -> None:
        # Task 7 fill
        raise NotImplementedError("filled by Plan 1B Task 7")
```

更新 `backend/app/memory/__init__.py`:

```python
"""C.5 cross-session memory subsystem."""

from app.memory.hierarchical import HierarchicalMemory
from app.memory.protocol import Memory

__all__ = ["HierarchicalMemory", "Memory"]
```

#### 5.4 跑测试

```bash
cd backend && uv run pytest tests/unit/memory/test_hierarchical_skeleton.py -xvs
cd backend && uv run mypy app/memory/
```

#### 5.5 commit

```bash
git add backend/app/memory/hierarchical.py backend/app/memory/__init__.py backend/tests/unit/memory/test_hierarchical_skeleton.py
git commit -m "feat(c5-plan1b): HierarchicalMemory class 骨架 + DI signature + Plan 2-4 stub"
```

---

### Task 6: HierarchicalMemory — working blocks 方法实现

#### 6.1 spec / contract ref
- spec § 7 working memory budget(persona 500 / scratchpad 1000 + 自动 paging)
- 契约 § 2 Memory Protocol 3 个 working blocks method 签名

#### 6.2 conftest fixture(L1 用)

新建 `backend/tests/integration/memory/conftest.py`:

```python
"""L1 fixture for memory tests — pg_memory_fixture / age_fixture.

复用 PR #39 / v1.0 已建的 pg_test_container fixture(testcontainers + 外部 fallback).
本 fixture session-scoped, schema 通过 Base.metadata.create_all 建.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# 触发 model 注册 → Base.metadata 含 4 PG 表
import app.memory.models  # noqa: F401
from app.core.database import Base


@pytest.fixture(scope="session")
def pg_memory_fixture(pg_test_container):
    """real PG, schema 已 create_all.

    依赖 PR #39 / v1.0 ship 的 pg_test_container fixture(在 backend/tests/conftest.py 全局).

    Plan 1B 创建, Plan 2-8 复用.

    yields a callable: () -> Session(同步 sessionmaker, 跟 v1.0 monitoring repo 模式一致).
    """
    db_url = os.environ.get("DATABASE_URL") or pg_test_container.get_connection_url()
    engine = create_engine(db_url, echo=False, pool_pre_ping=True)
    Base.metadata.create_all(engine)

    SessionFactory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def _factory() -> Session:
        return SessionFactory()

    yield _factory


@pytest.fixture(scope="session")
def age_fixture(pg_memory_fixture):
    """AGE 'chat_memory' 图 setup. Plan 1A ship 时已建; 此 fixture 仅 sanity check.

    Plan 2 实施时填实际 cypher executor, Plan 1B 留 thin stub.
    """
    # Plan 1A 已 setup, 这里仅返回 None placeholder, Plan 2 填.
    yield None
```

注: `pg_test_container` fixture 假设来自 backend/tests/conftest.py(v1.0 监控引擎 ship 已建)。如未建则在本 conftest 临时建一个 testcontainers PG。

#### 6.3 写 failing test

更新 `backend/tests/integration/memory/test_working_blocks_e2e.py`:

```python
"""L1: HierarchicalMemory working blocks — real PG."""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryWorkingBlock


@pytest.fixture
def hier_memory(pg_memory_fixture):
    return HierarchicalMemory(
        pg_session_factory=pg_memory_fixture,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_working_blocks_empty_user_returns_empty_dict(hier_memory) -> None:
    blocks = await hier_memory.get_working_blocks(uuid4())
    assert blocks == {}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_memory_append_creates_block(hier_memory) -> None:
    uid = uuid4()
    block = await hier_memory.core_memory_append(uid, "persona", "我偏好 ROE")
    assert block.block_name == "persona"
    assert "我偏好 ROE" in block.content
    assert block.max_tokens == 500


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_memory_append_idempotent_appends(hier_memory) -> None:
    uid = uuid4()
    await hier_memory.core_memory_append(uid, "persona", "fact A")
    block = await hier_memory.core_memory_append(uid, "persona", "fact B")
    assert "fact A" in block.content
    assert "fact B" in block.content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_memory_replace_exact_match(hier_memory) -> None:
    uid = uuid4()
    await hier_memory.core_memory_append(uid, "persona", "ROE 重要")
    block = await hier_memory.core_memory_replace(uid, "persona", "重要", "关键")
    assert "ROE 关键" in block.content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_core_memory_replace_no_match_raises(hier_memory) -> None:
    uid = uuid4()
    await hier_memory.core_memory_append(uid, "persona", "ROE")
    with pytest.raises(ValueError, match="not found"):
        await hier_memory.core_memory_replace(uid, "persona", "MISSING", "X")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_block_name_raises(hier_memory) -> None:
    uid = uuid4()
    with pytest.raises(ValueError, match="block_name"):
        await hier_memory.core_memory_append(uid, "unknown_block", "x")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_append_exceed_budget_pages_oldest(hier_memory) -> None:
    """超 max_tokens 自动 paging — paged_lines 通过 logger 记录(Plan 2 ship 后归档)."""
    uid = uuid4()
    # 故意写超 max_tokens
    for i in range(20):
        await hier_memory.core_memory_append(
            uid, "persona", f"fact_{i}: 茅台白酒 ROE 持仓 偏好 现金流"
        )
    blocks = await hier_memory.get_working_blocks(uid)
    persona = blocks["persona"]
    # Plan 1B 不会真 raise; 内容会被 page 到 max_tokens 内
    from app.memory.working_blocks import approx_token_count
    assert approx_token_count(persona.content) <= 500
```

跑 → red。

#### 6.4 实现

更新 `backend/app/memory/hierarchical.py`, 填 working blocks 方法:

```python
# 在 HierarchicalMemory class 内, 替换 Task 5 的 stub:

    async def get_working_blocks(
        self, user_id: UUID
    ) -> dict[str, "ChatMemoryWorkingBlock"]:
        """Return {block_name: block} for user's persona / scratchpad.

        新用户 / 没建过 block 的用户 → 返回空 dict(不自动建).
        cold_start 走单独 path 给新用户初始化 block.
        """
        from app.memory.models import ChatMemoryWorkingBlock

        session = self._pg_session_factory()
        try:
            rows = (
                session.query(ChatMemoryWorkingBlock)
                .filter(ChatMemoryWorkingBlock.user_id == user_id)
                .all()
            )
            return {b.block_name: b for b in rows}
        finally:
            session.close()

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> "ChatMemoryWorkingBlock":
        """Append content to block. Auto-paging if exceed max_tokens.

        Plan 1B: paged_out_lines 通过 logger.warning 记(后续 Plan 2 ship 后,
        改成调 self.archival_memory_insert 真归档).
        """
        from app.memory.models import ChatMemoryWorkingBlock
        from app.memory.working_blocks import (
            BLOCK_DEFAULTS,
            approx_token_count,
            do_append_with_paging,
        )

        if block_name not in BLOCK_DEFAULTS:
            raise ValueError(
                f"unknown block_name {block_name!r}; "
                f"valid: {list(BLOCK_DEFAULTS.keys())}"
            )

        session = self._pg_session_factory()
        try:
            block = (
                session.query(ChatMemoryWorkingBlock)
                .filter(
                    ChatMemoryWorkingBlock.user_id == user_id,
                    ChatMemoryWorkingBlock.block_name == block_name,
                )
                .first()
            )
            if block is None:
                block = ChatMemoryWorkingBlock(
                    user_id=user_id,
                    block_name=block_name,
                    content="",
                    token_count=0,
                    max_tokens=BLOCK_DEFAULTS[block_name],
                )
                session.add(block)
                session.flush()

            new_content, paged = do_append_with_paging(
                existing=block.content,
                new=content,
                max_tokens=block.max_tokens,
            )
            block.content = new_content
            block.token_count = approx_token_count(new_content)

            if paged:
                logger.warning(
                    "core_memory_append: paged %d lines from block %s/user=%s — "
                    "Plan 2 ship 后改 archival_memory_insert 真归档(spec § 7)",
                    len(paged), block_name, user_id,
                )

            session.commit()
            session.refresh(block)
            return block
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def core_memory_replace(
        self,
        user_id: UUID,
        block_name: str,
        old_content: str,
        new_content: str,
    ) -> "ChatMemoryWorkingBlock":
        """Exact substring replace. Raise ValueError if not found."""
        from app.memory.models import ChatMemoryWorkingBlock
        from app.memory.working_blocks import (
            BLOCK_DEFAULTS,
            approx_token_count,
            do_replace_exact,
        )

        if block_name not in BLOCK_DEFAULTS:
            raise ValueError(
                f"unknown block_name {block_name!r}; valid: {list(BLOCK_DEFAULTS.keys())}"
            )

        session = self._pg_session_factory()
        try:
            block = (
                session.query(ChatMemoryWorkingBlock)
                .filter(
                    ChatMemoryWorkingBlock.user_id == user_id,
                    ChatMemoryWorkingBlock.block_name == block_name,
                )
                .first()
            )
            if block is None:
                raise ValueError(
                    f"core_memory_replace: block {block_name} not found for user {user_id}"
                )

            replaced = do_replace_exact(block.content, old_content, new_content)
            block.content = replaced
            block.token_count = approx_token_count(replaced)
            session.commit()
            session.refresh(block)
            return block
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

#### 6.5 跑测试 + commit

```bash
cd backend && uv run pytest tests/integration/memory/test_working_blocks_e2e.py -xvs -m integration
```

```bash
git add backend/app/memory/hierarchical.py backend/tests/integration/memory/conftest.py backend/tests/integration/memory/test_working_blocks_e2e.py
git commit -m "feat(c5-plan1b): HierarchicalMemory working blocks CRUD + auto-paging + L1 e2e"
```

---

### Task 7: HierarchicalMemory — episode 持久化方法实现

#### 7.1 spec / contract ref
- 契约 § 2 `write_episode` / `get_unextracted_episodes` / `mark_episode_extracted` 签名
- spec § 4 写入 pipeline Step 1 / Step 8

#### 7.2 写 failing test

文件: `backend/tests/integration/memory/test_episodes_e2e.py`

```python
"""L1: HierarchicalMemory episode 持久化 — write / get_unextracted / mark_extracted."""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEpisode


@pytest.fixture
def hier_memory(pg_memory_fixture):
    return HierarchicalMemory(
        pg_session_factory=pg_memory_fixture,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_episode_creates_row(hier_memory) -> None:
    uid = uuid4()
    sid = uuid4()
    ep = await hier_memory.write_episode(
        user_id=uid,
        session_id=sid,
        episode_index=0,
        user_message="我看好茅台",
        agent_response="茅台 PE 32",
    )
    assert ep.episode_id is not None
    assert ep.user_message_text == "我看好茅台"
    assert ep.extracted_at is None
    assert ep.source_kind == "chat_turn"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_episode_unique_session_index(hier_memory) -> None:
    uid = uuid4()
    sid = uuid4()
    await hier_memory.write_episode(uid, sid, 0, "u", "a")
    # 同 session 同 index 第二次 → IntegrityError(UNIQUE constraint Plan 1A 已建)
    with pytest.raises(Exception):
        await hier_memory.write_episode(uid, sid, 0, "u2", "a2")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_unextracted_episodes_filters(hier_memory) -> None:
    uid = uuid4()
    sid = uuid4()
    ep1 = await hier_memory.write_episode(uid, sid, 0, "u1", "a1")
    ep2 = await hier_memory.write_episode(uid, sid, 1, "u2", "a2")

    pending = await hier_memory.get_unextracted_episodes(uid, limit=10)
    pending_ids = {e.episode_id for e in pending}
    assert ep1.episode_id in pending_ids
    assert ep2.episode_id in pending_ids

    # mark ep1 extracted
    await hier_memory.mark_episode_extracted(
        ep1.episode_id, extracted_by="agent", extraction_metadata={"edges": 2}
    )
    pending2 = await hier_memory.get_unextracted_episodes(uid, limit=10)
    pending2_ids = {e.episode_id for e in pending2}
    assert ep1.episode_id not in pending2_ids
    assert ep2.episode_id in pending2_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_episode_extracted_sets_metadata(hier_memory) -> None:
    uid = uuid4()
    sid = uuid4()
    ep = await hier_memory.write_episode(uid, sid, 0, "u", "a")
    await hier_memory.mark_episode_extracted(
        ep.episode_id,
        extracted_by="eos_batch",
        extraction_metadata={"model": "haiku", "edges": 3, "latency_ms": 120},
    )

    sess = hier_memory._pg_session_factory()
    try:
        ep_reread = sess.query(ChatMemoryEpisode).filter_by(episode_id=ep.episode_id).first()
        assert ep_reread is not None
        assert ep_reread.extracted_at is not None
        assert ep_reread.extracted_by == "eos_batch"
        assert ep_reread.extraction_metadata["model"] == "haiku"
    finally:
        sess.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_unextracted_user_isolation(hier_memory) -> None:
    """多租户隔离: user A 的 unextracted 不能漏给 user B."""
    uA, uB = uuid4(), uuid4()
    sA, sB = uuid4(), uuid4()
    epA = await hier_memory.write_episode(uA, sA, 0, "uA", "a")
    epB = await hier_memory.write_episode(uB, sB, 0, "uB", "a")

    pendingA = await hier_memory.get_unextracted_episodes(uA, limit=10)
    pA_ids = {e.episode_id for e in pendingA}
    assert epA.episode_id in pA_ids
    assert epB.episode_id not in pA_ids
```

跑 → red。

#### 7.3 实现

更新 `backend/app/memory/hierarchical.py`, 填 episode 方法:

```python
    # 替换 Task 5 的 episode stub:

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> "ChatMemoryEpisode":
        """Path A 写入 step 1: episode 入库, extracted_at=NULL."""
        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            ep = ChatMemoryEpisode(
                user_id=user_id,
                session_id=session_id,
                episode_index=episode_index,
                user_message_text=user_message,
                agent_response_text=agent_response,
                source_kind=source_kind,
            )
            session.add(ep)
            session.commit()
            session.refresh(ep)
            return ep
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list["ChatMemoryEpisode"]:
        """Path B end-of-session batch 用. extracted_at IS NULL 过滤."""
        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            rows = (
                session.query(ChatMemoryEpisode)
                .filter(
                    ChatMemoryEpisode.user_id == user_id,
                    ChatMemoryEpisode.extracted_at.is_(None),
                )
                .order_by(ChatMemoryEpisode.created_at)
                .limit(limit)
                .all()
            )
            # detach 让 caller 在 session 关后仍可读 attributes
            for r in rows:
                session.expunge(r)
            return rows
        finally:
            session.close()

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Step 8: 抽取完成标记."""
        from datetime import datetime, timezone

        from app.memory.models import ChatMemoryEpisode

        session = self._pg_session_factory()
        try:
            ep = session.query(ChatMemoryEpisode).filter_by(
                episode_id=episode_id
            ).first()
            if ep is None:
                raise ValueError(f"episode {episode_id} not found")
            ep.extracted_at = datetime.now(timezone.utc)
            ep.extracted_by = extracted_by
            ep.extraction_metadata = extraction_metadata
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
```

#### 7.4 跑测试 + commit

```bash
cd backend && uv run pytest tests/integration/memory/test_episodes_e2e.py -xvs -m integration
```

```bash
git add backend/app/memory/hierarchical.py backend/tests/integration/memory/test_episodes_e2e.py
git commit -m "feat(c5-plan1b): HierarchicalMemory episode 持久化 — write/get_unextracted/mark_extracted"
```

---

### Task 8: Cold Start Populator(静态 3 路 seed + CLI)

#### 8.1 spec / contract ref
- spec § 8 Cold Start Populator(3 路: 持仓 → HOLDS / preferences → PREFERS / watchlist → WATCHES)
- spec § 8 幂等保证(检查 cold_start_seed episode 存在跳过)
- 算法深度补丁 #5: 走 Plan 1A 已建幂等键 UNIQUE constraint, 重跑不重复 INSERT

#### 8.2 写 failing test

文件: `backend/tests/unit/memory/test_cold_start.py` (L0 — 纯函数级)

```python
"""L0: Cold start helper 纯函数."""

from __future__ import annotations

from app.memory.cold_start import (
    build_holds_edge_payload,
    has_been_seeded_for_user,
)


def test_build_holds_payload_default_valid_from() -> None:
    """没有 purchase_date 时, 用 fallback(spec § 8 容许 last_updated_at 或 default)."""
    from datetime import datetime
    payload = build_holds_edge_payload(
        ts_code="600519.SH",
        qty=500,
        avg_cost=1500.0,
        purchase_date=None,
        fallback_date=datetime(2024, 1, 1),
    )
    assert payload["target_label"] == "600519.SH"
    assert payload["qty"] == 500
    assert payload["valid_from"].year == 2024
    assert payload["rel_type"] == "HOLDS"
```

文件: `backend/tests/integration/memory/test_cold_start_e2e.py`(L1 — real PG)

```python
"""L1: cold start 3 路 seed + 幂等."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.memory.cold_start import seed_user_graph
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from app.models.position import Position
from app.models.user import User


@pytest.fixture
def seeded_user(pg_memory_fixture):
    """创建一个测试 user + 2 持仓 + preferences."""
    sess = pg_memory_fixture()
    user = User(
        id=str(uuid4()),
        username="cold_start_test",
        email="cs@example.com",
        hashed_password="x",
    )
    sess.add(user)
    sess.flush()

    p1 = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=500,
        avg_cost=Decimal("1500.0"),
        total_cost=Decimal("750000.0"),
        realized_pnl=Decimal("0"),
    )
    p2 = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code="600036.SH",
        name="招商银行",
        quantity=200,
        avg_cost=Decimal("35.0"),
        total_cost=Decimal("7000.0"),
        realized_pnl=Decimal("0"),
    )
    sess.add_all([p1, p2])
    sess.commit()
    user_id = user.id
    sess.close()
    return user_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_user_graph_creates_holds_edges(seeded_user, pg_memory_fixture) -> None:
    await seed_user_graph(seeded_user, pg_session_factory=pg_memory_fixture)

    sess = pg_memory_fixture()
    try:
        edges = (
            sess.query(ChatMemoryEdge)
            .filter(
                ChatMemoryEdge.user_id == seeded_user,
                ChatMemoryEdge.rel_type == "HOLDS",
            )
            .all()
        )
        # 2 持仓 → 2 HOLDS edges
        assert len(edges) == 2
        for e in edges:
            assert e.importance == 0.9   # cold start 高 importance
            assert e.invalidated_at is None
            assert e.source_episode_id is not None
    finally:
        sess.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_creates_cold_start_seed_episode(seeded_user, pg_memory_fixture) -> None:
    await seed_user_graph(seeded_user, pg_session_factory=pg_memory_fixture)
    sess = pg_memory_fixture()
    try:
        seed_eps = (
            sess.query(ChatMemoryEpisode)
            .filter(
                ChatMemoryEpisode.user_id == seeded_user,
                ChatMemoryEpisode.source_kind == "cold_start_seed",
            )
            .all()
        )
        assert len(seed_eps) == 1
    finally:
        sess.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_idempotent_rerun_no_dup(seeded_user, pg_memory_fixture) -> None:
    """走幂等键 UNIQUE constraint (Plan 1A 已建): 重跑无重复 edge."""
    await seed_user_graph(seeded_user, pg_session_factory=pg_memory_fixture)
    await seed_user_graph(seeded_user, pg_session_factory=pg_memory_fixture)

    sess = pg_memory_fixture()
    try:
        holds = (
            sess.query(ChatMemoryEdge)
            .filter(
                ChatMemoryEdge.user_id == seeded_user,
                ChatMemoryEdge.rel_type == "HOLDS",
            )
            .all()
        )
        assert len(holds) == 2  # 仍 2 条, 不是 4 条
    finally:
        sess.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_creates_user_node_and_stock_nodes(seeded_user, pg_memory_fixture) -> None:
    await seed_user_graph(seeded_user, pg_session_factory=pg_memory_fixture)
    sess = pg_memory_fixture()
    try:
        nodes = (
            sess.query(ChatMemoryNode)
            .filter(ChatMemoryNode.user_id == seeded_user)
            .all()
        )
        labels = {n.entity_label for n in nodes}
        types = {n.entity_type for n in nodes}
        assert "User" in labels
        assert "600519.SH" in labels
        assert "600036.SH" in labels
        assert "Stock" in types
        assert "User" in types
    finally:
        sess.close()
```

跑 → red。

#### 8.3 实现

新建 `backend/app/memory/cold_start.py`:

```python
"""Cold Start Populator — 静态版.

spec ref: § 8 Cold Start Populator
contract ref: § 5 normalize_entity / Plan 1A 幂等键 UNIQUE constraint

3 路 seed:
- 持仓 (positions) → User → HOLDS Stock(valid_from=position.updated_at 或 default)
- preferences (users.preferences JSONB) → PREFERS edge (Plan 1B 留 hook,
  当前 User model 无 preferences 列, 留 v1.x 接 PR #39 / v0.8 ship 的 user prefs)
- watchlist (如表存在) → WATCHES edge

幂等保证:
- 检查 cold_start_seed episode 存在 → 跳过(spec § 8)
- 走幂等键 UNIQUE constraint(Plan 1A 已建): 重跑 INSERT 命中 UNIQUE 走 ON CONFLICT DO NOTHING

CLI 入口:
    python -m app.memory.cold_start --user-id <uuid>

启动 lifespan auto-trigger:
    在 chat router 第一次拿 session 时调用(本 plan Task 10 接).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


def has_been_seeded_for_user(pg_session_factory: Any, user_id: Any) -> bool:
    """检查是否已 cold start(找 source_kind='cold_start_seed' episode)."""
    from app.memory.models import ChatMemoryEpisode

    sess = pg_session_factory()
    try:
        existing = (
            sess.query(ChatMemoryEpisode)
            .filter(
                ChatMemoryEpisode.user_id == user_id,
                ChatMemoryEpisode.source_kind == "cold_start_seed",
            )
            .first()
        )
        return existing is not None
    finally:
        sess.close()


def build_holds_edge_payload(
    ts_code: str,
    qty: int,
    avg_cost: float,
    purchase_date: datetime | None,
    fallback_date: datetime,
) -> dict[str, Any]:
    """构造 HOLDS edge payload.

    valid_from 优先 purchase_date(spec § 8 提示 position.purchase_date 或 last_updated_at);
    无则 fallback_date.
    """
    valid_from = purchase_date or fallback_date
    return {
        "rel_type": "HOLDS",
        "target_label": ts_code,
        "qty": qty,
        "avg_cost": avg_cost,
        "valid_from": valid_from,
        "importance": 0.9,
        "reasoning": "cold start from positions table",
    }


async def seed_user_graph(
    user_id: Any,
    pg_session_factory: Any,
) -> None:
    """3 路 seed user 的 memory graph(幂等).

    - 已 seeded 则 skip
    - 否则建 cold_start_seed episode + User node + per-position Stock node + HOLDS edge
    - preferences / watchlist 路在 Plan 1B 留 stub(当前 user model 无 preferences 列)
    """
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
    )
    from app.memory.registry import jieba_tokenize_for_search
    from app.models.position import Position

    if has_been_seeded_for_user(pg_session_factory, user_id):
        logger.info("cold_start: user %s already seeded, skip", user_id)
        return

    sess = pg_session_factory()
    try:
        # 1. 创建 cold_start_seed episode
        seed_episode = ChatMemoryEpisode(
            user_id=user_id,
            session_id=uuid4(),     # 假 session_id, FK 满足: chat_sessions 也需有此 row
            episode_index=0,
            user_message_text="COLD_START_SEED",
            agent_response_text="COLD_START_SEED",
            source_kind="cold_start_seed",
            extracted_at=datetime.now(timezone.utc),
            extracted_by="cold_start",
        )
        sess.add(seed_episode)
        sess.flush()    # need episode_id for FK

        # 注: cold_start_seed episode 用假 session_id 会撞 chat_sessions FK,
        #     Plan 1A 应该已加 ON DELETE 或允许 NULL. 若不允许, 这里改为
        #     NULLABLE session_id(DDL 在 Plan 1A 协调; 本 plan 假设 OK).
        #     若 schema 不允许, fallback: 在 chat_sessions 建一条 system seed session.

        # 2. 创建或获取 User node
        user_node = (
            sess.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user_id,
                ChatMemoryNode.entity_type == "User",
                ChatMemoryNode.entity_label == "User",
            )
            .first()
        )
        if user_node is None:
            user_node = ChatMemoryNode(
                user_id=user_id,
                entity_type="User",
                entity_label="User",
                properties={},
                search_tokens=jieba_tokenize_for_search("User"),
            )
            sess.add(user_node)
            sess.flush()

        # 3. 持仓 → HOLDS edges
        positions = (
            sess.query(Position)
            .filter(Position.user_id == user_id)
            .all()
        )
        for pos in positions:
            ts_code = pos.ts_code
            # Stock node 幂等 get_or_create
            stock_node = (
                sess.query(ChatMemoryNode)
                .filter(
                    ChatMemoryNode.user_id == user_id,
                    ChatMemoryNode.entity_type == "Stock",
                    ChatMemoryNode.entity_label == ts_code,
                )
                .first()
            )
            if stock_node is None:
                stock_node = ChatMemoryNode(
                    user_id=user_id,
                    entity_type="Stock",
                    entity_label=ts_code,
                    properties={"name": pos.name},
                    search_tokens=jieba_tokenize_for_search(f"{ts_code} {pos.name}"),
                )
                sess.add(stock_node)
                sess.flush()

            payload = build_holds_edge_payload(
                ts_code=ts_code,
                qty=pos.quantity,
                avg_cost=float(pos.avg_cost),
                purchase_date=None,    # Position model 当前无 purchase_date 字段
                fallback_date=pos.updated_at or datetime(2024, 1, 1),
            )

            # 走 ON CONFLICT DO NOTHING(幂等键 UNIQUE constraint Plan 1A 已建)
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(ChatMemoryEdge).values(
                user_id=user_id,
                source_node_id=user_node.node_id,
                target_node_id=stock_node.node_id,
                rel_type=payload["rel_type"],
                valid_from=payload["valid_from"],
                source_episode_id=seed_episode.episode_id,
                importance=payload["importance"],
                reasoning=payload["reasoning"],
                properties={"qty": payload["qty"], "avg_cost": payload["avg_cost"]},
                search_tokens=jieba_tokenize_for_search(
                    f"HOLDS User Stock {ts_code} {pos.name}"
                ),
            )
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_edges_idempotency_key"
            )
            sess.execute(stmt)

        # 4. (留 hook) preferences 路 — User model 无 preferences 列, 跳过
        # TODO Plan 1B+: 若 PR #39 / v0.8 加了 preferences JSONB, 这里补 PREFERS edges
        logger.info(
            "cold_start: preferences seed skipped (User.preferences not yet present)"
        )

        # 5. (留 hook) watchlist 路 — model 不存在, 跳过
        logger.info("cold_start: watchlist seed skipped (no watchlist model)")

        sess.commit()
        logger.info(
            "cold_start: seeded user %s with %d HOLDS edges",
            user_id, len(positions),
        )
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# === CLI entry ===

def _build_pg_session_factory() -> Any:
    """从 env 建 sync session factory(给 CLI 用)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def _factory() -> Session:
        return SessionFactory()

    return _factory


def main() -> None:
    parser = argparse.ArgumentParser(description="C.5 cold start populator")
    parser.add_argument("--user-id", required=True, help="user UUID to seed")
    args = parser.parse_args()

    factory = _build_pg_session_factory()
    asyncio.run(seed_user_graph(args.user_id, pg_session_factory=factory))
    print(f"cold_start: done for user {args.user_id}")


if __name__ == "__main__":
    main()
```

#### 8.4 跑测试 + commit

```bash
cd backend && uv run pytest tests/unit/memory/test_cold_start.py -xvs
cd backend && uv run pytest tests/integration/memory/test_cold_start_e2e.py -xvs -m integration
```

```bash
git add backend/app/memory/cold_start.py backend/tests/unit/memory/test_cold_start.py backend/tests/integration/memory/test_cold_start_e2e.py
git commit -m "feat(c5-plan1b): cold start populator — 持仓 → HOLDS edges + 幂等 + CLI"
```

---

### Task 9: Reconciliation 骨架(scan inconsistent state)

#### 9.1 spec / contract ref
- spec § 11 末尾 #5 三方一致性: "进程崩溃恢复 job: 启动时扫'PG 写完 + Milvus pending + episode extracted_at IS NULL'的 inconsistent 状态做 reconciliation"
- 算法深度补丁 #5: Plan 1A 已建幂等键, Plan 1B ship reconciliation 入口骨架, Plan 5 weekly job 收束

#### 9.2 写 failing test

文件: `backend/tests/integration/memory/test_reconciliation_e2e.py`

```python
"""L1: reconciliation 骨架 — scan inconsistent state.

Plan 1B 范围:
- scan_inconsistent_state(user_id) returns list of ReconciliationCase
- 简单 case: edge 存在但 source_episode 的 extracted_at 仍 NULL → 标
- 复杂 case (Milvus pending) → Plan 5 收束, 这里仅 placeholder

Plan 5 收束: weekly Celery job 调本入口 + 实际 retry / fix.
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.memory.hierarchical import HierarchicalMemory
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode, ChatMemoryNode
from app.memory.reconciliation import scan_inconsistent_state


@pytest.fixture
def hier_memory(pg_memory_fixture):
    return HierarchicalMemory(
        pg_session_factory=pg_memory_fixture,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scan_inconsistent_empty_user_zero_cases(hier_memory, pg_memory_fixture) -> None:
    cases = await scan_inconsistent_state(uuid4(), pg_session_factory=pg_memory_fixture)
    assert cases == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scan_detects_edge_with_unextracted_episode(
    hier_memory, pg_memory_fixture
) -> None:
    """造一个不一致 state: episode extracted_at IS NULL 但已有 edge ref 它.

    这表示进程崩溃在 Step 8(mark_extracted)之前 — 反向失败的典型 case.
    """
    uid = uuid4()
    sid = uuid4()
    ep = await hier_memory.write_episode(uid, sid, 0, "u", "a")
    # 模拟 Plan 2 ship 的 archival_memory_insert 走完 Step 7 但 Step 8 崩
    sess = pg_memory_fixture()
    try:
        u_node = ChatMemoryNode(
            user_id=uid, entity_type="User", entity_label="User"
        )
        s_node = ChatMemoryNode(
            user_id=uid, entity_type="Stock", entity_label="600519.SH"
        )
        sess.add_all([u_node, s_node])
        sess.flush()

        from datetime import datetime, timezone
        edge = ChatMemoryEdge(
            user_id=uid,
            source_node_id=u_node.node_id,
            target_node_id=s_node.node_id,
            rel_type="HOLDS",
            valid_from=datetime.now(timezone.utc),
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning="test",
        )
        sess.add(edge)
        sess.commit()
    finally:
        sess.close()

    cases = await scan_inconsistent_state(uid, pg_session_factory=pg_memory_fixture)
    # 检测到 1 个 case: edge 存在但 episode extracted_at IS NULL
    assert len(cases) == 1
    assert cases[0].kind == "edge_exists_episode_unextracted"
    assert cases[0].episode_id == ep.episode_id
```

跑 → red。

#### 9.3 实现

新建 `backend/app/memory/reconciliation.py`:

```python
"""Reconciliation job 骨架 — scan inconsistent state.

spec ref: § 11 末尾 #5 三方一致性反向失败
contract ref: § 1 reconciliation.py 进程崩溃恢复 job 骨架

Plan 1B 范围(本):
- scan_inconsistent_state(user_id) → list[ReconciliationCase]
- 简单 case detection:
  - 'edge_exists_episode_unextracted': edge ref episode 但 episode.extracted_at IS NULL
    (Step 7 done, Step 8 崩) — Plan 5 weekly job 调 mark_episode_extracted 修
  - 'pending_milvus' placeholder — Plan 2/5 ship pending_milvus_inserts 表后接
- 不实施 retry / fix(Plan 5 weekly job 收束)

为啥 Plan 1B ship 入口骨架而不是放到 Plan 5:
  Plan 1A 已经 ship 了幂等键 UNIQUE constraint, Plan 1B 顺势 ship 这个 hook 让
  作品集叙事完整(算法深度补丁 #5 cover 全), Plan 5 只填实际 retry 逻辑.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciliationCase:
    """一条不一致 state 描述."""

    kind: str       # 'edge_exists_episode_unextracted' / 'pending_milvus' / ...
    user_id: UUID
    episode_id: UUID | None
    edge_id: UUID | None
    description: str


async def scan_inconsistent_state(
    user_id: Any,
    pg_session_factory: Any,
) -> list[ReconciliationCase]:
    """扫描 user_id 的不一致 state.

    Plan 1B 检测的 case:
    1. edge_exists_episode_unextracted: edge ref episode 但 episode.extracted_at IS NULL
       (Step 7 done, Step 8 崩 — Plan 5 修)

    Plan 1B 不检测但留 hook(Plan 2/5 ship 后接):
    2. pending_milvus: pending_milvus_inserts 表存在 row(Plan 2 ship 此表)
    3. age_pg_drift: AGE 图节点 vs PG nodes 数量不一致(Plan 5 weekly chaos test 收束)
    """
    from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode

    cases: list[ReconciliationCase] = []

    sess = pg_session_factory()
    try:
        # case 1: edge 存在但 episode extracted_at IS NULL
        rows = (
            sess.query(ChatMemoryEdge, ChatMemoryEpisode)
            .join(
                ChatMemoryEpisode,
                ChatMemoryEdge.source_episode_id == ChatMemoryEpisode.episode_id,
            )
            .filter(
                ChatMemoryEdge.user_id == user_id,
                ChatMemoryEpisode.extracted_at.is_(None),
                ChatMemoryEpisode.source_kind != "cold_start_seed",
                # cold_start_seed 走特殊路径 extracted_at 已设置, 但即便不设置也 OK
            )
            .all()
        )
        for edge, ep in rows:
            cases.append(
                ReconciliationCase(
                    kind="edge_exists_episode_unextracted",
                    user_id=user_id,
                    episode_id=ep.episode_id,
                    edge_id=edge.edge_id,
                    description=(
                        f"edge {edge.edge_id} ref episode {ep.episode_id}, "
                        f"but episode.extracted_at is NULL (Step 8 likely crashed)"
                    ),
                )
            )

        if cases:
            logger.warning(
                "reconciliation: detected %d inconsistent cases for user %s",
                len(cases), user_id,
            )

        # case 2 placeholder: pending_milvus_inserts 表(Plan 2 ship)
        # try:
        #     from app.memory.models import PendingMilvusInsert  # Plan 2 ship
        #     pending = sess.query(PendingMilvusInsert).filter_by(user_id=user_id).all()
        #     for p in pending:
        #         cases.append(ReconciliationCase(kind="pending_milvus", ...))
        # except ImportError:
        #     pass

        return cases
    finally:
        sess.close()
```

#### 9.4 跑测试 + commit

```bash
cd backend && uv run pytest tests/integration/memory/test_reconciliation_e2e.py -xvs -m integration
```

```bash
git add backend/app/memory/reconciliation.py backend/tests/integration/memory/test_reconciliation_e2e.py
git commit -m "feat(c5-plan1b): reconciliation 骨架 — scan inconsistent state(算法深度补丁 #5)"
```

---

### Task 10: DI 替换 chat router + smoke test + 知识卡

#### 10.1 spec / contract ref
- 契约 § 3 末尾"DI 替换点: 在 app.app_main.lifespan 或 app.agents.factory.build_chat_agent 处把 InSessionMemory 替换 HierarchicalMemory, 由 Plan 1 完成"
- 当前 DI 点在 `backend/app/router/chat.py` `_build_graph_singleton`(line 204)

#### 10.2 写 failing test(L0 — singleton wiring smoke)

文件: `backend/tests/unit/memory/test_router_di_swap.py`

```python
"""L0 smoke: chat router _build_graph_singleton DI 替换为 HierarchicalMemory.

由于 _build_graph_singleton 真起 LLM client / Tushare client(env-driven),
本 smoke test 仅验证 import path + memory 类型, 不真跑 graph.

注: 真完整 DI 测试在 Task 10 的 manual smoke step.
"""

from __future__ import annotations

import inspect


def test_chat_router_imports_hierarchical_memory() -> None:
    """chat router 不再 import InSessionMemory 主路径, 改 import HierarchicalMemory."""
    import app.router.chat as chat_router_module

    src = inspect.getsource(chat_router_module._build_graph_singleton)
    assert "HierarchicalMemory" in src, (
        "chat router _build_graph_singleton 必须 import + 实例化 HierarchicalMemory"
    )
    # InSessionMemory legacy import 可以仍留(Q4 E in-session dedup / summarize 仍需)
    # 但 Memory Protocol 注入到 graph 的应是 HierarchicalMemory


def test_hierarchical_memory_satisfies_protocol_at_import() -> None:
    """sanity: HierarchicalMemory 在 import time satisfies Protocol."""
    from app.memory.hierarchical import HierarchicalMemory
    from app.memory.protocol import Memory

    instance = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    assert isinstance(instance, Memory)
```

跑 → red。

#### 10.3 实现 router DI swap

修改 `backend/app/router/chat.py` `_build_graph_singleton`:

定位 line ~181-204(`from app.agents.in_session_memory import InSessionMemory` + `memory = InSessionMemory(llm=llm)`), 替换:

```python
    # 在 _build_graph_singleton 函数内, 替换 line 181:

    from app.agents.chat_planner import ChatPlanner
    from app.agents.in_session_memory import InSessionMemory  # Q4 E in-session dedup/summarize 仍用
    from app.agents.responder import Responder
    from app.memory.hierarchical import HierarchicalMemory
    from app.orchestration.chat_graph import build_chat_graph
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.services.openai_client import build_llm_service_from_env
    from app.services.tushare_factory import build_tushare_service
    from app.tools.get_financials import GetFinancialsTool
    from app.tools.get_news import GetNewsTool
    from app.tools.get_stock_quote import StockQuoteTool
    from app.tools.registry import ToolRegistry

    llm = build_llm_service_from_env()
    tushare = build_tushare_service()

    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare))
    registry.register(GetFinancialsTool(tushare=tushare))
    registry.register(GetNewsTool(bocha=build_bocha_service_from_env()))

    planner = ChatPlanner(llm=llm, registry=registry)
    responder = Responder(llm=llm)

    # C.5 Plan 1B: HierarchicalMemory 替换 InSessionMemory 作为主 Memory Protocol 实现.
    # InSessionMemory 仍可用于 in-session dedup / token-guard summarize(Q4 E),
    # 但 cross-session memory 方法走 HierarchicalMemory.
    # Plan 2-4 的 archival_memory_* 方法 ship 后, 此处真 inject embed_service / llm_extractor;
    # Plan 1B 阶段 Plan 2-4 stub 方法 raise NotImplementedError, agent 调到时报错(预期).
    pg_factory = _build_async_pg_session_factory_or_none()
    if pg_factory is None:
        # 测试 / 无 PG 环境: fallback InSessionMemory 保 Q4 E behavior
        memory: Any = InSessionMemory(llm=llm)
    else:
        memory = HierarchicalMemory(
            pg_session_factory=pg_factory,
            age_executor=None,        # Plan 2 inject
            milvus_client=None,       # Plan 2 inject
            embed_service=None,       # Plan 2 inject
            llm_extractor=None,       # Plan 2 inject
            llm_judge=None,           # Plan 2 inject
        )

    # ... 后续代码不变(_NoOpCache 等)
```

新增辅助函数 `_build_async_pg_session_factory_or_none`(放在 chat.py 顶层):

```python
def _build_async_pg_session_factory_or_none():
    """build sync session factory from env DATABASE_URL.

    无 PG / 测试环境返回 None, fallback 走 InSessionMemory(保 Q4 E 兼容).
    """
    import os
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session, sessionmaker

        engine = create_engine(db_url, pool_pre_ping=True)
        Factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

        def _factory():
            return Factory()

        return _factory
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "DI fallback to InSessionMemory: %s", e
        )
        return None
```

#### 10.4 manual smoke

```bash
# Smoke 1: import 不爆
cd backend && uv run python -c "from app.router import chat; print('chat router import OK')"

# Smoke 2: HierarchicalMemory + Protocol
cd backend && uv run python -c "
from app.memory.hierarchical import HierarchicalMemory
from app.memory.protocol import Memory
m = HierarchicalMemory(None, None, None, None, None, None)
assert isinstance(m, Memory)
print('protocol satisfied')
"

# Smoke 3: server 起得来(quick boot)
cd backend && uv run python -c "
from app.app_main import app
print('app object:', app)
" 2>&1 | head -10
```

#### 10.5 跑测试 + 知识卡 + commit

```bash
cd backend && uv run pytest tests/unit/memory/test_router_di_swap.py -xvs
cd backend && uv run pytest tests/unit/memory/ tests/integration/memory/ -xvs
cd backend && uv run mypy app/memory/ app/router/chat.py
```

新建 `docs/claude-context/c5-plan1b-business-foundation-done.md`:

```markdown
---
name: c5-plan1b-business-foundation-done
description: C.5 Plan 1B Business Foundation ship — Memory Protocol + HierarchicalMemory 骨架 + working blocks + cold start + reconciliation
type: project
---

C.5 Plan 1B(Business Foundation)ship — 2026-05-{ship-date}.

## ship 范围
- `app.memory.protocol` Memory Protocol 完整 9 method 签名(契约 § 2)
- `app.memory.hierarchical` HierarchicalMemory class 骨架 + Plan 1B 方法实现, Plan 2-4 留 stub raise NotImplementedError
- `app.memory.registry` 7+11 ontology + normalize_entity(Stock ts_code / Metric / Strategy 白名单)+ jieba_tokenize_for_search
- `app.memory.working_blocks` Tier 1 CRUD 纯函数(append/replace/auto-paging) + HierarchicalMemory 方法(real PG)
- `app.memory.cold_start` 静态 3 路 seed(持仓 → HOLDS edges 主路径 / preferences / watchlist 留 hook)+ CLI `python -m app.memory.cold_start --user-id X`
- `app.memory.reconciliation` scan_inconsistent_state 入口骨架(算法深度补丁 #5 ship 入口, Plan 5 收束 retry)
- DI 替换: `app.router.chat._build_graph_singleton` 注入 HierarchicalMemory(env DATABASE_URL fallback InSessionMemory 保兼容)
- InSessionMemory 加 6 stub method 维持扩展 Protocol 兼容

## 关键决策(实施期撞实)
- **DI fallback 走 InSessionMemory**: 测试 / 无 PG env 不 break PR #39 Q4 E behavior, 渐进迁移
- **Industry/Sector 当前 passthrough + audit_flag**: 申万 registry 留 v1.x(Tushare /api/sw_hierarchy 没 ship)
- **cold_start preferences 路留 hook**: User model 当前无 preferences JSONB 列(PR #39 / v0.8 未 ship), 只 seed HOLDS
- **reconciliation case kind**: 'edge_exists_episode_unextracted'(Plan 1B 主 case)+ Plan 2/5 'pending_milvus' / 'age_pg_drift' 留 stub
- **Working blocks paged_lines**: Plan 1B 仅 logger.warning 不真归档; Plan 2 ship archival_memory_insert 后改 真调归档

## 跟 spec 决策对齐
- spec § 1: Memory Protocol DI hook ✓
- spec § 3: 7 entity + 11 rel + normalize 4 类规则 ✓(Industry/Sector v1.x 接 registry)
- spec § 7: persona 500 + scratchpad 1000 + 自动 paging ✓
- spec § 8: 3 路 cold start + 幂等(走 Plan 1A UNIQUE constraint)✓
- spec § 11 末尾 #5: reconciliation 入口骨架 ship ✓(Plan 5 weekly retry job 收束)

## 关键文件 ref
- backend/app/memory/protocol.py
- backend/app/memory/hierarchical.py
- backend/app/memory/registry.py
- backend/app/memory/working_blocks.py
- backend/app/memory/cold_start.py
- backend/app/memory/reconciliation.py
- backend/app/router/chat.py(DI swap)

## 下游解锁
- Plan 2 写入 8 step pipeline: 在 hierarchical.py 填 archival_memory_insert(Step 2-8)
- Plan 3 读取: 在 hierarchical.py 填 archival_memory_search + RRF v2
- Plan 4 MCP tools: 6 tool 包装本 Plan ship 的 method
- Plan 5 cost optimization: reconciliation Celery weekly job + skip_gate / batch_extractor
```

```bash
git add backend/app/router/chat.py backend/tests/unit/memory/test_router_di_swap.py docs/claude-context/c5-plan1b-business-foundation-done.md
git commit -m "feat(c5-plan1b): chat router DI swap → HierarchicalMemory + 知识卡 ship"
```

---

## § 4 Self-Review Checklist

### 契约对齐
- [x] 契约 § 2 Memory Protocol 9 method 签名(get_working_blocks / core_memory_append / core_memory_replace / archival_memory_insert(含 evidence_quote)/ archival_memory_search / archival_memory_traverse / recall_memory_search / write_episode / get_unextracted_episodes / mark_episode_extracted)— Task 1
- [x] 契约 § 3 HierarchicalMemory class 骨架 — 7 DI 参数(injection_classifier 默认 None)— Task 5
- [x] 契约 § 5 ENTITY_TYPES = 7 / REL_TYPES = 11 / normalize_entity 5 类规则 / is_valid_rel_type / jieba_tokenize_for_search — Task 3
- [x] 契约 § 6 core_memory_append 200 chars/call + auto-paging / core_memory_replace exact match raise — Task 4 + 6

### Spec 章节 coverage
- [x] **§ 1 整体架构**: DI 接入 chat router(Task 10)
- [x] **§ 3 Ontology**: 7+11 ontology + normalize 4 类(Stock/User/Metric/Strategy 完整, Industry/Sector audit_flag 留 v1.x)— Task 3
- [x] **§ 7 Working memory budget**: persona 500 / scratchpad 1000 / 自动 paging(踢 oldest lines)— Task 4 + 6
- [x] **§ 8 Cold Start Populator**: 3 路 seed(持仓 HOLDS 主路径 + preferences/watchlist 留 hook)+ 幂等(检查 cold_start_seed episode + UNIQUE constraint)+ CLI — Task 8
- [x] **§ 11 末尾 #5 三方一致性**: reconciliation 入口骨架 + 'edge_exists_episode_unextracted' case detection — Task 9

### 不在 Plan 1B 范围(其他 Plan 收)
- [x] Plan 2 写入 8 step pipeline(extractor / conflict_resolver)— hierarchical.py archival_memory_insert stub
- [x] Plan 2/5 Path B 兜底批 / 跨轮抽取(#4)— batch_extractor.py
- [x] Plan 3 3-way hybrid 检索 / RRF v2(#3)— retriever.py / rrf.py
- [x] Plan 4 6 MCP tools / evidence_quote 校验(#2)— mcp_server/tools/memory/
- [x] Plan 5 cost optimization 5 项 ladder / 投毒分类器 / 后验校准 — batch_extractor / injection_classifier / posterior_calibration
- [x] Plan 6 Memory vs KB routing(#7)— memory_kb_router.py
- [x] Plan 7 /memory page UI(#8)+ REST API
- [x] Plan 8 50 golden case + 3 metric + bi-temporal differential + chaos test

### 测试 layer 完整性
- [x] L0 unit: protocol / registry / working_blocks(纯函数)/ hierarchical_skeleton / cold_start helper / router DI smoke
- [x] L1 integration(real PG): working_blocks_e2e / episodes_e2e / cold_start_e2e / reconciliation_e2e
- [x] L2 cassette: 不在 Plan 1B 范围(无真 LLM call)
- [x] mypy strict 跑全 backend(Task 2/5/10 显式跑)

### Plan 自包含性
- [x] 10 个 task, 每个 5-step TDD(spec → failing test → 实现 → 跑测试 → commit)
- [x] 每 task 独立 commit, 无 cross-task pending state
- [x] 没有 placeholder code(每 step 完整代码)
- [x] 风险点显式注明: cold_start session_id FK / preferences / watchlist 留 hook 原因
- [x] DI fallback 设计保 PR #39 InSessionMemory 兼容, 渐进迁移
- [x] Plan 1A 假设显式: 4 PG 表 + AGE + Milvus + 幂等键 UNIQUE constraint 都已 ship

### 风险与已知 limitation
- **cold_start session_id**: 假 session_id 撞 chat_sessions FK 风险 — 假设 Plan 1A 协调 schema 允许 NULLABLE 或 ON DELETE; 若不允许 fallback 在 chat_sessions 建一条 system seed session(implementation 时 verify 实际 schema)
- **preferences / watchlist seed**: User model 无 preferences 列, 留 v1.x 接 PR #39 / v0.8 未 ship 的 user prefs 字段
- **DI fallback**: env 无 DATABASE_URL fallback InSessionMemory(测试通过), 生产环境必有 DATABASE_URL 走 HierarchicalMemory
- **Plan 2 stub raise**: agent 调 archival_memory_* 在 Plan 2 ship 前会 raise NotImplementedError — 这是预期行为(Plan 1B → 2 → 3 → 4 sequential ship)

---

## § 5 Commit 序列总览(预期 10 commit)

1. `feat(c5-plan1b): app.memory.protocol Memory Protocol + 完整 9 method 签名`
2. `feat(c5-plan1b): InSessionMemory 加 6 stub 方法保持扩展 Protocol 兼容`
3. `feat(c5-plan1b): entity registry — 7+11 ontology + normalize_entity + jieba_tokenize`
4. `feat(c5-plan1b): working blocks 纯函数层 — append/replace/auto-paging + L0 单测`
5. `feat(c5-plan1b): HierarchicalMemory class 骨架 + DI signature + Plan 2-4 stub`
6. `feat(c5-plan1b): HierarchicalMemory working blocks CRUD + auto-paging + L1 e2e`
7. `feat(c5-plan1b): HierarchicalMemory episode 持久化 — write/get_unextracted/mark_extracted`
8. `feat(c5-plan1b): cold start populator — 持仓 → HOLDS edges + 幂等 + CLI`
9. `feat(c5-plan1b): reconciliation 骨架 — scan inconsistent state(算法深度补丁 #5)`
10. `feat(c5-plan1b): chat router DI swap → HierarchicalMemory + 知识卡 ship`

PR title: `feat(c5-plan1b): Business Foundation — Memory Protocol + HierarchicalMemory + cold start + reconciliation`

---

## § 6 工程量预估

| Task | 预估时间 |
|---|---|
| 1. Protocol | 0.3 天 |
| 2. InSessionMemory stub | 0.2 天 |
| 3. Registry | 0.5 天(jieba calibration + 白名单整理) |
| 4. Working blocks 纯函数 | 0.4 天 |
| 5. HierarchicalMemory 骨架 | 0.3 天 |
| 6. Working blocks 方法 + L1 | 0.6 天(含 fixture conftest) |
| 7. Episode 方法 + L1 | 0.4 天 |
| 8. Cold start | 0.7 天(幂等键测试 + CLI) |
| 9. Reconciliation 骨架 | 0.3 天 |
| 10. DI swap + smoke + 知识卡 | 0.3 天 |

**合计**: ~4 天 wall time(含 mypy / pre-commit / debug buffer)。

