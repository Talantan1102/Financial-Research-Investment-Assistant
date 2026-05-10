# C.5 Plan 1A — Storage Foundation (4 PG 表 + AGE + Milvus + 幂等)

> **范围**: spec § 2 数据模型 / Schema 全部 + § 11 末尾 #5 三方一致性补丁的"幂等键 UNIQUE constraint"部分
>
> **共享契约**: `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md`(以下简称"契约")
>
> **Spec**: `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md`(commit PR #41)
>
> **工程量估算**: ~4 天 wall time
>
> **依赖前置**: 无(C.5 第一个 plan ship)
>
> **下游 unblock**: Plan 1B(Memory Protocol + HierarchicalMemory 骨架 + working_blocks CRUD + cold start + reconciliation 骨架)、Plan 2-8 全部依赖本 plan
>
> **不在范围(交给 Plan 1B)**: Memory Protocol 接口、HierarchicalMemory class 骨架、DI 替换 InSessionMemory、Entity registry、Working blocks CRUD、Cold start populator、Reconciliation job 骨架

---

## 0. Spec Reference

| 范围 | spec 章节 | 契约章节 |
|---|---|---|
| 4 PG 表 schema | § 2 表 1-4(行 138-270) | § 4 SQLAlchemy Model |
| Bi-temporal 4 字段 | § 2(行 184-225) | § 4 ChatMemoryEdge |
| AGE 图设置 | § 2(行 272-302) | — |
| Milvus 集合 + alias 模式 | § 2(行 304-318) + § 11 #1 触发后 hook 留口子 | — |
| importance 三档 CHECK | § 11 末尾 #3 | § 4 ChatMemoryEdge |
| 幂等键 UNIQUE | § 11 末尾 #5 | § 4 ChatMemoryEdge |
| GIN tsvector + jieba | § 2(行 173-180) + § 5 检索路径 1 | — |
| partial index for current snapshot | § 2(行 217-220) | — |

---

## 1. File Structure(本 plan ship 出的全部文件)

```
backend/app/memory/                               ← 主目录(NEW, 本 plan 创建)
├── __init__.py                                   ← Task 1: package marker + 必要 export
├── models.py                                     ← Task 2-4: 4 PG 表 SQLAlchemy
└── milvus_setup.py                               ← Task 7: Milvus collection + alias 创建

backend/scripts/migrations/
└── 2026-05-11-c5-memory-schema.sql               ← Task 5-6: SQL migration(partial index / GIN / AGE)

backend/app/models/__init__.py                    ← Task 4: barrel 加 chat_memory_* 4 model
backend/app/app_main.py                           ← Task 8: lifespan 加 SQL migration apply hook(幂等)

backend/tests/unit/memory/                        ← NEW
├── __init__.py
└── test_models.py                                ← Task 3 / 4 L0 schema validation

backend/tests/integration/memory/                 ← NEW
├── __init__.py
├── conftest.py                                   ← Task 7: pg_memory_fixture + age_fixture + milvus_memory_fixture
├── test_pg_schema_e2e.py                         ← Task 6 L1 real PG migration
├── test_age_graph_e2e.py                         ← Task 6 L1 AGE 'chat_memory' 图
├── test_milvus_collection_e2e.py                 ← Task 7 L1 collection + alias 可写读
└── test_idempotency_constraint_e2e.py            ← Task 4 L1 幂等键 UNIQUE 反向失败覆盖
```

> **不动**: `backend/app/memory/protocol.py` / `hierarchical.py` / `registry.py` / `working_blocks.py` / `cold_start.py` / `reconciliation.py` 全部留 Plan 1B。

---

## 2. 关键设计决策(实施前必读)

### 2.1 字段类型与 SQLAlchemy 表达力边界

契约 § 4 字段名 / 类型 / index 是**硬约束**, Plan 2-8 严禁修改 model 字段。本 plan 严格按契约写。但有些 PG 特性(`tsvector GENERATED ALWAYS AS`, partial index, AGE 扩展) SQLAlchemy 表达力受限, 走 raw SQL migration:

| 走 SQLAlchemy model | 走 SQL migration |
|---|---|
| 表 + 字段 + UUID/UUID FK | `tsvector GENERATED ALWAYS AS ... STORED` 列 |
| UNIQUE / CHECK constraint | partial index(`WHERE valid_to IS NULL ...`) |
| 普通 B-tree index | GIN index on tsvector |
| `JSONB` / `TIMESTAMPTZ` 用 SA 类型 | AGE 扩展加载 + 图创建 + vlabel/elabel |

### 2.2 PG vs sqlite 类型差异(L0/L1 分层)

contract § 4 用 `PgUUID(as_uuid=True)` / `JSONB` / `TSVECTOR`。L0 unit test 走 sqlite override 时这些类型必须能 fallback:

- **决定**: 模仿 v1.0 monitoring(`UUID(as_uuid=True).with_variant(String(36), "sqlite")`)。本 plan 4 个 PG 类型在 model 层用同样 with_variant 模式: `PgUUID` → `String(36)`(sqlite), `JSONB` → `JSON`(sqlite)。`TSVECTOR` 字段不进 SQLAlchemy model(只在 SQL migration 里建), L0 不测它, L1 真 PG 才测。
- **理由**: L0 schema unit test 不 require docker/PG, 提速 + CI 友好; L1 才上 testcontainer 验真 PG 的 tsvector / partial index / AGE / Milvus。

### 2.3 幂等键 UNIQUE constraint 形态

spec § 11 末尾 #5 写的是 `(episode_id, source_label, target_label, rel_type, valid_from)`。但 source_label / target_label 不是表字段(是 nodes 表的 entity_label), 直接写到 edge 表 UNIQUE 不可行。契约 § 4 已校准为:

```
UNIQUE(source_episode_id, source_node_id, target_node_id, rel_type, valid_from)
```

用 `source_node_id / target_node_id`(已经是 FK to nodes.node_id) 替代 source_label / target_label 在语义上等价, 因为 nodes 表有 `UNIQUE(user_id, entity_type, entity_label)`, 一个 (user_id, entity_type, entity_label) 唯一对应一个 node_id。

**反向失败覆盖**: 同 episode 重复抽出同 (s, t, rel_type, valid_from) → 第二次插入 raise `IntegrityError`(L1 测试覆盖, Task 4)。

### 2.4 importance CHECK 三档

契约 § 4 写 `CheckConstraint("importance IN (0.9, 0.5, 0.2)", name="ck_edges_importance_three_tier")`。spec § 2 原本写 `REAL CHECK (importance BETWEEN 0 AND 1)`, 但 spec § 11 末尾 #3 算法深度补丁明确升级到三档。**以契约为准**, model 层加 CHECK + L0 schema test 校验。

### 2.5 Milvus alias 模式 — 给 #1 触发后 hook 留口子

spec § 11 末尾 #1(触发后做)要求"向量模型升级 zero-downtime alias 切换"。本 plan **不实现升级流程**, 但**必须从 day 1 就用 alias 引用 collection**, 否则将来切的时候要回头改全部检索代码。

**实现**:
- 真实 collection 名: `chat_memory_edge_embeddings_v1`(带版本后缀)
- alias 名: `chat_memory_edge_embeddings_current`
- 业务代码统一用 alias 名(Plan 2-5 检索/写入); Plan 1A 创建时立即 `create_alias(collection, alias)`
- alias 切换由 Plan 1A 之后的"#1 触发后做"plan 处理, 本 plan 只建初始 alias

### 2.6 search_tokens 写入路径

spec § 2 行 172 + 205 都说 `search_tokens` 是 `jieba pre-tokenize 中文`。但 jieba 调用应该在**写入时**(Plan 2 archival_memory_insert / Plan 1B normalize), 本 plan 只建 schema(列存在 + GENERATED tsvector + GIN), 不实现 jieba 调用。

L1 测试: 直接 `INSERT ... search_tokens='茅台 贵州 白酒'` 验 GENERATED `search_vector` 自动产生 + GIN 命中即可, 不真跑 jieba。

### 2.7 AGE 测试可选 skip

AGE 在某些 dev 机器上未编译进 PG。fixture `age_fixture` 必须健壮 fallback: 如果 `CREATE EXTENSION age` 失败, **不报红 fixture**, 而是 `pytest.skip(reason="AGE extension not available")`。这样 macOS 开发者跑测试不被 AGE 卡死, 但 CI / Docker 真 PG 环境必须装好 AGE。

> **CI 约束**: Plan 1A ship 后, `docker-compose.yml` 的 PG image 必须切到 `apache/age:latest` 或带 AGE 扩展的镜像。本 plan Task 5 同步动 `docker-compose.yml`。

---

## 3. Task 拆分(8 task, 5-step TDD)

### Task 1 — backend/app/memory/ 包初始化 + 空 __init__.py

**目标**: 创建 `backend/app/memory/` 目录 + 空 `__init__.py`(暂不 export 任何东西, 留 Plan 1B 填), 让后续 task 的 import 链可工作。

**Step 1 — 红测**: 跳过(纯 scaffolding, 无业务逻辑)。

**Step 2 — 实现**:

`backend/app/memory/__init__.py`:
```python
"""C.5 Cross-session memory subsystem.

Plan 1A ships: PG schema + AGE setup + Milvus collection + 幂等键 UNIQUE.
Plan 1B will fill: Memory Protocol / HierarchicalMemory / working_blocks / cold_start.
Plan 2-8 fill: extraction / retrieval / MCP tools / cost / routing / UI / eval.

See docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md
"""

from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)

__all__ = [
    "ChatMemoryEpisode",
    "ChatMemoryNode",
    "ChatMemoryEdge",
    "ChatMemoryWorkingBlock",
]
```

> **注**: import 在 Task 2 写完 models.py 后才能 resolve, 但 module import 是 lazy 的, 先写 __init__.py 不会报错(import 只在 import 触发时执行)。

**Step 3 — 绿测**: Task 2 后跑全套。

**Step 4 — refactor**: N/A。

**Step 5 — commit**:

```bash
git add backend/app/memory/__init__.py
git commit -m "chore(c5-plan1a): scaffold backend/app/memory/ package"
```

---

### Task 2 — `backend/app/memory/models.py` 4 PG 表 SQLAlchemy

**目标**: 严格按契约 § 4 写 4 个 SQLAlchemy ORM 类。覆盖字段名 / 类型 / 默认值 / FK / index / UNIQUE / CHECK constraint。

**Step 1 — 红测**: 写 L0 unit test 占位(完整测试 Task 3 写)。

`backend/tests/unit/memory/__init__.py`: 空文件。

`backend/tests/unit/memory/test_models.py`:
```python
"""L0 schema test for chat_memory_* models. PG-specific behaviors covered in L1."""

import pytest


def test_models_importable():
    """Smoke: 4 model classes import without error."""
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
        ChatMemoryWorkingBlock,
    )
    assert ChatMemoryEpisode.__tablename__ == "chat_memory_episodes"
    assert ChatMemoryNode.__tablename__ == "chat_memory_nodes"
    assert ChatMemoryEdge.__tablename__ == "chat_memory_edges"
    assert ChatMemoryWorkingBlock.__tablename__ == "chat_memory_working_blocks"
```

跑: `cd backend && uv run pytest tests/unit/memory/test_models.py -x` → ImportError(red)。

**Step 2 — 实现**:

`backend/app/memory/models.py`:
```python
"""C.5 Cross-session memory PG models.

严格遵守: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 4
Spec: docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 2

设计取舍:
- PgUUID + with_variant(String(36), "sqlite") — L0 unit test sqlite override 友好
- JSONB + with_variant(JSON, "sqlite") — 同上
- tsvector GENERATED + partial index — SQLAlchemy 表达力受限, 留 SQL migration
- importance CHECK 三档(0.9/0.5/0.2) — § 11 末尾 #3 算法深度补丁
- 幂等键 UNIQUE — § 11 末尾 #5 三方一致性补丁

Plan 2-8 严禁修改 model 字段, 只能通过新 SQL migration 加新字段。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.sql import func

from app.core.database import Base

# ---------------------------------------------------------------------------
# Type adapters: L0 sqlite override fallback
# ---------------------------------------------------------------------------

_UUID = PgUUID(as_uuid=True).with_variant(String(36), "sqlite")
_JSONB = JSONB().with_variant(JSON, "sqlite")
_TS = DateTime(timezone=True)


# ---------------------------------------------------------------------------
# Table 1: chat_memory_episodes (抽取单位)
# ---------------------------------------------------------------------------


class ChatMemoryEpisode(Base):
    """spec § 2 行 138-160. 一个 chat_turn / file_upload / web_paste / cold_start_seed 单位.

    `extracted_at IS NULL` 表示尚未被抽取, end-of-session batch 扫这些。
    """

    __tablename__ = "chat_memory_episodes"

    episode_id = Column(_UUID, primary_key=True, default=uuid4)
    user_id = Column(_UUID, ForeignKey("users.id"), nullable=False)
    session_id = Column(_UUID, ForeignKey("chat_sessions.id"), nullable=False)
    episode_index = Column(Integer, nullable=False)
    user_message_text = Column(Text, nullable=False)
    agent_response_text = Column(Text, nullable=True)
    source_kind = Column(String(32), nullable=False, default="chat_turn")
    extracted_at = Column(_TS, nullable=True)
    extracted_by = Column(String(32), nullable=True)  # 'agent' / 'eos_batch' / 'manual'
    extraction_metadata = Column(_JSONB, nullable=True)
    created_at = Column(_TS, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("session_id", "episode_index", name="uq_episodes_session_idx"),
        Index("idx_episodes_user_session", "user_id", "session_id"),
        # partial index `idx_episodes_unextracted WHERE extracted_at IS NULL` → SQL migration
    )


# ---------------------------------------------------------------------------
# Table 2: chat_memory_nodes (实体)
# ---------------------------------------------------------------------------


class ChatMemoryNode(Base):
    """spec § 2 行 162-181. 7 类 entity (User / Stock / Industry / Sector / Metric / Strategy / Concept).

    UNIQUE(user_id, entity_type, entity_label) 保证同一用户下 entity 唯一,
    edges 表通过 source_node_id / target_node_id FK 引用, 幂等键依赖此唯一性。
    """

    __tablename__ = "chat_memory_nodes"

    node_id = Column(_UUID, primary_key=True, default=uuid4)
    user_id = Column(_UUID, ForeignKey("users.id"), nullable=False)
    entity_type = Column(String(32), nullable=False)
    entity_label = Column(String(255), nullable=False)
    properties = Column(_JSONB, nullable=False, default=dict)
    created_at = Column(_TS, nullable=False, server_default=func.now())
    search_tokens = Column(Text, nullable=True)
    # search_vector tsvector GENERATED → SQL migration

    __table_args__ = (
        UniqueConstraint(
            "user_id", "entity_type", "entity_label", name="uq_nodes_user_type_label"
        ),
        Index("idx_nodes_user_type", "user_id", "entity_type"),
        # GIN index on search_vector → SQL migration
    )


# ---------------------------------------------------------------------------
# Table 3: chat_memory_edges (关系 + bi-temporal 4 字段)
# ---------------------------------------------------------------------------


class ChatMemoryEdge(Base):
    """spec § 2 行 183-225. 11 类 rel_type. bi-temporal 4 时间戳.

    importance 三档 CHECK constraint(0.9/0.5/0.2) — § 11 末尾 #3.
    幂等键 UNIQUE(source_episode_id, source_node_id, target_node_id, rel_type, valid_from) — § 11 末尾 #5.
    """

    __tablename__ = "chat_memory_edges"

    edge_id = Column(_UUID, primary_key=True, default=uuid4)
    user_id = Column(_UUID, ForeignKey("users.id"), nullable=False)
    source_node_id = Column(
        _UUID, ForeignKey("chat_memory_nodes.node_id"), nullable=False
    )
    target_node_id = Column(
        _UUID, ForeignKey("chat_memory_nodes.node_id"), nullable=False
    )
    rel_type = Column(String(32), nullable=False)

    # ====== bi-temporal 4 字段(spec § 2 行 193-197) ======
    valid_from = Column(_TS, nullable=False)
    valid_to = Column(_TS, nullable=True)
    recorded_at = Column(_TS, nullable=False, server_default=func.now())
    invalidated_at = Column(_TS, nullable=True)

    # ====== provenance(spec § 2 行 199-202) ======
    source_episode_id = Column(
        _UUID, ForeignKey("chat_memory_episodes.episode_id"), nullable=False
    )
    importance = Column(Float, nullable=True)  # 三档 CHECK below
    reasoning = Column(Text, nullable=True)

    properties = Column(_JSONB, nullable=False, default=dict)
    search_tokens = Column(Text, nullable=True)
    # search_vector tsvector GENERATED → SQL migration

    __table_args__ = (
        # importance 三档(算法深度补丁 #3) — NULL 允许(写入时可能 deferred)
        CheckConstraint(
            "importance IS NULL OR importance IN (0.9, 0.5, 0.2)",
            name="ck_edges_importance_three_tier",
        ),
        # 幂等键(算法深度补丁 #5 三方一致性) — 同 episode 同 (s, t, rel, valid_from) 不可重抽
        UniqueConstraint(
            "source_episode_id",
            "source_node_id",
            "target_node_id",
            "rel_type",
            "valid_from",
            name="uq_edges_idempotency_key",
        ),
        Index("idx_edges_user_rel", "user_id", "rel_type"),
        Index("idx_edges_source", "source_node_id"),
        Index("idx_edges_target", "target_node_id"),
        Index("idx_edges_episode", "source_episode_id"),
        # partial index for "current snapshot" + GIN index on search_vector → SQL migration
        # 时间区间 query 索引 → SQL migration
    )


# ---------------------------------------------------------------------------
# Table 4: chat_memory_working_blocks (Tier 1 working memory)
# ---------------------------------------------------------------------------


class ChatMemoryWorkingBlock(Base):
    """spec § 2 行 257-269 + § 7. persona / scratchpad two named blocks per user.

    Plan 1A 只建 schema, CRUD 留 Plan 1B(working_blocks.py)。
    """

    __tablename__ = "chat_memory_working_blocks"

    block_id = Column(_UUID, primary_key=True, default=uuid4)
    user_id = Column(_UUID, ForeignKey("users.id"), nullable=False)
    block_name = Column(String(32), nullable=False)  # 'persona' / 'scratchpad'
    content = Column(Text, nullable=False, default="")
    token_count = Column(Integer, nullable=False, default=0)
    max_tokens = Column(Integer, nullable=False)  # persona=500, scratchpad=1000
    updated_at = Column(
        _TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "block_name", name="uq_working_blocks_user_name"),
    )
```

**Step 3 — 绿测**:
```bash
cd backend && uv run pytest tests/unit/memory/test_models.py -x
```
预期 PASS(Task 3 加更多 schema test)。

**Step 4 — refactor**: 跑 mypy:
```bash
cd backend && uv run mypy app/memory/models.py
```
预期 PASS。

**Step 5 — commit**:
```bash
git add backend/app/memory/__init__.py backend/app/memory/models.py \
        backend/tests/unit/memory/__init__.py backend/tests/unit/memory/test_models.py
git commit -m "feat(c5-plan1a): 4 PG 表 SQLAlchemy model(契约 § 4)"
```

---

### Task 3 — L0 schema validation test

**目标**: L0 unit test 全面校验 model: 字段存在 / 类型正确 / index 命名 / UNIQUE/CHECK constraint 在 metadata 里被识别。**不依赖 PG**, 走 sqlite override。

**Step 1 — 红测**: 加完整 test, 跑应该全 fail(因为 model 已实现 Task 2 应该已经 PASS 大部分; 这步只补充测试 surface)。

`backend/tests/unit/memory/test_models.py`(完全替换):
```python
"""L0 schema test for chat_memory_* models. PG-specific behaviors covered in L1.

覆盖:
- 4 model 类可 import + tablename 正确
- 字段名 / 类型 / nullable 跟契约 § 4 对齐
- UNIQUE / CHECK constraint 在 metadata 里被识别
- create_all() on sqlite override 不报错
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)


# ---------------------------------------------------------------------------
# 1. tablenames + import smoke
# ---------------------------------------------------------------------------


def test_tablenames():
    assert ChatMemoryEpisode.__tablename__ == "chat_memory_episodes"
    assert ChatMemoryNode.__tablename__ == "chat_memory_nodes"
    assert ChatMemoryEdge.__tablename__ == "chat_memory_edges"
    assert ChatMemoryWorkingBlock.__tablename__ == "chat_memory_working_blocks"


# ---------------------------------------------------------------------------
# 2. 字段 surface 校验(契约 § 4)
# ---------------------------------------------------------------------------


def test_episode_fields():
    cols = {c.name for c in ChatMemoryEpisode.__table__.columns}
    assert cols == {
        "episode_id", "user_id", "session_id", "episode_index",
        "user_message_text", "agent_response_text", "source_kind",
        "extracted_at", "extracted_by", "extraction_metadata", "created_at",
    }


def test_node_fields():
    cols = {c.name for c in ChatMemoryNode.__table__.columns}
    assert cols == {
        "node_id", "user_id", "entity_type", "entity_label",
        "properties", "created_at", "search_tokens",
    }


def test_edge_fields():
    cols = {c.name for c in ChatMemoryEdge.__table__.columns}
    expected = {
        "edge_id", "user_id", "source_node_id", "target_node_id", "rel_type",
        "valid_from", "valid_to", "recorded_at", "invalidated_at",
        "source_episode_id", "importance", "reasoning",
        "properties", "search_tokens",
    }
    assert cols == expected, f"missing: {expected - cols}, extra: {cols - expected}"


def test_working_block_fields():
    cols = {c.name for c in ChatMemoryWorkingBlock.__table__.columns}
    assert cols == {
        "block_id", "user_id", "block_name",
        "content", "token_count", "max_tokens", "updated_at",
    }


# ---------------------------------------------------------------------------
# 3. Constraint surface(UNIQUE / CHECK 命名)
# ---------------------------------------------------------------------------


def _constraint_names(table) -> set[str]:
    return {c.name for c in table.constraints if c.name}


def test_episode_constraints():
    names = _constraint_names(ChatMemoryEpisode.__table__)
    assert "uq_episodes_session_idx" in names


def test_node_constraints():
    names = _constraint_names(ChatMemoryNode.__table__)
    assert "uq_nodes_user_type_label" in names


def test_edge_constraints():
    names = _constraint_names(ChatMemoryEdge.__table__)
    # importance 三档 CHECK
    assert "ck_edges_importance_three_tier" in names
    # 幂等键 UNIQUE — 算法深度补丁 #5
    assert "uq_edges_idempotency_key" in names


def test_working_block_constraints():
    names = _constraint_names(ChatMemoryWorkingBlock.__table__)
    assert "uq_working_blocks_user_name" in names


# ---------------------------------------------------------------------------
# 4. Index surface(B-tree index 命名)
# ---------------------------------------------------------------------------


def _index_names(table) -> set[str]:
    return {idx.name for idx in table.indexes}


def test_edge_indexes():
    names = _index_names(ChatMemoryEdge.__table__)
    assert "idx_edges_user_rel" in names
    assert "idx_edges_source" in names
    assert "idx_edges_target" in names
    assert "idx_edges_episode" in names


def test_node_indexes():
    names = _index_names(ChatMemoryNode.__table__)
    assert "idx_nodes_user_type" in names


def test_episode_indexes():
    names = _index_names(ChatMemoryEpisode.__table__)
    assert "idx_episodes_user_session" in names


# ---------------------------------------------------------------------------
# 5. create_all() on sqlite — 跨 dialect 兼容(L0 友好)
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_session():
    """fresh sqlite + create_all + 必要前置表(users / chat_sessions)."""
    engine = create_engine("sqlite:///:memory:")
    # 触发 user / chat_session model 注册(memory model 依赖 FK)
    import app.models  # noqa: F401  barrel ensures FK targets exist
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_sqlite_create_all_works(sqlite_session):
    """create_all on sqlite override 不抛 — proves with_variant 设置正确."""
    # 直接查 sqlite_master 验表存在
    from sqlalchemy import inspect
    insp = inspect(sqlite_session.bind)
    tables = set(insp.get_table_names())
    assert "chat_memory_episodes" in tables
    assert "chat_memory_nodes" in tables
    assert "chat_memory_edges" in tables
    assert "chat_memory_working_blocks" in tables
```

跑(应有 fail, 因为 Task 2 model 尚未注册到 `app.models` barrel — 见 Task 4 加 barrel; 这步先跑看哪些 PASS):
```bash
cd backend && uv run pytest tests/unit/memory/test_models.py -x -v
```
预期: 前 4 类 test(field/constraint/index/tablename)PASS, `test_sqlite_create_all_works` 可能 fail(barrel 没拉 chat_memory_*, 或者 user/chat_session FK target 缺)→ Task 4 修。

**Step 2 — 实现**: 已在 Task 2 完成。本 task 主要补 test。

**Step 3 — 绿测**: Task 4 后再跑。

**Step 4 — refactor**: N/A。

**Step 5 — commit**:
```bash
git add backend/tests/unit/memory/test_models.py
git commit -m "test(c5-plan1a): L0 schema validation 4 model(field/index/constraint surface)"
```

---

### Task 4 — barrel 注册 + 幂等键 L1 反向失败测试 + ondelete 策略

**目标**:
1. 把 4 个 chat_memory_* model 加到 `backend/app/models/__init__.py` barrel(让 `app_main.lifespan` 的 `Base.metadata.create_all()` 能拉到)。
2. 写 L1 真 PG fixture + 幂等键 UNIQUE 反向失败测试(spec § 11 #5 算法深度补丁 verify)。
3. 跨表 FK ondelete 策略小决策(本 plan 决定: 不加 CASCADE, 保持 audit 价值; 用户删除走 GDPR job 单独处理 — 留 Scale-4 hook)。

**Step 1 — 红测**:

`backend/tests/integration/memory/__init__.py`: 空文件。

`backend/tests/integration/memory/conftest.py`(初版, Task 7 扩展):
```python
"""Integration test fixtures for backend/app/memory/.

Shape 跟 v1.0 monitoring / v0.9.x pg_test_container 一致(契约 § 6)。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# pg_memory_fixture — 真 PG + create_all + 跑 SQL migration
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_memory_fixture(pg_test_container) -> Iterator[dict[str, object]]:
    """real PG + chat_memory_* 4 表 + SQL migration 已 apply.

    依赖 backend/tests/conftest.py 的 pg_test_container(已 ship v0.9.x)。
    """
    url = pg_test_container["url"]
    engine = create_engine(url, future=True)

    # 1. create_all 4 表(走 SQLAlchemy)
    from app.core.database import Base
    import app.models  # noqa: F401  barrel registers chat_memory_*
    Base.metadata.create_all(bind=engine)

    # 2. apply SQL migration(partial index / GIN / AGE / GENERATED tsvector)
    backend_dir = Path(__file__).resolve().parents[3]
    migration_path = (
        backend_dir / "scripts" / "migrations" / "2026-05-11-c5-memory-schema.sql"
    )
    if migration_path.exists():
        sql = migration_path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            conn.execute(text(sql))

    yield {"url": url, "engine": engine, **pg_test_container}

    engine.dispose()


@pytest.fixture
def pg_memory_session(pg_memory_fixture):
    """function-scoped Session, 每 test 自己 rollback."""
    engine = pg_memory_fixture["engine"]
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

`backend/tests/integration/memory/test_idempotency_constraint_e2e.py`:
```python
"""L1 verify 幂等键 UNIQUE constraint(spec § 11 末尾 #5 算法深度补丁).

同 episode 重复抽出同 (s, t, rel_type, valid_from) → 第二次 insert raise IntegrityError.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user_and_session(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert minimal users + chat_sessions row to satisfy FK."""
    from app.models.user import User
    from app.models.chat import ChatSession

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user = User(id=user_id, username=f"u_{user_id.hex[:6]}", password_hash="x")
    session.add(user)
    session.flush()
    cs = ChatSession(
        id=session_id,
        user_id=user_id,
        title="t",
        created_at=datetime.now(timezone.utc),
    )
    session.add(cs)
    session.flush()
    return user_id, session_id


def test_idempotency_key_blocks_duplicate_insert(pg_memory_session):
    """同 (episode, source_node, target_node, rel_type, valid_from) 第二次 insert raise."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    # episode + 2 nodes
    episode = ChatMemoryEpisode(
        user_id=user_id,
        session_id=session_id,
        episode_index=0,
        user_message_text="我买了茅台",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(
        user_id=user_id, entity_type="Stock", entity_label="600519.SH"
    )
    s.add_all([episode, src, tgt])
    s.flush()

    valid_from = datetime(2024, 8, 1, tzinfo=timezone.utc)
    edge1 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=valid_from,
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    s.add(edge1)
    s.commit()

    # 重复 insert → IntegrityError
    edge2 = ChatMemoryEdge(
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=valid_from,
        source_episode_id=episode.episode_id,
        importance=0.9,
    )
    s.add(edge2)
    with pytest.raises(IntegrityError):
        s.commit()


def test_idempotency_allows_different_valid_from(pg_memory_session):
    """同 (s, t, rel) 但不同 valid_from → 允许(场景 2 SOLD/HOLDS)."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    episode = ChatMemoryEpisode(
        user_id=user_id, session_id=session_id, episode_index=0,
        user_message_text="我清仓茅台",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(
        user_id=user_id, entity_type="Stock", entity_label="600519.SH"
    )
    s.add_all([episode, src, tgt])
    s.flush()

    edge1 = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2024, 8, 1, tzinfo=timezone.utc),
        source_episode_id=episode.episode_id, importance=0.9,
    )
    edge2 = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),  # 不同 valid_from
        source_episode_id=episode.episode_id, importance=0.9,
    )
    s.add_all([edge1, edge2])
    s.commit()  # 不报错


def test_importance_check_constraint_rejects_continuous_value(pg_memory_session):
    """importance 三档 CHECK: 0.7(连续值) raise."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    episode = ChatMemoryEpisode(
        user_id=user_id, session_id=session_id, episode_index=0,
        user_message_text="x",
    )
    src = ChatMemoryNode(user_id=user_id, entity_type="User", entity_label="User")
    tgt = ChatMemoryNode(
        user_id=user_id, entity_type="Stock", entity_label="600519.SH"
    )
    s.add_all([episode, src, tgt])
    s.flush()

    edge = ChatMemoryEdge(
        user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
        rel_type="HOLDS",
        valid_from=datetime(2024, 8, 1, tzinfo=timezone.utc),
        source_episode_id=episode.episode_id,
        importance=0.7,  # 不是 0.9/0.5/0.2
    )
    s.add(edge)
    with pytest.raises(IntegrityError):
        s.commit()


def test_importance_three_tier_values_pass(pg_memory_session):
    """importance ∈ {0.9, 0.5, 0.2} 都 pass."""
    s = pg_memory_session
    user_id, session_id = _seed_user_and_session(s)

    for imp in (0.9, 0.5, 0.2):
        episode = ChatMemoryEpisode(
            user_id=user_id, session_id=session_id,
            episode_index=int(imp * 100),
            user_message_text="x",
        )
        src = ChatMemoryNode(
            user_id=user_id, entity_type="User", entity_label=f"User_{imp}"
        )
        tgt = ChatMemoryNode(
            user_id=user_id, entity_type="Stock", entity_label=f"600519.SH_{imp}"
        )
        s.add_all([episode, src, tgt])
        s.flush()
        edge = ChatMemoryEdge(
            user_id=user_id, source_node_id=src.node_id, target_node_id=tgt.node_id,
            rel_type="HOLDS",
            valid_from=datetime(2024, 8, 1, tzinfo=timezone.utc),
            source_episode_id=episode.episode_id, importance=imp,
        )
        s.add(edge)
        s.commit()
```

**Step 2 — 实现** — 改 barrel:

`backend/app/models/__init__.py`(在 import 区加新 4 行, `__all__` 里加 4 名):

```python
# (在文件已有 import 末尾追加)
from .monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
    Notification,
)
# ↓ NEW: c5 memory schema
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)
```

`__all__` 末尾加 4 个名字:
```python
__all__ = [
    # ... 原有 ...
    "EscalationRecord",
    # c5 memory(Plan 1A)
    "ChatMemoryEpisode",
    "ChatMemoryNode",
    "ChatMemoryEdge",
    "ChatMemoryWorkingBlock",
]
```

> **注**: barrel 的 import 用 `from app.memory.models import ...` 是绝对路径 import, 跟仓库其它 model 的相对路径 `from .monitoring import ...` 不一致, 但 `app.memory.models` 路径稳定且语义清楚, **不放进 backend/app/models/ 子目录**(物理位置在 `app/memory/`, 不是 `app/models/`)。

**Step 3 — 绿测**:

L0 全跑:
```bash
cd backend && uv run pytest tests/unit/memory/ -x -v
```
预期 PASS。

L1 真 PG(本地需 docker compose up postgres):
```bash
cd backend && uv run pytest tests/integration/memory/test_idempotency_constraint_e2e.py -x -v
```
预期: SQL migration 还没写(Task 5)所以可能 GENERATED column / partial index 缺, 但 4 个 test 只用 model + UNIQUE/CHECK constraint, **不依赖 SQL migration**, 应 PASS。

> **若 fail**: 调试 conftest fixture, 或者跳过 SQL migration apply(Task 5/6 ship 后再开)。

**Step 4 — refactor**: 跑 mypy:
```bash
cd backend && uv run mypy app/memory/ app/models/__init__.py
```

**Step 5 — commit**:
```bash
git add backend/app/models/__init__.py \
        backend/tests/integration/memory/__init__.py \
        backend/tests/integration/memory/conftest.py \
        backend/tests/integration/memory/test_idempotency_constraint_e2e.py
git commit -m "feat(c5-plan1a): barrel 注册 + L1 幂等键/CHECK constraint 反向失败测试(#5 算法深度补丁)"
```

---

### Task 5 — SQL migration: partial index / GIN tsvector / 时间区间索引

**目标**: 写 `backend/scripts/migrations/2026-05-11-c5-memory-schema.sql`, 覆盖 SQLAlchemy 表达力外的 PG 特性 — partial index for current snapshot, GENERATED tsvector + GIN, 时间区间复合索引, AGE 扩展加载与图创建。

**Step 1 — 红测**:

`backend/tests/integration/memory/test_pg_schema_e2e.py`:
```python
"""L1 verify SQL migration 应用结果: partial index / GIN tsvector / GENERATED column 都能用."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def test_partial_index_for_unextracted_episodes_exists(pg_memory_fixture):
    """idx_episodes_unextracted partial index 在 pg_indexes 里能查到."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'chat_memory_episodes' "
            "AND indexname = 'idx_episodes_unextracted'"
        )).fetchall()
    assert len(rows) == 1


def test_partial_index_for_current_snapshot_exists(pg_memory_fixture):
    """idx_edges_current_snapshot 是 partial WHERE valid_to IS NULL AND invalidated_at IS NULL."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'chat_memory_edges' "
            "AND indexname = 'idx_edges_current_snapshot'"
        )).fetchall()
    assert len(rows) == 1
    indexdef = rows[0][0]
    # partial index 必须 WHERE 含两个条件
    assert "valid_to IS NULL" in indexdef
    assert "invalidated_at IS NULL" in indexdef


def test_valid_range_index_exists(pg_memory_fixture):
    """idx_edges_valid_range B-tree 复合索引(user_id, valid_from, valid_to) 存在."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'chat_memory_edges' "
            "AND indexname = 'idx_edges_valid_range'"
        )).fetchall()
    assert len(rows) == 1


def test_search_vector_generated_on_nodes(pg_memory_fixture):
    """nodes.search_vector 是 GENERATED ALWAYS AS to_tsvector('simple', search_tokens) STORED."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT column_name, data_type, is_generated, generation_expression "
            "FROM information_schema.columns "
            "WHERE table_name = 'chat_memory_nodes' "
            "AND column_name = 'search_vector'"
        )).fetchall()
    assert len(rows) == 1
    col, dt, is_gen, gen_expr = rows[0]
    assert dt.lower() == "tsvector"
    assert is_gen == "ALWAYS"
    assert "search_tokens" in (gen_expr or "")


def test_gin_index_on_nodes_search_vector(pg_memory_fixture):
    """idx_nodes_search_gin USING GIN(search_vector)."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'chat_memory_nodes' "
            "AND indexname = 'idx_nodes_search_gin'"
        )).fetchall()
    assert len(rows) == 1
    assert "gin" in rows[0][0].lower()


def test_search_vector_generated_on_edges(pg_memory_fixture):
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT column_name, is_generated FROM information_schema.columns "
            "WHERE table_name = 'chat_memory_edges' "
            "AND column_name = 'search_vector'"
        )).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "ALWAYS"


def test_gin_index_on_edges_search_vector(pg_memory_fixture):
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'chat_memory_edges' "
            "AND indexname = 'idx_edges_search_gin'"
        )).fetchall()
    assert len(rows) == 1
    assert "gin" in rows[0][0].lower()


def test_search_vector_populated_from_search_tokens(pg_memory_fixture):
    """直接 INSERT search_tokens, GENERATED search_vector 自动产生."""
    engine = pg_memory_fixture["engine"]
    with engine.begin() as conn:
        node_id = str(uuid.uuid4())
        # 拿一个 user_id(任意, 满足 FK)
        user_id = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar()
        if user_id is None:
            pytest.skip("no user exists; need users seed")
        conn.execute(text(
            "INSERT INTO chat_memory_nodes "
            "(node_id, user_id, entity_type, entity_label, search_tokens) "
            "VALUES (:nid, :uid, 'Stock', :label, '茅台 贵州 白酒')"
        ), {"nid": node_id, "uid": str(user_id), "label": f"x_{node_id[:6]}"})
        # 用 GIN 检索
        rows = conn.execute(text(
            "SELECT node_id FROM chat_memory_nodes "
            "WHERE search_vector @@ to_tsquery('simple', '茅台') "
            "AND node_id = :nid"
        ), {"nid": node_id}).fetchall()
        assert len(rows) == 1
```

跑(应 fail, migration 还没写):
```bash
cd backend && uv run pytest tests/integration/memory/test_pg_schema_e2e.py -x -v
```

**Step 2 — 实现**:

`backend/scripts/migrations/2026-05-11-c5-memory-schema.sql`:
```sql
-- C.5 Cross-session memory schema migration.
-- Spec: docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md § 2
-- Plan: docs/superpowers/plans/2026-05-11-c5-plan1a-storage-foundation.md
--
-- Idempotent: 安全多次运行(IF NOT EXISTS / DROP-and-recreate-when-needed pattern)。
-- 应用时机: app_main.lifespan create_all() 之后, 或 tests fixture 应用一次。

-- ===========================================================================
-- 1. partial index for unextracted episodes(spec § 2 行 158-159)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_episodes_unextracted
  ON chat_memory_episodes(user_id)
  WHERE extracted_at IS NULL;

-- ===========================================================================
-- 2. GENERATED tsvector + GIN index on nodes(spec § 2 行 173-180)
-- ===========================================================================
-- 注: GENERATED column 加在 ALTER TABLE 时, 不能用 IF NOT EXISTS for column;
-- 用 DO block 检查 column 不存在再 ADD.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'chat_memory_nodes' AND column_name = 'search_vector'
  ) THEN
    ALTER TABLE chat_memory_nodes
      ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(search_tokens, ''))
      ) STORED;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_nodes_search_gin
  ON chat_memory_nodes USING GIN(search_vector);

-- ===========================================================================
-- 3. GENERATED tsvector + GIN index on edges(spec § 2 行 205-208 + 215)
-- ===========================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'chat_memory_edges' AND column_name = 'search_vector'
  ) THEN
    ALTER TABLE chat_memory_edges
      ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(search_tokens, ''))
      ) STORED;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_edges_search_gin
  ON chat_memory_edges USING GIN(search_vector);

-- ===========================================================================
-- 4. Partial index for "current snapshot"(spec § 2 行 217-220)
--    高频 query: 当前持仓 / 偏好(valid_to IS NULL AND invalidated_at IS NULL)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_edges_current_snapshot
  ON chat_memory_edges(user_id, source_node_id, target_node_id)
  WHERE valid_to IS NULL AND invalidated_at IS NULL;

-- ===========================================================================
-- 5. 时间区间复合索引(spec § 2 行 222-224)
-- ===========================================================================

CREATE INDEX IF NOT EXISTS idx_edges_valid_range
  ON chat_memory_edges(user_id, valid_from, valid_to);

-- ===========================================================================
-- 6. AGE 扩展加载 + 'chat_memory' 图 + 7 vlabel + 11 elabel
--    (spec § 2 行 274-302)
--    若 AGE 不可用, 用 DO block 把全部 AGE 命令包起来, exception swallow.
--    L1 fixture 探测, 真不可用时 skip 测试。
-- ===========================================================================

DO $age$ BEGIN
  -- 加载 AGE 扩展
  CREATE EXTENSION IF NOT EXISTS age;
  LOAD 'age';
  -- AGE 要求 search_path 含 ag_catalog
  PERFORM set_config('search_path', 'ag_catalog,"$user",public', false);

  -- 创建图(若不存在)
  IF NOT EXISTS (
    SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'chat_memory'
  ) THEN
    PERFORM ag_catalog.create_graph('chat_memory');
  END IF;

  -- 7 vlabel(create_vlabel 内部已有"已存在则跳过"语义, 但保险用 EXCEPTION 包裹)
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'User'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Stock'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Industry'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Sector'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Metric'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Strategy'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_vlabel('chat_memory', 'Concept'); EXCEPTION WHEN OTHERS THEN NULL; END;

  -- 11 elabel
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'HOLDS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'WATCHES'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'PREFERS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'AVOIDS'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'EXPRESSED_VIEW'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'SOLD'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'STUDIED'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'COMPARED'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'BELONGS_TO'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'HAS_CONCEPT'); EXCEPTION WHEN OTHERS THEN NULL; END;
  BEGIN PERFORM ag_catalog.create_elabel('chat_memory', 'CORRELATED_WITH'); EXCEPTION WHEN OTHERS THEN NULL; END;

EXCEPTION WHEN undefined_file OR undefined_object OR feature_not_supported THEN
  -- AGE 扩展未编译进 PG / 镜像不带 AGE → silent skip(测试 fixture 单独 verify)
  RAISE NOTICE 'AGE extension not available; skipping graph setup';
END $age$;
```

**Step 3 — 绿测**:

```bash
cd backend && uv run pytest tests/integration/memory/test_pg_schema_e2e.py -x -v
```

**关键注意点**:
- migration 要在 fixture 里 apply 一次(conftest 已 wired Task 4)
- AGE 扩展若 PG 镜像不带, DO block silent skip — `test_age_graph_e2e.py`(Task 6) 探测 AGE 可用否再 skip
- 若 dev 用现有 `apache/age` 镜像 OK; postgres:15 不带 AGE → 改 docker-compose 或装 contrib

**docker-compose.yml 同步检查**(若 PG image 不带 AGE):

读 `/Users/talantan/.openclaw/workspace-main/financial-research-assistant/docker-compose.yml` 看 postgres image; 若是 `postgres:15-alpine` 等不带 AGE, 加注释说明 "AGE extension optional, only L1 AGE tests need it; CI 暂不强 require"。本 plan 不动 docker-compose(等 Plan 4 用 AGE traverse 时再切镜像)。

**Step 4 — refactor**: 检查 SQL 命令幂等性(全跑两次不报错):
```bash
docker exec <pg-container> psql -U postgres -d industry_assistant_test \
  -f /path/to/2026-05-11-c5-memory-schema.sql
docker exec <pg-container> psql -U postgres -d industry_assistant_test \
  -f /path/to/2026-05-11-c5-memory-schema.sql
# 第二次必须无报错
```

**Step 5 — commit**:
```bash
git add backend/scripts/migrations/2026-05-11-c5-memory-schema.sql \
        backend/tests/integration/memory/test_pg_schema_e2e.py
git commit -m "feat(c5-plan1a): SQL migration — partial index / GIN tsvector / 时间区间索引 / AGE 图"
```

---

### Task 6 — AGE 'chat_memory' 图 L1 验证

**目标**: 单独写 AGE 图测试, 验证 7 vlabel + 11 elabel 已建 + Cypher 基本可执行。AGE 不可用时 skip 但不 fail。

**Step 1 — 红测**:

`backend/tests/integration/memory/test_age_graph_e2e.py`:
```python
"""L1 verify AGE 'chat_memory' graph + 7 vlabel + 11 elabel.

AGE 不可用时 skip(macOS dev / postgres:15 镜像无 AGE 扩展)。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _age_available(engine) -> bool:
    """Probe AGE 扩展是否真的加载."""
    try:
        with engine.begin() as conn:
            conn.execute(text("LOAD 'age'"))
            rows = conn.execute(text(
                "SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'chat_memory'"
            )).fetchall()
            return len(rows) == 1
    except Exception:
        return False


def test_age_chat_memory_graph_exists(pg_memory_fixture):
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available in this PG instance")

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT name FROM ag_catalog.ag_graph WHERE name = 'chat_memory'"
        )).fetchall()
    assert len(rows) == 1


@pytest.mark.parametrize("vlabel", [
    "User", "Stock", "Industry", "Sector", "Metric", "Strategy", "Concept",
])
def test_all_7_vlabels_created(pg_memory_fixture, vlabel):
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")
    with engine.begin() as conn:
        # ag_label.kind = 'v' (vertex)
        rows = conn.execute(text(
            "SELECT name FROM ag_catalog.ag_label "
            "WHERE name = :n AND kind = 'v'"
        ), {"n": vlabel}).fetchall()
    assert len(rows) == 1, f"vlabel {vlabel} not created"


@pytest.mark.parametrize("elabel", [
    "HOLDS", "WATCHES", "PREFERS", "AVOIDS", "EXPRESSED_VIEW", "SOLD",
    "STUDIED", "COMPARED", "BELONGS_TO", "HAS_CONCEPT", "CORRELATED_WITH",
])
def test_all_11_elabels_created(pg_memory_fixture, elabel):
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT name FROM ag_catalog.ag_label "
            "WHERE name = :n AND kind = 'e'"
        ), {"n": elabel}).fetchall()
    assert len(rows) == 1, f"elabel {elabel} not created"


def test_basic_cypher_create_match(pg_memory_fixture):
    """smoke: Cypher CREATE + MATCH 通."""
    engine = pg_memory_fixture["engine"]
    if not _age_available(engine):
        pytest.skip("AGE extension not available")

    with engine.begin() as conn:
        conn.execute(text("LOAD 'age'"))
        conn.execute(text("SET search_path = ag_catalog, public"))
        # CREATE Stock node
        conn.execute(text("""
            SELECT * FROM cypher('chat_memory', $$
                CREATE (s:Stock {ts_code: '600519.SH'})
                RETURN s
            $$) AS (s ag_catalog.agtype)
        """))
        # MATCH 回来
        rows = conn.execute(text("""
            SELECT * FROM cypher('chat_memory', $$
                MATCH (s:Stock {ts_code: '600519.SH'})
                RETURN s
            $$) AS (s ag_catalog.agtype)
        """)).fetchall()
        assert len(rows) >= 1
        # 清理避免污染
        conn.execute(text("""
            SELECT * FROM cypher('chat_memory', $$
                MATCH (s:Stock {ts_code: '600519.SH'})
                DELETE s
            $$) AS (deleted ag_catalog.agtype)
        """))
```

**Step 2 — 实现**: AGE 图创建已在 Task 5 SQL migration 完成, 本 task 只补 test。

**Step 3 — 绿测**:
```bash
cd backend && uv run pytest tests/integration/memory/test_age_graph_e2e.py -x -v
```
- AGE 镜像 → 全 PASS
- 普通 PG 镜像 → 全 SKIP(不报红, 健壮 fallback)

**Step 4 — refactor**: N/A。

**Step 5 — commit**:
```bash
git add backend/tests/integration/memory/test_age_graph_e2e.py
git commit -m "test(c5-plan1a): L1 AGE chat_memory graph + 7 vlabel + 11 elabel(AGE 不可用时 skip)"
```

---

### Task 7 — Milvus chat_memory_edge_embeddings collection + alias

**目标**: 创建 Milvus collection(schema 按 spec § 2 行 304-318)+ alias 模式给 § 11 #1 触发后做留口子。

**Step 1 — 红测**:

`backend/tests/integration/memory/conftest.py`(扩展, 加 milvus_memory_fixture):
```python
# (在 Task 4 conftest 末尾追加)


# ---------------------------------------------------------------------------
# milvus_memory_fixture — 真 Milvus + chat_memory_edge_embeddings_v1 + alias
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def milvus_memory_fixture(milvus_test_container):
    """Real Milvus + chat_memory_edge_embeddings_v1 collection + alias 已建.

    依赖 backend/tests/conftest.py 的 milvus_test_container(已 ship v0.7)。
    """
    from app.memory.milvus_setup import (
        ALIAS_NAME,
        COLLECTION_V1_NAME,
        ensure_chat_memory_edge_collection,
    )

    host = milvus_test_container["host"]
    port = milvus_test_container["port"]

    # 幂等创建
    ensure_chat_memory_edge_collection(host=host, port=port)

    yield {
        "host": host,
        "port": port,
        "collection_name": COLLECTION_V1_NAME,
        "alias_name": ALIAS_NAME,
    }

    # session 末不清理(跟 milvus_test_container 同 fail-safe)
```

`backend/tests/integration/memory/test_milvus_collection_e2e.py`:
```python
"""L1 verify Milvus chat_memory_edge_embeddings_v1 + alias 模式."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_MILVUS_TESTS") == "1",
    reason="Milvus container required",
)


def test_collection_exists_under_versioned_name(milvus_memory_fixture):
    """真实 collection 名是 chat_memory_edge_embeddings_v1(带版本后缀)."""
    from pymilvus import MilvusClient
    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    assert client.has_collection("chat_memory_edge_embeddings_v1")


def test_alias_points_to_v1(milvus_memory_fixture):
    """alias chat_memory_edge_embeddings_current → chat_memory_edge_embeddings_v1."""
    from pymilvus import MilvusClient
    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    aliases = client.list_aliases(collection_name="chat_memory_edge_embeddings_v1")
    # list_aliases 返回 dict 含 'aliases' key
    alias_list = aliases.get("aliases", []) if isinstance(aliases, dict) else aliases
    assert "chat_memory_edge_embeddings_current" in alias_list


def test_schema_has_required_fields(milvus_memory_fixture):
    """schema: edge_id Int64 PK / user_id VarChar / embedding FloatVector(1024) / rel_type VarChar."""
    from pymilvus import MilvusClient
    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )
    desc = client.describe_collection(collection_name="chat_memory_edge_embeddings_v1")
    field_names = {f["name"]: f for f in desc["fields"]}
    assert "edge_id" in field_names
    assert "user_id" in field_names
    assert "embedding" in field_names
    assert "rel_type" in field_names

    # embedding dim == 1024
    emb_field = field_names["embedding"]
    assert emb_field.get("params", {}).get("dim") == 1024


def test_can_insert_and_search_via_alias(milvus_memory_fixture):
    """通过 alias 名写入 + 检索 — 确认 alias 完全等价 collection."""
    from pymilvus import MilvusClient
    client = MilvusClient(
        uri=f"http://{milvus_memory_fixture['host']}:{milvus_memory_fixture['port']}"
    )

    alias = "chat_memory_edge_embeddings_current"
    # insert via alias
    vec = [0.1] * 1024
    rows = [{
        "edge_id": 999001,
        "user_id": "test-user-1",
        "embedding": vec,
        "rel_type": "HOLDS",
    }]
    client.insert(collection_name=alias, data=rows)
    client.flush(alias)

    # search via alias
    results = client.search(
        collection_name=alias,
        data=[vec],
        anns_field="embedding",
        limit=1,
        output_fields=["edge_id", "rel_type"],
    )
    assert len(results) == 1
    assert results[0][0]["entity"]["edge_id"] == 999001

    # 清理
    client.delete(collection_name=alias, filter="edge_id == 999001")
```

跑(应 fail, milvus_setup.py 还没写):
```bash
cd backend && uv run pytest tests/integration/memory/test_milvus_collection_e2e.py -x -v
```

**Step 2 — 实现**:

`backend/app/memory/milvus_setup.py`:
```python
"""Milvus collection setup for C.5 chat_memory edge embeddings.

Spec § 2 行 304-318:
    collection = "chat_memory_edge_embeddings"
    schema = {edge_id Int64, user_id VarChar(36), embedding FloatVector(1024), rel_type VarChar(32)}

Plan 1A 决策(spec § 11 末尾 #1 触发后做留口子):
    真实 collection 名带版本后缀 chat_memory_edge_embeddings_v1
    业务代码统一通过 alias chat_memory_edge_embeddings_current 引用
    向量模型升级时建 _v2 + alias 切换 — 本 plan 不实现升级流程

复用 v0.7 KB Milvus client 模式(backend/app/services/milvus_client.py):
    - HNSW index on embedding field, COSINE metric
    - load_collection 在 ensure 后调一次(spec sediment: feedback_milvus_load_after_index.md)
"""

from __future__ import annotations

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient

EMBEDDING_DIM = 1024  # qwen text-embedding-v3(契约 § 9 同)

COLLECTION_V1_NAME = "chat_memory_edge_embeddings_v1"
"""真实 collection 名(带版本后缀, 给 #1 向量模型升级 hook 留口子)."""

ALIAS_NAME = "chat_memory_edge_embeddings_current"
"""业务代码引用名 — Plan 2-5 检索 / 写入只用 alias, 升级时 alias 切换零代码改动."""


def _build_schema() -> CollectionSchema:
    """Spec § 2 行 308-313."""
    fields = [
        FieldSchema("edge_id", DataType.INT64, is_primary=True, description="PG chat_memory_edges.edge_id"),
        FieldSchema("user_id", DataType.VARCHAR, max_length=36, description="多租户隔离"),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
        FieldSchema("rel_type", DataType.VARCHAR, max_length=32),
    ]
    return CollectionSchema(
        fields=fields,
        description=(
            "C.5 chat_memory edge embeddings (qwen v3 1024d). "
            "Embed text template: '{rel_type} {src_label} → {tgt_label} reasoning=...'. "
            "Plan 1A schema; Plan 2 写入; Plan 3 检索."
        ),
    )


def ensure_chat_memory_edge_collection(*, host: str, port: int) -> None:
    """幂等创建 collection v1 + HNSW index + alias.

    第一次跑: create_collection + create_index + load + create_alias
    重复跑: skip(has_collection / has_alias)
    """
    client = MilvusClient(uri=f"http://{host}:{port}")

    # 1. collection
    if not client.has_collection(COLLECTION_V1_NAME):
        schema = _build_schema()
        client.create_collection(
            collection_name=COLLECTION_V1_NAME,
            schema=schema,
        )

        # 2. HNSW index on embedding(跟 v0.7 KB 同款参数)
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        client.create_index(
            collection_name=COLLECTION_V1_NAME,
            index_params=index_params,
        )

    # 3. load collection(必须在 create_index 之后, sediment: feedback_milvus_load_after_index.md)
    client.load_collection(COLLECTION_V1_NAME)

    # 4. alias(幂等: alter_alias 把已有 alias 重新指向, 不存在则 create)
    try:
        existing_aliases = client.list_aliases(collection_name=COLLECTION_V1_NAME)
        alias_list = (
            existing_aliases.get("aliases", [])
            if isinstance(existing_aliases, dict)
            else existing_aliases
        )
        if ALIAS_NAME not in alias_list:
            client.create_alias(
                collection_name=COLLECTION_V1_NAME,
                alias=ALIAS_NAME,
            )
    except Exception:
        # 兜底: list_aliases / create_alias API 在不同 pymilvus 版本签名有差异
        try:
            client.create_alias(
                collection_name=COLLECTION_V1_NAME,
                alias=ALIAS_NAME,
            )
        except Exception:
            pass  # alias 已存在
```

**Step 3 — 绿测**:
```bash
cd backend && uv run pytest tests/integration/memory/test_milvus_collection_e2e.py -x -v
```
预期: PASS(需要 milvus_test_container 起来 — 本地 `docker compose -f backend/docker-compose.milvus.yml up -d`)。

**Step 4 — refactor**: 跑 mypy:
```bash
cd backend && uv run mypy app/memory/milvus_setup.py
```

**Step 5 — commit**:
```bash
git add backend/app/memory/milvus_setup.py \
        backend/tests/integration/memory/test_milvus_collection_e2e.py \
        backend/tests/integration/memory/conftest.py
git commit -m "feat(c5-plan1a): Milvus chat_memory_edge_embeddings collection + alias 模式(给 #1 向量升级 hook 留口子)"
```

---

### Task 8 — `app_main.lifespan` apply SQL migration + Milvus ensure(幂等)

**目标**: serve path 启动时自动 apply C.5 SQL migration + ensure Milvus collection, 跟 PR #21 / v0.9.x 已有 langgraph-pg-schema.sql 同款 pattern。**幂等 + 不阻塞启动**(PG/Milvus 不可用只 warn)。

> v0.9.x sediment: `feedback_serve_path_no_ci_coverage.md` — 改 app_main 必须本地 import smoke。本 task 末尾 Step 4 强制跑 `python -c "from app.app_main import app"`。

**Step 1 — 红测**:

`backend/tests/integration/memory/test_serve_path_lifespan_smoke.py`:
```python
"""L1 verify app_main.lifespan 起来能 apply C.5 migration + ensure Milvus collection.

依赖 pg_test_container + milvus_test_container 都 up。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1" or os.environ.get("SKIP_MILVUS_TESTS") == "1",
    reason="PG + Milvus required",
)


def test_app_main_imports_without_error():
    """import smoke — 不能因 c5 migration apply 把 lifespan 撞挂."""
    from app.app_main import app  # noqa: F401


@pytest.mark.asyncio
async def test_lifespan_applies_c5_migration(
    pg_test_container, milvus_test_container, monkeypatch
):
    """fastapi lifespan startup → c5 schema 已 apply, c5 collection 已建."""
    monkeypatch.setenv("POSTGRES_HOST", str(pg_test_container["host"]))
    monkeypatch.setenv("POSTGRES_PORT", str(pg_test_container["port"]))
    monkeypatch.setenv("POSTGRES_DB", str(pg_test_container["db"]))
    monkeypatch.setenv("MILVUS_HOST", str(milvus_test_container["host"]))
    monkeypatch.setenv("MILVUS_PORT", str(milvus_test_container["port"]))

    from fastapi.testclient import TestClient
    from app.app_main import app

    with TestClient(app):
        # lifespan startup 已跑
        from sqlalchemy import create_engine, text
        engine = create_engine(pg_test_container["url"])
        with engine.begin() as conn:
            # partial index 应当存在
            rows = conn.execute(text(
                "SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'idx_edges_current_snapshot'"
            )).fetchall()
            assert len(rows) == 1

        from pymilvus import MilvusClient
        m = MilvusClient(
            uri=f"http://{milvus_test_container['host']}:{milvus_test_container['port']}"
        )
        assert m.has_collection("chat_memory_edge_embeddings_v1")
```

**Step 2 — 实现** — 改 `backend/app/app_main.py` lifespan:

定位现有 lifespan(行 75-95 左右)的 `Base.metadata.create_all(...)` 之后, 加一段 c5 specific 的 apply migration + ensure milvus:

```python
# 在 lifespan() 里, 紧跟 `Base.metadata.create_all(bind=engine)` 之后追加:

    # C.5 cross-session memory: apply SQL migration(partial index / GIN / AGE 图).
    # 幂等(IF NOT EXISTS), PG 不可用时只 warn 不阻塞启动(serve path 不强依赖 c5)。
    try:
        from pathlib import Path
        from sqlalchemy import text as _sql_text

        c5_migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrations"
            / "2026-05-11-c5-memory-schema.sql"
        )
        if c5_migration.exists():
            sql = c5_migration.read_text(encoding="utf-8")
            with engine.begin() as conn:
                conn.execute(_sql_text(sql))
            logger.info("C.5 memory SQL migration applied")
    except Exception as e:  # noqa: BLE001
        logger.warning("C.5 memory SQL migration skipped: %s", e)

    # C.5 Milvus collection ensure(幂等). Milvus 不可用时只 warn。
    try:
        milvus_host = os.getenv("MILVUS_HOST", "127.0.0.1")
        milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
        from app.memory.milvus_setup import ensure_chat_memory_edge_collection
        ensure_chat_memory_edge_collection(host=milvus_host, port=milvus_port)
        logger.info("C.5 Milvus chat_memory_edge_embeddings ensured")
    except Exception as e:  # noqa: BLE001
        logger.warning("C.5 Milvus collection ensure skipped: %s", e)
```

**Step 3 — 绿测**:

```bash
cd backend && uv run pytest tests/integration/memory/test_serve_path_lifespan_smoke.py -x -v
```

**Step 4 — refactor — serve path import smoke**(必须做 — sediment 教训):

```bash
cd backend && uv run python -c "from app.app_main import app; print('OK')"
```

预期: 输出 `OK`(本地有 PG/Milvus)或 warn log + 输出 `OK`(无)。

**Step 5 — commit**:
```bash
git add backend/app/app_main.py \
        backend/tests/integration/memory/test_serve_path_lifespan_smoke.py
git commit -m "feat(c5-plan1a): app_main.lifespan apply C.5 migration + ensure Milvus collection(幂等)"
```

---

## 4. Self-Review Checklist

执行 plan 末尾自检, 全部勾完才算 ship。

### 4.1 Spec coverage

- [x] **§ 2 表 1 chat_memory_episodes** — Task 2 model 11 字段 + UNIQUE(session_id, episode_index) + idx_episodes_user_session + idx_episodes_unextracted partial(Task 5)
- [x] **§ 2 表 2 chat_memory_nodes** — Task 2 model 7 字段 + UNIQUE(user_id, entity_type, entity_label) + idx_nodes_user_type + GENERATED tsvector + GIN(Task 5)
- [x] **§ 2 表 3 chat_memory_edges** — Task 2 model 14 字段(含 bi-temporal 4 + provenance 3)+ 4 B-tree index + GENERATED tsvector + GIN(Task 5)+ partial index for current snapshot(Task 5)+ 时间区间索引(Task 5)
- [x] **§ 2 表 4 chat_memory_working_blocks** — Task 2 model 7 字段 + UNIQUE(user_id, block_name)
- [x] **§ 2 AGE 图设置** — Task 5 SQL migration: CREATE EXTENSION + LOAD + create_graph + 7 vlabel + 11 elabel; Task 6 L1 verify
- [x] **§ 2 Milvus 集合** — Task 7 milvus_setup.py: chat_memory_edge_embeddings_v1 + 4 字段 schema + HNSW index + alias 模式

### 4.2 算法深度补丁(§ 11 末尾 #5 三方一致性 — 幂等键部分)

- [x] **#5 幂等键 UNIQUE constraint** — Task 2 model: `UniqueConstraint("source_episode_id", "source_node_id", "target_node_id", "rel_type", "valid_from", name="uq_edges_idempotency_key")`
- [x] **#5 反向失败 L1 测试** — Task 4 `test_idempotency_key_blocks_duplicate_insert` + `test_idempotency_allows_different_valid_from`
- [x] **#5 reconciliation job 骨架** — **明确不做, 留 Plan 1B**(契约 § 11 矩阵: Plan 1 ship 幂等键, Plan 1B ship reconciliation 骨架)

### 4.3 算法深度补丁(§ 11 末尾 #3 importance 三档 — schema 部分)

- [x] **importance 三档 CHECK constraint** — Task 2 model: `CheckConstraint("importance IS NULL OR importance IN (0.9, 0.5, 0.2)", name="ck_edges_importance_three_tier")`
- [x] **L1 反向失败测试** — Task 4 `test_importance_check_constraint_rejects_continuous_value` + `test_importance_three_tier_values_pass`
- 注: RRF v2 时间感知公式 / τ 按 rel_type / 后验校准 — 全部 **Plan 3 ship**, 本 plan 只兑现 schema 层 CHECK

### 4.4 算法深度补丁(§ 11 末尾 #1 向量模型升级 — 留口子部分)

- [x] **Milvus alias 模式** — Task 7 milvus_setup.py: `COLLECTION_V1_NAME = "chat_memory_edge_embeddings_v1"` + `ALIAS_NAME = "chat_memory_edge_embeddings_current"`, 业务代码全用 alias
- 注: dual-write 重算流程 / embedding_version 字段 — 触发后做(qwen v3→v4 时), 不进 Plan 1-8

### 4.5 契约 § 4 字段对齐(逐字段 grep)

- [x] **chat_memory_episodes** 11 字段名跟契约 § 4 完全一致
- [x] **chat_memory_nodes** 7 字段名一致(注: search_vector tsvector 在 SQL migration 加, model 不写, 契约也已注释)
- [x] **chat_memory_edges** 14 字段名一致(注: 同上 search_vector)
- [x] **chat_memory_working_blocks** 7 字段名一致
- [x] **类型一致** — UUID 全用 PgUUID + with_variant, JSONB 同, TIMESTAMPTZ 用 DateTime(timezone=True)
- [x] **constraint 命名一致** — uq_episodes_session_idx / uq_nodes_user_type_label / uq_edges_idempotency_key / ck_edges_importance_three_tier / uq_working_blocks_user_name
- [x] **index 命名一致** — idx_episodes_user_session / idx_nodes_user_type / idx_edges_user_rel|source|target|episode

### 4.6 不在范围确认(交给 Plan 1B / 2-8 — 无误改)

- [x] **Plan 1B 范围** — protocol.py / hierarchical.py(class 骨架 + DI)/ registry.py / working_blocks.py CRUD / cold_start.py / reconciliation.py 骨架 / DI 替换 InSessionMemory — **本 plan 全部不动**
- [x] **Plan 2 范围** — extractor.py / conflict_resolver.py / 8 step 写入 pipeline / outbox sync — 本 plan 不动
- [x] **Plan 3 范围** — retriever.py / rrf.py(RRF v2 公式)/ persona_populator.py — 本 plan 不动
- [x] **Plan 4 范围** — 6 MCP tools / evidence_quote 校验 — 本 plan 不动

### 4.7 v0.9.x sediment 守护

- [x] **`feedback_serve_path_no_ci_coverage.md`** — Task 8 Step 4 显式 `python -c "from app.app_main import app"` import smoke, 不依赖 pytest 走过
- [x] **`feedback_milvus_load_after_index.md`** — Task 7 milvus_setup.py: create_collection → create_index → **load_collection** → create_alias
- [x] **`feedback_legacy_barrel_eager_import_rot.md`** — Task 4 改 barrel: `from app.memory.models import (...)` 直接绝对路径, 不在 backend/app/models/ 物理位置, 减少 barrel 拖累其它 import chain
- [x] **`feedback_unguarded_imports_after_delete.md`** — 本 plan 只加文件不删, 不适用
- [x] **`feedback_path_resolution_in_plans.md`** — Task 8 lifespan migration path 用 `Path(__file__).resolve().parents[1]` 锚 `backend/`, 不依赖 cwd
- [x] **`feedback_pytest_layer_env.md`** — L0 用 sqlite override 不靠环境变量, L1 用 pg_test_container fixture(已 ship)

### 4.8 commit 规范

- 每 task 一个 commit(共 8), prefix 全是 `feat(c5-plan1a):` / `chore(c5-plan1a):` / `test(c5-plan1a):`
- 无 `fix(c5-plan1a):` commit(本 plan 全新)— `feedback_fix_commit_layer_marker.md` 不适用

### 4.9 工程量自评

| Task | 估时(h) |
|---|---|
| 1 包 scaffold | 0.5 |
| 2 4 model | 4 |
| 3 L0 schema test | 2 |
| 4 barrel + L1 幂等键 test | 3 |
| 5 SQL migration | 4 |
| 6 AGE L1 test | 2 |
| 7 Milvus collection + alias + L1 test | 4 |
| 8 lifespan migration apply + serve smoke | 2 |
| 调试 / mypy / 文档梳理 | 4 |
| **总计** | **~25.5 h ≈ 4 个工作日** |

跟范围标的 4 天对齐 ✓。

### 4.10 ship 后产物清单

```
新增:
  backend/app/memory/__init__.py
  backend/app/memory/models.py              (~190 行)
  backend/app/memory/milvus_setup.py        (~80 行)
  backend/scripts/migrations/2026-05-11-c5-memory-schema.sql  (~120 行)
  backend/tests/unit/memory/__init__.py
  backend/tests/unit/memory/test_models.py
  backend/tests/integration/memory/__init__.py
  backend/tests/integration/memory/conftest.py
  backend/tests/integration/memory/test_idempotency_constraint_e2e.py
  backend/tests/integration/memory/test_pg_schema_e2e.py
  backend/tests/integration/memory/test_age_graph_e2e.py
  backend/tests/integration/memory/test_milvus_collection_e2e.py
  backend/tests/integration/memory/test_serve_path_lifespan_smoke.py

修改:
  backend/app/models/__init__.py            (barrel 加 4 import + __all__ 加 4 名)
  backend/app/app_main.py                   (lifespan 加 c5 migration apply + milvus ensure)
```

测试覆盖:
- L0 unit: 14+ test(field / constraint / index / sqlite create_all)
- L1 integration: 12+ test(幂等键 / CHECK / partial index / GIN / AGE / Milvus collection / alias / lifespan smoke)

---

## 5. 下一 plan 解锁条件(给 Plan 1B 看)

Plan 1A ship 后, Plan 1B 可立即起步, 假设以下都成立:

1. `app.memory.models` 4 model 可 import, ORM 写入 PG 工作
2. `app.memory.milvus_setup.ensure_chat_memory_edge_collection()` 可调用, 幂等
3. `pg_memory_fixture` / `milvus_memory_fixture` 在 `backend/tests/integration/memory/conftest.py` 可复用
4. `Base.metadata.create_all()` + SQL migration 应用结果跟 spec § 2 schema 完全对齐
5. 幂等键 + importance CHECK 已 verify(L1 反向失败 PASS)

Plan 1B 起手第一步: 写 `backend/app/memory/protocol.py` Memory Protocol(契约 § 2 已定义), 接 InSessionMemory stub 这些方法, 然后写 `hierarchical.py` class 骨架 + Plan 1 范围 6 个方法。

---

## 6. Post-ship 任务(Plan 1A 收尾 — 不算实施时间, 但 ship checklist 必填)

- [ ] 写知识卡 `docs/claude-context/c5-plan1a-storage-foundation-done.md`(契约 § 13 模板)
- [ ] CLAUDE.md 索引区"v0.9+ roadmap"小节追加 `c5-plan1a-storage-foundation-done.md` 引用
- [ ] PR description: 引用 spec § 2 + § 11 末尾 #5 行号, 列 Self-review checklist 4.1-4.7 全勾
- [ ] PR body 加一段 "下游解锁: Plan 1B 可起 / Plan 2-8 schema 层就绪"

---

## 附录 A: 命令快查

```bash
# 全套 L0
cd backend && uv run pytest tests/unit/memory/ -x -v

# 全套 L1(本地需 docker compose up postgres milvus)
cd backend && uv run pytest tests/integration/memory/ -x -v

# mypy
cd backend && uv run mypy app/memory/ app/models/__init__.py

# 跑特定文件
cd backend && uv run pytest tests/integration/memory/test_idempotency_constraint_e2e.py -x -v

# serve path smoke
cd backend && uv run python -c "from app.app_main import app; print('OK')"

# 起 PG container
docker compose up -d postgres

# 起 Milvus container
docker compose -f backend/docker-compose.milvus.yml up -d

# 手动 apply C.5 migration(幂等)
docker exec <pg-container> psql -U postgres -d industry_assistant_test \
  -f /path/to/backend/scripts/migrations/2026-05-11-c5-memory-schema.sql
```

## 附录 B: 关键 ref 文档

| 文档 | 用途 |
|---|---|
| `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 2 | schema 总规格 |
| `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 11 末尾 #5 | 幂等键算法深度补丁 |
| `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 11 末尾 #3 | importance 三档(schema 兑现 CHECK)|
| `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` § 11 末尾 #1 | 向量模型升级(本 plan 留 alias 口子)|
| `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 4 | SQLAlchemy model 字段名硬约束 |
| `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` § 6 | 测试 fixture 命名约定 |
| `backend/app/models/monitoring.py` | SQLAlchemy 风格参考(v1.0 ship)|
| `backend/scripts/migrations/2026-05-09-langgraph-pg-schema.sql` | SQL migration 风格参考(v0.9.x ship)|
| `backend/app/services/milvus_client.py` | Milvus collection setup 风格参考(v0.7 ship)|
| `backend/app/app_main.py` lifespan | create_all + migration apply pattern |

---

**END OF PLAN 1A**
