"""REST API for C.5 cross-session memory page.

Endpoints (契约 § 10):
  GET  /api/v0/memory/graph              graph viz nodes + edges 当前快照
  GET  /api/v0/memory/timeline           按 valid_from DESC 排序的 edge 列表(分页 + 筛)
  GET  /api/v0/memory/audit              已 invalidate 的 edges(纠错史)
  POST /api/v0/memory/edges/{edge_id}/invalidate 用户一键否决
  GET  /api/v0/memory/blocks             working blocks 当前内容(persona / scratchpad)

Auth: 所有 endpoint 强制从 get_current_user_required 取 user_id,
path/query 不接受 user_id 参数 (防越权, 契约 § 10 末尾约定)。

Note(Plan 7A): 此文件替换原 legacy /memories 路由(未注册到 app_main, 无活跃 caller)。
新 C.5 路由按 shared contracts § 1 + § 10 实现, prefix=/api/v0/memory。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)
from app.models.user import User
from app.router.auth_router import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v0/memory", tags=["c5-memory"])


# ---------------------------------------------------------------------------
# Pydantic schemas — Graph view
# ---------------------------------------------------------------------------


class GraphNodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    entity_type: str  # 7 类: User / Stock / Industry / Sector / Metric / Strategy / Concept
    entity_label: str
    properties: dict


class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    source_node_id: str
    target_node_id: str
    rel_type: str
    valid_from: str
    valid_to: str | None
    importance: float = Field(..., description="三档 0.9 / 0.5 / 0.2 (契约 § 4)")
    reasoning: str | None

    @field_validator("importance")
    @classmethod
    def _check_importance(cls, v: float) -> float:
        if v not in (0.2, 0.5, 0.9):
            raise ValueError(f"importance must be one of [0.2, 0.5, 0.9], got {v}")
        return v


class GraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# ---------------------------------------------------------------------------
# Pydantic schemas — Timeline view
# ---------------------------------------------------------------------------


class TimelineEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    rel_type: str
    source_label: str  # entity_label of source node
    target_label: str  # entity_label of target node
    valid_from: str
    valid_to: str | None
    importance: float
    invalidated_at: str | None


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TimelineEdgeOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Pydantic schemas — Audit view
# ---------------------------------------------------------------------------


class AuditEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    rel_type: str
    source_label: str
    target_label: str
    invalidated_at: str
    invalidated_by_edge_id: str | None  # nullable: 用户手动 invalidate 时无替代 fact
    original_reasoning: str | None


class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AuditEdgeOut]
    total: int


# ---------------------------------------------------------------------------
# Pydantic schemas — Working Blocks
# ---------------------------------------------------------------------------


class WorkingBlockOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_name: str  # 'persona' / 'scratchpad'
    content: str
    token_count: int
    max_tokens: int
    updated_at: str


class BlocksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[WorkingBlockOut]


# ---------------------------------------------------------------------------
# Pydantic schemas — Invalidate
# ---------------------------------------------------------------------------


class InvalidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str
    invalidated_at: str
    status: Literal["invalidated"]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> GraphResponse:
    """Return current snapshot: edges with valid_to IS NULL AND invalidated_at IS NULL.

    Spec § 9 行 965, § 5 路径 3.
    """
    edges = (
        db.query(ChatMemoryEdge)
        .filter(
            ChatMemoryEdge.user_id == user.id,
            ChatMemoryEdge.valid_to.is_(None),
            ChatMemoryEdge.invalidated_at.is_(None),
        )
        .all()
    )

    # 收集涉及的 node ids
    node_ids: set = set()
    for e in edges:
        node_ids.add(e.source_node_id)
        node_ids.add(e.target_node_id)

    nodes_q: list[ChatMemoryNode] = []
    if node_ids:
        nodes_q = (
            db.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user.id,
                ChatMemoryNode.node_id.in_(node_ids),
            )
            .all()
        )

    return GraphResponse(
        nodes=[
            GraphNodeOut(
                node_id=str(n.node_id),
                entity_type=n.entity_type,
                entity_label=n.entity_label,
                properties=n.properties or {},
            )
            for n in nodes_q
        ],
        edges=[
            GraphEdgeOut(
                edge_id=str(e.edge_id),
                source_node_id=str(e.source_node_id),
                target_node_id=str(e.target_node_id),
                rel_type=e.rel_type,
                valid_from=e.valid_from.isoformat(),
                valid_to=e.valid_to.isoformat() if e.valid_to else None,
                importance=e.importance,
                reasoning=e.reasoning,
            )
            for e in edges
        ],
    )


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    rel_type: str | None = None,
    entity_label: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> TimelineResponse:
    """spec § 9 行 967 — 按 valid_from DESC 排序, 支持 rel_type / entity_label 筛."""
    q = db.query(ChatMemoryEdge).filter(ChatMemoryEdge.user_id == user.id)

    if rel_type:
        q = q.filter(ChatMemoryEdge.rel_type == rel_type)

    if entity_label:
        # 跨用户隔离: 两步 query (先查 user 的 nodes, 再 filter edges)
        matching_node_ids = [
            n.node_id
            for n in db.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user.id,
                ChatMemoryNode.entity_label == entity_label,
            )
            .all()
        ]
        if not matching_node_ids:
            return TimelineResponse(items=[], total=0, page=page, page_size=page_size)
        q = q.filter(
            or_(
                ChatMemoryEdge.source_node_id.in_(matching_node_ids),
                ChatMemoryEdge.target_node_id.in_(matching_node_ids),
            )
        )

    total = q.count()
    edges = (
        q.order_by(ChatMemoryEdge.valid_from.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 反查 src / tgt label
    all_node_ids: set = set()
    for e in edges:
        all_node_ids.add(e.source_node_id)
        all_node_ids.add(e.target_node_id)
    label_map: dict = {}
    if all_node_ids:
        for n in db.query(ChatMemoryNode).filter(ChatMemoryNode.node_id.in_(all_node_ids)).all():
            label_map[n.node_id] = n.entity_label

    items = [
        TimelineEdgeOut(
            edge_id=str(e.edge_id),
            rel_type=e.rel_type,
            source_label=label_map.get(e.source_node_id, "?"),
            target_label=label_map.get(e.target_node_id, "?"),
            valid_from=e.valid_from.isoformat(),
            valid_to=e.valid_to.isoformat() if e.valid_to else None,
            importance=e.importance,
            invalidated_at=e.invalidated_at.isoformat() if e.invalidated_at else None,
        )
        for e in edges
    ]
    return TimelineResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/audit", response_model=AuditResponse)
def get_audit(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> AuditResponse:
    """spec § 9 行 974 — invalidated_at IS NOT NULL 的纠错史.

    invalidated_by_edge_id 从 properties JSONB 读 (Plan 2 conflict_resolver 写入)。
    """
    edges = (
        db.query(ChatMemoryEdge)
        .filter(
            ChatMemoryEdge.user_id == user.id,
            ChatMemoryEdge.invalidated_at.is_not(None),
        )
        .order_by(ChatMemoryEdge.invalidated_at.desc())
        .all()
    )

    all_node_ids: set = set()
    for e in edges:
        all_node_ids.add(e.source_node_id)
        all_node_ids.add(e.target_node_id)
    label_map: dict = {}
    if all_node_ids:
        for n in db.query(ChatMemoryNode).filter(ChatMemoryNode.node_id.in_(all_node_ids)).all():
            label_map[n.node_id] = n.entity_label

    items = [
        AuditEdgeOut(
            edge_id=str(e.edge_id),
            rel_type=e.rel_type,
            source_label=label_map.get(e.source_node_id, "?"),
            target_label=label_map.get(e.target_node_id, "?"),
            invalidated_at=e.invalidated_at.isoformat(),
            invalidated_by_edge_id=(e.properties or {}).get("invalidated_by_edge_id"),
            original_reasoning=e.reasoning,
        )
        for e in edges
    ]
    return AuditResponse(items=items, total=len(items))


@router.post("/edges/{edge_id}/invalidate", response_model=InvalidateResponse)
def invalidate_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> InvalidateResponse:
    """spec § 14 P1 #8 — 用户一键否决.

    跨用户访问 → 404 (防越权, user_id 不在 path/query).
    已 invalidated 重复 POST → 400 (防覆盖 audit log 时间戳).
    """
    try:
        eid_str = str(UUID(edge_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="edge not found") from None

    # Pass as str to dodge sqlite-variant bind issue (no UUID→str converter on sqlite).
    # PG accepts str-form UUID equivalently.
    edge = db.query(ChatMemoryEdge).filter(ChatMemoryEdge.edge_id == eid_str).first()
    if edge is None or str(edge.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="edge not found")
    if edge.invalidated_at is not None:
        raise HTTPException(status_code=400, detail="edge already invalidated")

    now = datetime.now(UTC)
    edge.invalidated_at = now
    # SQLAlchemy JSONB mutate-detect: 重新赋整个 dict (model 未标 MutableDict)
    new_props = dict(edge.properties or {})
    new_props["invalidated_by"] = "user_manual"
    edge.properties = new_props
    db.commit()

    return InvalidateResponse(
        edge_id=str(edge.edge_id),
        invalidated_at=now.isoformat(),
        status="invalidated",
    )


@router.get("/blocks", response_model=BlocksResponse)
def get_blocks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> BlocksResponse:
    """spec § 7 working memory budget — 返 persona / scratchpad 当前内容(只读)."""
    blocks = (
        db.query(ChatMemoryWorkingBlock)
        .filter(ChatMemoryWorkingBlock.user_id == user.id)
        .order_by(ChatMemoryWorkingBlock.block_name.asc())
        .all()
    )
    return BlocksResponse(
        blocks=[
            WorkingBlockOut(
                block_name=b.block_name,
                content=b.content or "",
                token_count=b.token_count,
                max_tokens=b.max_tokens,
                updated_at=b.updated_at.isoformat() if b.updated_at else "",
            )
            for b in blocks
        ]
    )
