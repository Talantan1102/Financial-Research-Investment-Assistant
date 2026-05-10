"""L0: memory_router Pydantic schema validation.

Plan 7A Task 1 — round-trip + importance 三档 validator.
契约 § 4 CHECK constraint mirror, 契约 § 10 endpoint table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_graph_response_schema_round_trip() -> None:
    from app.router.memory_router import GraphEdgeOut, GraphNodeOut, GraphResponse

    node = GraphNodeOut(
        node_id=str(uuid4()),
        entity_type="Stock",
        entity_label="600519.SH",
        properties={"name": "茅台"},
    )
    edge = GraphEdgeOut(
        edge_id=str(uuid4()),
        source_node_id=node.node_id,
        target_node_id=str(uuid4()),
        rel_type="HOLDS",
        valid_from=datetime.now(UTC).isoformat(),
        valid_to=None,
        importance=0.9,
        reasoning="user said hold",
    )
    body = GraphResponse(nodes=[node], edges=[edge])
    assert body.model_dump()["nodes"][0]["entity_type"] == "Stock"


def test_timeline_response_schema_round_trip() -> None:
    from app.router.memory_router import TimelineEdgeOut, TimelineResponse

    item = TimelineEdgeOut(
        edge_id=str(uuid4()),
        rel_type="HOLDS",
        source_label="User",
        target_label="600519.SH",
        valid_from=datetime.now(UTC).isoformat(),
        valid_to=None,
        importance=0.5,
        invalidated_at=None,
    )
    body = TimelineResponse(items=[item], total=1, page=1, page_size=50)
    assert body.total == 1


def test_audit_response_schema_round_trip() -> None:
    from app.router.memory_router import AuditEdgeOut, AuditResponse

    item = AuditEdgeOut(
        edge_id=str(uuid4()),
        rel_type="HOLDS",
        source_label="User",
        target_label="600519.SH",
        invalidated_at=datetime.now(UTC).isoformat(),
        invalidated_by_edge_id=str(uuid4()),
        original_reasoning="early extraction",
    )
    body = AuditResponse(items=[item], total=1)
    assert body.items[0].rel_type == "HOLDS"


def test_blocks_response_schema_round_trip() -> None:
    from app.router.memory_router import BlocksResponse, WorkingBlockOut

    block = WorkingBlockOut(
        block_name="persona",
        content="long-term value investor",
        token_count=12,
        max_tokens=500,
        updated_at=datetime.now(UTC).isoformat(),
    )
    body = BlocksResponse(blocks=[block])
    assert body.blocks[0].block_name == "persona"


def test_invalidate_response_schema_round_trip() -> None:
    from app.router.memory_router import InvalidateResponse

    body = InvalidateResponse(
        edge_id=str(uuid4()),
        invalidated_at=datetime.now(UTC).isoformat(),
        status="invalidated",
    )
    assert body.status == "invalidated"


def test_invalid_importance_rejected() -> None:
    """importance 必须在 [0.2, 0.5, 0.9] 三档(契约 § 4 CHECK)."""
    from app.router.memory_router import GraphEdgeOut

    with pytest.raises(ValidationError):
        GraphEdgeOut(
            edge_id=str(uuid4()),
            source_node_id=str(uuid4()),
            target_node_id=str(uuid4()),
            rel_type="HOLDS",
            valid_from=datetime.now(UTC).isoformat(),
            valid_to=None,
            importance=0.7,  # 非三档
            reasoning="x",
        )
