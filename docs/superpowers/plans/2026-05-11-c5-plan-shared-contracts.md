# C.5 Cross-Session Memory — Plan Shared Contracts

> **作用**：Plan 1-8 共享的接口契约 / 文件结构 / 命名约定。所有 sub-plan 必须遵守此契约，不得自行重定义。本文件先于 Plan 1-8 编写，Plan 1-8 可并行写但都引用本契约。
>
> **Spec ref**：`docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`（commit 含 PR #41 全部 3 个 commit）
>
> **Audit owner**：Plan 1-8 全部 ship 后，main 做一轮 audit 确认契约对齐（file path 不冲突 / 接口签名一致 / fixture 复用）

---

## § 1 项目结构（File Structure 全局总览）

### Backend 主目录

```
backend/app/memory/                       ← 主目录(NEW，Plan 1 创建)
├── __init__.py                           ← Plan 1 export
├── models.py                             ← Plan 1: 4 PG 表 SQLAlchemy
├── protocol.py                           ← Plan 1: Memory Protocol 接口
├── hierarchical.py                       ← Plan 1 骨架(stub NotImplementedError) + Plan 2/3/4 填实现
├── registry.py                           ← Plan 1: entity normalize 白名单
├── working_blocks.py                     ← Plan 1: Tier 1 working memory CRUD
├── extractor.py                          ← Plan 2: LLM extraction 入口
├── conflict_resolver.py                  ← Plan 2: 4-action conflict resolution
├── retriever.py                          ← Plan 3: 3-way hybrid 检索入口
├── rrf.py                                ← Plan 3: RRF v2 公式(importance + 时间感知)
├── persona_populator.py                  ← Plan 3: working memory auto-injection
├── cold_start.py                         ← Plan 1: 静态 cold start populator
├── reconciliation.py                     ← Plan 1: 进程崩溃恢复 job 骨架
├── injection_classifier.py               ← Plan 5: prompt injection 检测
├── batch_extractor.py                    ← Plan 5: batch extraction(end-of-session)
├── skip_gate.py                          ← Plan 5: skip-extraction gate
├── embed_cache.py                        ← Plan 5: embedding 缓存
├── posterior_calibration.py              ← Plan 3 / 5 (合作): importance 后验校准 weekly job
└── memory_kb_router.py                   ← Plan 6: Memory vs KB routing supervisor 节点(注: 物理可在 orchestration/, 但逻辑归 memory)

backend/app/mcp_server/tools/memory/      ← NEW, Plan 4 创建
├── __init__.py
├── core_memory_append.py                 ← Plan 4
├── core_memory_replace.py                ← Plan 4
├── archival_memory_insert.py             ← Plan 4(含 evidence_quote 校验)
├── archival_memory_search.py             ← Plan 4
├── archival_memory_traverse.py           ← Plan 4
└── recall_memory_search.py               ← Plan 4

backend/app/router/
└── memory_router.py                      ← Plan 7: /memory REST API endpoints

backend/app/tasks/
└── memory.py                             ← Plan 2/5: Celery tasks(end-of-session batch / reconciliation / posterior calibration)

backend/scripts/migrations/
└── 2026-05-11-c5-memory-schema.sql       ← Plan 1: SQL migration(SCHEMA / GRANT / partial index / AGE 设置)

backend/eval/memory/                      ← NEW, Plan 8 创建
├── c5_memory_golden.jsonl                ← Plan 8: 50 golden case
├── poison_attacks_golden.jsonl           ← Plan 8: 30 投毒攻击 case(Plan 5 也用)
├── cross_turn_extraction_golden.jsonl    ← Plan 8: 跨轮抽取 case
├── recall_precision_metric.py            ← Plan 8
├── temporal_correctness_metric.py        ← Plan 8
├── faithful_answer_metric.py             ← Plan 8
└── routing_accuracy_metric.py            ← Plan 8(memory 内部 6 tool routing + memory vs KB routing 共用)

backend/tests/
├── unit/memory/                          ← L0 Unit
│   ├── test_models.py                    ← Plan 1
│   ├── test_protocol.py                  ← Plan 1
│   ├── test_registry.py                  ← Plan 1
│   ├── test_working_blocks.py            ← Plan 1
│   ├── test_cold_start.py                ← Plan 1
│   ├── test_extractor.py                 ← Plan 2
│   ├── test_conflict_resolver.py         ← Plan 2
│   ├── test_retriever.py                 ← Plan 3
│   ├── test_rrf.py                       ← Plan 3
│   ├── test_persona_populator.py         ← Plan 3
│   ├── test_skip_gate.py                 ← Plan 5
│   ├── test_injection_classifier.py      ← Plan 5
│   ├── test_embed_cache.py               ← Plan 5
│   └── test_memory_kb_router.py          ← Plan 6
├── integration/memory/                   ← L1 Integration
│   ├── test_extractor_e2e.py             ← Plan 2(mock LLM, real PG)
│   ├── test_conflict_resolver_e2e.py     ← Plan 2
│   ├── test_retriever_e2e.py             ← Plan 3
│   ├── test_mcp_tools_e2e.py             ← Plan 4
│   ├── test_cost_opt_e2e.py              ← Plan 5
│   ├── test_kb_routing_e2e.py            ← Plan 6
│   └── test_cold_start_e2e.py            ← Plan 1
├── e2e/memory/                           ← L2 Cassette + Bi-temporal differential + Chaos
│   ├── test_search_full_path.py          ← Plan 3 cassette
│   ├── test_traverse_full_path.py        ← Plan 4 cassette
│   ├── test_recall_full_path.py          ← Plan 4 cassette
│   ├── test_bi_temporal_differential.py  ← Plan 8(spec § 12 5 session 序列)
│   ├── test_chaos_three_way_consistency.py ← Plan 8(#5 三方一致性)
│   └── test_poison_attacks.py            ← Plan 5/8(#2 投毒)
└── cassettes/memory/                     ← Plan 3-8 cassette
    ├── search_*.yaml
    ├── traverse_*.yaml
    └── ...

frontend/                                  ← Plan 7
├── src/app/memory/page.tsx                ← /memory route
├── src/components/memory/
│   ├── MemoryGraph.tsx                    ← Cytoscape graph viz
│   ├── MemoryTimeline.tsx                 ← Timeline view
│   ├── MemoryAuditLog.tsx                 ← Audit log view
│   └── MemoryOnboardingModal.tsx          ← 用户心智 onboarding(#8)
└── src/lib/memory-api.ts                  ← Backend API client

docs/claude-context/                       ← 各 Plan ship 后写知识卡(Plan 8 收束)
├── c5-plan1-foundation-done.md
├── c5-plan2-write-pipeline-done.md
├── ... (8 卡)
└── c5-cross-session-memory-done.md       ← 整 C.5 ship 总卡(Plan 8 写)
```

---

## § 2 Memory Protocol 接口（Plan 1 定义）

`backend/app/memory/protocol.py`：

```python
"""Memory Protocol — DI hook for chat agent's memory layer.

PR #39 ship 的 InSessionMemory 实现 in-session 范畴(Q4 E)。
C.5 加 HierarchicalMemory 实现跨 session 范畴(D MemGPT-style)。
两者通过 Memory Protocol 互换。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)


@runtime_checkable
class Memory(Protocol):
    """Memory interface used by ChatAgent / ResearchAgent.

    HierarchicalMemory(Plan 1-4) 和 InSessionMemory(PR #39 ship) 都实现此 Protocol。
    """

    # === Tier 1 Working Memory(Plan 1 完整实现) ===

    async def get_working_blocks(self, user_id: UUID) -> dict[str, ChatMemoryWorkingBlock]:
        """Return {block_name: block} for user's persona / scratchpad blocks."""
        ...

    async def core_memory_append(
        self, user_id: UUID, block_name: str, content: str
    ) -> ChatMemoryWorkingBlock:
        """Append content to working block. Auto-paging if exceed max_tokens."""
        ...

    async def core_memory_replace(
        self, user_id: UUID, block_name: str, old_content: str, new_content: str
    ) -> ChatMemoryWorkingBlock:
        """Replace exact substring. Raise ValueError if old_content not found."""
        ...

    # === Tier 2 Archival(Plan 2 写入 / Plan 3 读取) ===

    async def archival_memory_insert(
        self,
        user_id: UUID,
        content: dict[str, Any],
        reasoning: str,
        importance: float,
        evidence_quote: str,             # #2 防 Agent 幻觉写: 必须能在 episode 原文 substring 找到
        episode_id: UUID,
    ) -> ChatMemoryEdge:
        """Write fact to graph. Plan 2 实现完整 pipeline."""
        ...

    async def archival_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[ChatMemoryEdge]:
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

    # === Tier 3 Recall(Plan 4 实现，复用 PR #39 chat_messages 表) ===

    async def recall_memory_search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic search on chat_messages history. Plan 4 实现."""
        ...

    # === 持久化 episodes(Plan 1 完整实现) ===

    async def write_episode(
        self,
        user_id: UUID,
        session_id: UUID,
        episode_index: int,
        user_message: str,
        agent_response: str,
        source_kind: str = "chat_turn",
    ) -> ChatMemoryEpisode:
        """Path A 写入路径 step 1: episode 入库, extracted_at=NULL."""
        ...

    async def get_unextracted_episodes(
        self, user_id: UUID, limit: int = 100
    ) -> list[ChatMemoryEpisode]:
        """Path B end-of-session batch 用. Plan 5 batch extractor 调用."""
        ...

    async def mark_episode_extracted(
        self,
        episode_id: UUID,
        extracted_by: str,                # 'agent' / 'eos_batch' / 'manual'
        extraction_metadata: dict[str, Any],
    ) -> None:
        """Step 8: 抽取完成标记."""
        ...
```

**关键约定**：
- 所有方法 `async`
- 所有方法第一参数 `user_id: UUID`（多租户隔离）
- 返回类型用 `app.memory.models` 的 SQLAlchemy ORM 类，不另定义 Pydantic dataclass
- `evidence_quote` 是 `archival_memory_insert` 必填参数（#2 算法深度补丁），找不到原文 raise `ValueError`
- 需要在 PR #39 ship 的 `InSessionMemory` 上加 stub 这些方法（raise `NotImplementedError`），保持 Protocol 兼容（Plan 1 Task 处理）

---

## § 3 HierarchicalMemory class 骨架与责任划分

`backend/app/memory/hierarchical.py`：

```python
class HierarchicalMemory:
    """C.5 跨 session memory 实现, 替换 InSessionMemory."""

    def __init__(
        self,
        pg_session_factory,
        age_executor,                       # Plan 1 提供 thin wrapper
        milvus_client,
        embed_service,                      # qwen embed via existing app.services
        llm_extractor,                      # Plan 2 注入
        llm_judge,                          # Plan 2 注入
        injection_classifier=None,          # Plan 5 注入(默认 None = no check)
    ):
        ...

    # ===== Plan 1 实现 =====

    async def get_working_blocks(...): ...
    async def core_memory_append(...): ...
    async def core_memory_replace(...): ...
    async def write_episode(...): ...
    async def get_unextracted_episodes(...): ...
    async def mark_episode_extracted(...): ...

    # ===== Plan 2 实现(Plan 1 留 stub raise NotImplementedError) =====

    async def archival_memory_insert(...):
        raise NotImplementedError("filled by Plan 2")

    # ===== Plan 3 实现(Plan 1 留 stub) =====

    async def archival_memory_search(...):
        raise NotImplementedError("filled by Plan 3")

    # ===== Plan 4 实现(Plan 1 留 stub) =====

    async def archival_memory_traverse(...):
        raise NotImplementedError("filled by Plan 4")

    async def recall_memory_search(...):
        raise NotImplementedError("filled by Plan 4")
```

**Plan 1 责任**：class 骨架 + DI signature + Plan 1 范围方法完整实现 + 其他方法 stub。
**Plan 2-4 责任**：在 stub 位置填实现，**不修改 class signature**（避免 git conflict）。
**DI 替换点**：在 `app.app_main.lifespan` 或 `app.agents.factory.build_chat_agent` 处把 `InSessionMemory` 替换 `HierarchicalMemory`，由 Plan 1 完成。

---

## § 4 4 PG 表 SQLAlchemy Model（spec § 2 实现化）

`backend/app/memory/models.py`：

```python
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import (
    Column, String, Integer, DateTime, Float, Text, ForeignKey,
    UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID, JSONB, TSVECTOR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ChatMemoryEpisode(Base):
    __tablename__ = "chat_memory_episodes"

    episode_id          = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id             = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id          = Column(PgUUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    episode_index       = Column(Integer, nullable=False)
    user_message_text   = Column(Text, nullable=False)
    agent_response_text = Column(Text)
    source_kind         = Column(String, nullable=False, default="chat_turn")
    extracted_at        = Column(DateTime(timezone=True))
    extracted_by        = Column(String)            # 'agent' / 'eos_batch' / 'manual'
    extraction_metadata = Column(JSONB)
    created_at          = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("session_id", "episode_index", name="uq_episodes_session_idx"),
        Index("idx_episodes_user_session", "user_id", "session_id"),
        # partial index 在 SQL migration 文件里建(SQLAlchemy 表达力受限)
    )


class ChatMemoryNode(Base):
    __tablename__ = "chat_memory_nodes"

    node_id        = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id        = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    entity_type    = Column(String, nullable=False)   # 7 类
    entity_label   = Column(String, nullable=False)
    properties     = Column(JSONB, nullable=False, default=dict)
    created_at     = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    search_tokens  = Column(Text)                     # jieba pre-tokenize 中文
    # search_vector tsvector GENERATED 在 SQL migration 里建

    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_label", name="uq_nodes_user_type_label"),
        Index("idx_nodes_user_type", "user_id", "entity_type"),
    )


class ChatMemoryEdge(Base):
    __tablename__ = "chat_memory_edges"

    edge_id           = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id           = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    source_node_id    = Column(PgUUID(as_uuid=True), ForeignKey("chat_memory_nodes.node_id"), nullable=False)
    target_node_id    = Column(PgUUID(as_uuid=True), ForeignKey("chat_memory_nodes.node_id"), nullable=False)
    rel_type          = Column(String, nullable=False)   # 11 类

    # bi-temporal 4 字段(spec § 2 行 184-197)
    valid_from        = Column(DateTime(timezone=True), nullable=False)
    valid_to          = Column(DateTime(timezone=True))
    recorded_at       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    invalidated_at    = Column(DateTime(timezone=True))

    # provenance(spec § 2 行 200)
    source_episode_id = Column(PgUUID(as_uuid=True), ForeignKey("chat_memory_episodes.episode_id"), nullable=False)
    importance        = Column(Float)                 # 三档: 0.9 / 0.5 / 0.2 (Plan 1 加 CHECK constraint)
    reasoning         = Column(Text)

    properties        = Column(JSONB, nullable=False, default=dict)
    search_tokens     = Column(Text)
    # search_vector tsvector GENERATED 在 SQL migration 里建

    __table_args__ = (
        # importance 三档约束(Plan 1 实施, 算法深度补丁 #3)
        CheckConstraint("importance IN (0.9, 0.5, 0.2)", name="ck_edges_importance_three_tier"),
        # 幂等键(算法深度补丁 #5 三方一致性)
        UniqueConstraint(
            "source_episode_id", "source_node_id", "target_node_id", "rel_type", "valid_from",
            name="uq_edges_idempotency_key",
        ),
        Index("idx_edges_user_rel", "user_id", "rel_type"),
        Index("idx_edges_source", "source_node_id"),
        Index("idx_edges_target", "target_node_id"),
        Index("idx_edges_episode", "source_episode_id"),
        # partial index for current snapshot 在 SQL migration 里建
    )


class ChatMemoryWorkingBlock(Base):
    __tablename__ = "chat_memory_working_blocks"

    block_id     = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id      = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    block_name   = Column(String, nullable=False)    # 'persona' / 'scratchpad'
    content      = Column(Text, nullable=False, default="")
    token_count  = Column(Integer, nullable=False, default=0)
    max_tokens   = Column(Integer, nullable=False)   # persona=500, scratchpad=1000
    updated_at   = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "block_name", name="uq_working_blocks_user_name"),
    )
```

**关键约定**：
- 所有 `user_id` 字段类型 `PgUUID(as_uuid=True)`
- 所有 timestamp 字段 `DateTime(timezone=True)`
- 三档 importance CHECK constraint 在 model 加（Plan 3 RRF v2 依赖）
- 幂等键 UNIQUE constraint 在 model 加（Plan 1 实施，#5 算法深度补丁兑现）
- partial index / GENERATED tsvector 在 SQL migration 文件加（SQLAlchemy 表达力受限）
- **Plan 2-8 严禁修改 model 字段**，只能通过 SQL migration 加新字段（如果真需要）

---

## § 5 共享 Helper 函数签名

`backend/app/memory/registry.py`（Plan 1 实现）：

```python
ENTITY_TYPES = ["User", "Stock", "Industry", "Sector", "Metric", "Strategy", "Concept"]
REL_TYPES = ["HOLDS", "WATCHES", "PREFERS", "AVOIDS", "EXPRESSED_VIEW", "SOLD",
             "STUDIED", "COMPARED", "BELONGS_TO", "HAS_CONCEPT", "CORRELATED_WITH"]

def normalize_entity(entity_type: str, raw_label: str) -> tuple[str, bool]:
    """Returns (normalized_label, audit_flag).

    - Stock: ts_code 校验(6 数字 + .SH/.SZ/.BJ 后缀)
    - Industry: 申万行业 registry 查白名单
    - Sector: 概念板块 registry 查
    - Metric/Strategy/Concept: 附录 A 白名单 → 统一英文标识
    - User: 固定 'User'

    audit_flag=True 表示 normalize 失败(Plan 2 写入时仍写库, 标 flag).
    """
    ...


def is_valid_rel_type(rel_type: str) -> bool:
    """Pure: rel_type ∈ REL_TYPES?"""
    ...


def jieba_tokenize_for_search(text: str) -> str:
    """jieba.cut_for_search 全模式切词, 空格连接.

    用于 chat_memory_nodes / chat_memory_edges 的 search_tokens 字段写入.
    Plan 1 实现, Plan 3 检索路径 1(BM25)调用.
    """
    ...
```

`backend/app/memory/rrf.py`（Plan 3 实现，但常量在此处定义供 Plan 8 eval 引用）：

```python
# 算法深度补丁 #3: 时间感知 RRF 公式常量

IMPORTANCE_WEIGHT_MAP: dict[float, float] = {
    0.9: 0.95,
    0.5: 0.75,
    0.2: 0.6,
}
"""importance 三档映射, low(0.2)不完全压制(下限 0.6)."""

TAU_DAYS_BY_REL_TYPE: dict[str, int] = {
    "HOLDS": 365, "SOLD": 365,
    "PREFERS": 180, "AVOIDS": 180, "WATCHES": 180,
    "EXPRESSED_VIEW": 90, "STUDIED": 90,
    # 默认 fallback 在 compute_time_decay 里实现
}
"""τ 按 rel_type 分级: 持仓 365d / 偏好 180d / 观点 90d. spec § 11 #3."""

TAU_DAYS_DEFAULT: int = 180

DECAY_FLOOR: float = 0.5
"""时间衰减底, 老 fact 不消失保 audit 价值."""

RRF_K: int = 60


def compute_time_decay(rel_type: str, valid_from: datetime, valid_to: datetime | None) -> float:
    """time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) * exp(-Δt / τ).

    历史 edge(valid_to is not None) 用 valid_to 作衰减参考点.
    Plan 3 实现.
    """
    ...


def reciprocal_rank_fusion_v2(
    retriever_results: list[list[dict]],
    edges_meta: dict,
    k: int = RRF_K,
    top: int = 5,
) -> list[dict]:
    """spec § 11 末尾 #3 时间感知 RRF v2 公式. Plan 3 实现."""
    ...
```

`backend/app/memory/injection_classifier.py`（Plan 5 实现）：

```python
def is_prompt_injection(text: str) -> tuple[bool, float, str]:
    """Returns (is_injection, confidence, reason).

    实现策略:
    1. 规则层: 关键词 + 正则(忽略所有规则 / system: / 你必须 / pretend you are ...) → confidence ≥ 0.9
    2. ML 层(可选 v1.x): 200M 小分类器, confidence < 0.9 时启用

    Plan 4 archival_memory_insert + Plan 2 extractor 都调用.
    """
    ...


def evidence_quote_in_episode(quote: str, episode_text: str) -> bool:
    """Algorithm 深度补丁 #2 防 Agent 幻觉写: substring 校验.

    Plan 4 archival_memory_insert 必调用,失败 raise EvidenceNotFoundError.
    用于 v1.x ship 必做 6 条之 #2.
    """
    ...
```

`backend/app/memory/skip_gate.py`（Plan 5 实现）：

```python
def should_skip_extraction(episode: ChatMemoryEpisode) -> tuple[bool, str]:
    """Returns (skip, reason).

    spec § 4 优化 #3:
    - episode 长度 < 50 字符 → skip
    - 无 ts_code / metric / strategy 关键词 → skip
    - 已 extracted_at 不为 NULL → skip(防重)
    - 否则 → 不 skip(进 LLM extraction)

    Plan 2 extractor / Plan 5 batch_extractor 都调用.
    """
    ...
```

---

## § 6 测试 Fixture 命名约定

`backend/tests/conftest.py` 或 `backend/tests/memory/conftest.py`：

```python
# === L0 Unit / L1 Integration 共用 ===

@pytest.fixture(scope="session")
def pg_memory_fixture(pg_test_container):
    """real PG, schema 已 create_all + run migration SQL.
    依赖 PR #39 / v1.0 已有的 pg_test_container fixture(testcontainers + 外部 fallback).
    Plan 1 创建,Plan 2-8 复用.
    """
    ...


@pytest.fixture(scope="session")
def age_fixture(pg_memory_fixture):
    """AGE 扩展加载 + 'chat_memory' 图 + 7 vlabel + 11 elabel 创建.
    Plan 1 创建.
    """
    ...


@pytest.fixture(scope="session")
def milvus_memory_fixture():
    """real Milvus, chat_memory_edge_embeddings collection + alias 已建.
    Plan 1 创建,Plan 3-5 复用.
    """
    ...


@pytest.fixture
def mock_llm_extraction():
    """function-scoped, returns canned JSON for extraction prompt.
    Plan 2 创建,Plan 5 batch test 复用.
    """
    ...


@pytest.fixture
def mock_llm_judge():
    """function-scoped, returns canned 4-action verdict.
    Plan 2 创建.
    """
    ...


@pytest.fixture
def mock_qwen_embed():
    """function-scoped, returns deterministic 1024d vector based on text hash.
    Plan 1 创建,Plan 3-5 复用.
    """
    ...


# === L2 Cassette ===

@pytest.fixture
def vcr_memory_cassette(request):
    """VCR cassette path: backend/tests/cassettes/memory/<test-name>.yaml
    body match 模式跟 PR #39 cassette framework 一致(strip 动态 prompt 值).
    Plan 3 创建,Plan 4 / 8 复用.
    """
    ...


# === Celery ===

@pytest.fixture
def celery_eager_memory_fixture(monkeypatch):
    """L0/L1: CELERY_TASK_ALWAYS_EAGER=True.
    复用 v1.0 监控引擎 ship 的 celery_eager_fixture pattern(claude-context: celery-redis-test-fixture-pattern.md).
    """
    ...


@pytest.fixture(scope="session")
def celery_worker_memory_fixture(redis_test_container):
    """L2: subprocess Celery worker.
    复用 v1.0 同款 pattern.
    """
    ...
```

**约定**：
- L0 Unit 用 `mock_*` fixture，**不依赖** real DB（除 schema 校验类测试用 `pg_memory_fixture`）
- L1 Integration 用 `pg_memory_fixture` + `age_fixture` + `mock_llm_*`
- L2 Cassette 用 `vcr_memory_cassette` 录真 LLM 响应
- Celery 测试 L0/L1 用 eager，L2 用 subprocess

---

## § 7 Cassette / Golden Case 路径

```
backend/tests/cassettes/memory/
├── search_full_path__user_query_茅台.yaml
├── search_full_path__long_tail_老_fact.yaml
├── traverse_full_path__industry_neighbors.yaml
├── recall_full_path__我之前说过.yaml
└── ... (5+ representative scenarios)

backend/eval/memory/
├── c5_memory_golden.jsonl          ← Plan 8: 50 case (检索 / routing / 抽取)
├── poison_attacks_golden.jsonl     ← Plan 8: 30 投毒 attack(#2)
├── cross_turn_extraction_golden.jsonl ← Plan 8: 跨轮抽取(#4)
└── differential_holding_evolution.jsonl ← Plan 8: bi-temporal 5 session 序列(spec § 12)
```

---

## § 8 Memory vs KB Routing 触发词清单（Plan 6 用）

```python
# Plan 6 backend/app/memory/memory_kb_router.py

MEMORY_TRIGGER_WORDS: list[str] = [
    "我", "我的", "上次", "之前", "持仓", "偏好", "策略", "看好",
    "看空", "想法", "态度", "我说", "我提",
]

KB_TRIGGER_WORDS: list[str] = [
    "研报", "财报", "公告", "政策", "行业分析", "新闻", "市场",
    "宏观", "板块", "事件", "数据",
]

BOTH_TRIGGER_PATTERNS: list[str] = [
    "基于我.*推荐", "结合我.*", "根据我.*分析", "我.*的.*行业",
    "我.*的.*相关", "我.*跟.*对比",
]

# Plan 4 archival_memory_traverse 的 trigger words(已在 spec 附录 D)
TRAVERSE_TRIGGER_WORDS: list[str] = [
    "相关", "类似", "同样", "同", "同行业", "同赛道", "同概念",
    "所属", "属于", "归类", "之间", "对比", "vs", "链",
    "上下游", "产业链", "供应链", "范围", "覆盖",
]
```

---

## § 9 Cost Optimization 5 项契约（Plan 5 实现）

| # | 优化 | Service / Function | 调用方 |
|---|---|---|---|
| 1 | Anthropic prompt cache | `@with_prompt_cache` decorator on extraction / judge prompts | Plan 2 extractor / conflict_resolver |
| 2 | Batch extraction | `BatchExtractor.extract_batch(episodes: list)` in `batch_extractor.py` | Plan 5 / Celery eos task |
| 3 | Skip-extraction gate | `should_skip_extraction(episode)` in `skip_gate.py` | Plan 2 extractor / Plan 5 batch_extractor |
| 4 | Async via Celery | Queue `memory_llm`, task `extract_episode_async` in `tasks/memory.py` | Plan 2 path B / chat lifecycle hook |
| 5 | Embedding cache | `EmbedCache.get_or_compute(text)` in `embed_cache.py`, key=`memory:embed:{user_id}:{hash(text)}` | Plan 2/3 写入 / 检索路径 |

**关键约定**：
- prompt cache key 命名：`memory:prompt_cache:extraction:v1` / `memory:prompt_cache:judge:v1`
- embedding cache key 必须 **per-user**（防 #2 algorithm 深度补丁里提的 cross-user 污染，本契约扩展）：`memory:embed:{user_id}:{sha1(text)[:16]}`
- Celery 队列：`memory_llm`（v1.0 已有 `monitoring` / PR #39 已有 `chat`，新增独立队列）

---

## § 10 SSE / API Endpoint（Plan 7 frontend ↔ backend）

`backend/app/router/memory_router.py`（Plan 7 实现）：

```
GET  /api/v0/memory/graph              → graph viz 数据(nodes + edges 当前快照)
GET  /api/v0/memory/timeline           → 按 valid_from 排序的 edge 列表(支持分页)
GET  /api/v0/memory/audit              → invalidated_at IS NOT NULL 的 edge(纠错史)
POST /api/v0/memory/edges/{edge_id}/invalidate → 用户一键否决(#8 用户回路 first-class hook)
GET  /api/v0/memory/blocks             → working blocks 当前内容
```

**约定**：
- 不用 SSE（memory page 是 dashboard 风格 REST），跟 chat / research 的 SSE 流分离
- 所有 endpoint 强制 `user_id` 从 auth context 取，path / query 不接受 user_id 参数（防越权）

---

## § 11 Plan 范围矩阵

| 模块 | Plan 1 | Plan 2 | Plan 3 | Plan 4 | Plan 5 | Plan 6 | Plan 7 | Plan 8 |
|---|---|---|---|---|---|---|---|---|
| 4 PG 表 schema | ✓ ship | — | — | — | — | — | — | — |
| AGE 图 setup | ✓ ship | — | — | — | — | — | — | — |
| Milvus collection | ✓ ship | — | — | — | — | — | — | — |
| Memory Protocol | ✓ ship | — | — | — | — | — | — | — |
| HierarchicalMemory class 骨架 | ✓ ship | — | — | — | — | — | — | — |
| working_blocks CRUD | ✓ ship | — | — | — | — | — | — | — |
| Cold start populator(静态) | ✓ ship | — | — | — | — | — | — | — |
| Entity registry + normalize | ✓ ship | — | — | — | — | — | — | — |
| 幂等键 + reconciliation 骨架 | ✓ ship(#5) | — | — | — | — | — | — | — |
| 写入 8 step pipeline | — | ✓ ship | — | — | — | — | — | — |
| 4-action conflict resolution | — | ✓ ship | — | — | — | — | — | — |
| AGE/Milvus outbox sync | — | ✓ ship | — | — | — | — | — | — |
| 跨轮抽取(#4) | — | ✓ ship | — | — | — | — | — | — |
| 3-way hybrid 检索 | — | — | ✓ ship | — | — | — | — | — |
| RRF v2(#3 时间感知) | — | — | ✓ ship | — | — | — | — | — |
| Working memory auto-injection | — | — | ✓ ship | — | — | — | — | — |
| 长尾召回监控 | — | — | ✓ ship | — | — | — | — | ✓ assert |
| 6 MCP tools | — | — | — | ✓ ship | — | — | — | — |
| evidence_quote 校验(#2) | — | — | — | ✓ ship | — | — | — | — |
| Memory MCP profile | — | — | — | ✓ ship | — | — | — | — |
| 5 项 cost optimization ladder | — | — | — | — | ✓ ship | — | — | — |
| Prompt injection 分类器(#2) | — | — | — | — | ✓ ship | — | — | — |
| Posterior calibration job | — | — | ✓ glue | — | ✓ ship | — | — | — |
| Memory vs KB routing(#7) | — | — | — | — | — | ✓ ship | — | — |
| /memory page UI | — | — | — | — | — | — | ✓ ship | — |
| 用户心智 onboarding(#8) | — | — | — | — | — | — | ✓ ship | — |
| Memory page REST API | — | — | — | — | — | — | ✓ ship | — |
| 50 golden case | — | — | — | — | — | — | — | ✓ ship |
| 3 metric impl | — | — | — | — | — | — | — | ✓ ship |
| L0/L1/L2 完整测试 | partial | partial | partial | partial | partial | partial | partial | ✓ 收束 |
| Bi-temporal differential test | — | — | — | — | — | — | — | ✓ ship |
| Chaos test(#5 三方一致性) | — | — | — | — | — | — | — | ✓ ship |
| 投毒 attack 测试集(#2) | — | — | — | — | partial | — | — | ✓ 收束 |
| 知识卡 + CLAUDE.md 索引 | partial(自卡) | partial | partial | partial | partial | partial | partial | ✓ 总卡 |

**说明**：
- **ship**：该模块在此 Plan 完整实现 + 测试 + 知识卡
- **partial**：该 Plan 提供 stub / 部分实现 / 自身相关测试
- **glue**：该 Plan 调用集成（不实现 feature）
- **assert**：该 Plan 验证 feature（如长尾召回监控由 Plan 3 实现，Plan 8 在 eval pipeline 里 assert 阈值）

---

## § 12 测试分层约定

| Layer | 范围 | DB | LLM | Celery |
|---|---|---|---|---|
| **L0 Unit** | 纯函数 / Pydantic / model schema | sqlite override(create_all) 或不用 | mock | eager |
| **L1 Integration** | service / pipeline / e2e flow | real PG(testcontainers fixture) + AGE + Milvus | mock | eager |
| **L2 Cassette** | full retrieval / extraction with real LLM | real PG / AGE / Milvus | real(VCR record) | subprocess |
| **L3 Dogfood** | 作者真实跑 ≥ 10 chat 验证 | real prod-like | real | real |

**约定**：
- 每 Plan 必须有 L0 + L1 测试
- 涉及 LLM 的 Plan（2/3/4/5/6）必须有 L2 cassette（至少 2 representative scenarios）
- Bi-temporal differential test / Chaos test / 投毒 attack 测试集 → Plan 8 收束
- L3 Dogfood 在 Plan 8 写到 ship checklist

---

## § 13 知识卡 / Docs 协议

每 Plan ship 后写一张 `docs/claude-context/c5-plan{N}-{topic}-done.md` 知识卡：

```markdown
---
name: c5-plan{N}-{topic}-done
description: C.5 Plan {N} {topic} ship — 一句话核心
type: project
---

C.5 Plan {N} ({topic}) ship — {date}.

## ship 范围
- ...

## 关键决策(实施期撞实)
- ...

## 跟 spec 决策对齐
- ...

## 关键文件 ref
- backend/app/memory/{file}
- ...
```

`CLAUDE.md` 索引按 Plan 顺序更新（Plan 8 收束时统一总卡）。

**Plan 8 的总卡**：`docs/claude-context/c5-cross-session-memory-done.md`，按 v1.0 监控引擎 ship 总卡（`v1.0-monitoring-engine-done.md`）模式写。

---

## § 14 Commit Message 规范

每 Plan ship 出 N 个 commit，commit message 遵循 WORKING_AGREEMENT.md 规则 3：

- `feat(c5-plan{N}): <topic>` — 新功能
- `fix(c5-plan{N}): <topic>` + `原因 layer: impl|plan|spec` — bug 修
- `chore(c5-plan{N}): <topic>` — 重构 / 清理
- `test(c5-plan{N}): <topic>` — 加测试
- `docs(c5-plan{N}): <topic>` — 知识卡 / 注释

每 Plan ship 一个 PR，PR 标题 `feat(c5-plan{N}): {Plan Name}`。

---

## § 15 跨 Plan 依赖与执行顺序

```
Plan 1 (Schema + Foundation)
   │
   ├─► Plan 2 (Write Pipeline)
   │      │
   │      ├─► Plan 3 (Read Pipeline + RRF v2)
   │      │      │
   │      │      ├─► Plan 4 (6 MCP Tools)
   │      │      │      │
   │      │      │      ├─► Plan 6 (Memory vs KB Routing)
   │      │      │      └─► Plan 7 (Frontend /memory UI)
   │      │      │
   │      │      └─► Plan 5 (Cost Optimization) ← 也依赖 Plan 2
   │      │
   │      └─► Plan 5
   │
   └─► (Plan 1 ship 后, 2 / 5 可并行起步, 因为 Plan 5 部分功能不需 Plan 2 完整 ship)

Plan 8 (Eval + Tests + Docs) 依赖全部其他 Plan ship.
```

**写 plan 阶段（当前）**：8 plan 互不冲突，**8 个 subagent 可并行写**。
**执行 plan 阶段（后续）**：必须按依赖图 sequential ship，每 Plan ship 完触发下一 Plan 解锁。

---

## § 16 触发后做不在当前 plans

§ 14 P3 hooks 中的 6 条触发后做（不进 Plan 1-8）：

- 4 条 Scale-X 规模化补丁（spec § 11 4 条 Scale-1~4）
- 2 条算法深度 hook（spec § 11 末尾 #1 向量模型升级 / #6 ontology 演化）

留 v1.x 后期 / v2 触发时单独 spec + plan。

---

## 附录 A: spec 章节 → Plan 映射快查

| Spec 章节 | 主责 Plan |
|---|---|
| § 1 整体架构 | Plan 1（DI 接入 chat agent）|
| § 2 数据模型 / Schema | Plan 1 |
| § 3 Ontology | Plan 1（registry）|
| § 4 写入 Pipeline | Plan 2（主体）+ Plan 5（cost layer）|
| § 5 读取 Pipeline | Plan 3 |
| § 6 Agent Tool API（6 MCP Tools）| Plan 4 |
| § 7 Working Memory Budget | Plan 1（CRUD）+ Plan 3（auto-injection）|
| § 8 Cold Start Populator | Plan 1（静态）|
| § 9 /memory Page UI | Plan 7 |
| § 10 Eval Pipeline | Plan 8 |
| § 11 工业难题撞实表（16 + 4 + 8）| 各 Plan 按归属 |
| § 12 Test Strategy | Plan 8 收束 |
| § 13 工程量估算 | 全 Plan |
| § 14 v1.x Ship Checklist + P3 Hooks | Plan 8 ship checklist |
| § 15 简历叙事段 | Plan 8 总卡引用 |
