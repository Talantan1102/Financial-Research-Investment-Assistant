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

from uuid import uuid4

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
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811  (re-alias to disambiguate from stdlib uuid.UUID)
)
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
        UniqueConstraint("user_id", "entity_type", "entity_label", name="uq_nodes_user_type_label"),
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
    source_node_id = Column(_UUID, ForeignKey("chat_memory_nodes.node_id"), nullable=False)
    target_node_id = Column(_UUID, ForeignKey("chat_memory_nodes.node_id"), nullable=False)
    rel_type = Column(String(32), nullable=False)

    # ====== bi-temporal 4 字段(spec § 2 行 193-197) ======
    valid_from = Column(_TS, nullable=False)
    valid_to = Column(_TS, nullable=True)
    recorded_at = Column(_TS, nullable=False, server_default=func.now())
    invalidated_at = Column(_TS, nullable=True)

    # ====== provenance(spec § 2 行 199-202) ======
    source_episode_id = Column(_UUID, ForeignKey("chat_memory_episodes.episode_id"), nullable=False)
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
    updated_at = Column(_TS, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "block_name", name="uq_working_blocks_user_name"),
    )


# ---------------------------------------------------------------------------
# Table 5: chat_memory_persona_items (Tier 1 persona row-per-item)
# ---------------------------------------------------------------------------


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
    updated_at = Column(_TS, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_persona_items_user_source_pos",
            "user_id",
            "source",
            "position",
        ),
    )
