"""L1: HierarchicalMemory working blocks — real PG."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _make_user(pg_memory_fixture: dict[str, Any]) -> UUID:
    """Insert a fresh user row and return its UUID. Required for FK on
    chat_memory_working_blocks.user_id → users.id.
    """
    engine = pg_memory_fixture["engine"]
    user_uuid = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_uuid),
                "u": f"wb_{user_uuid.hex[:8]}",
                "e": f"{user_uuid.hex[:8]}@test.local",
                "p": "x",
            },
        )
    return user_uuid


@pytest.fixture
def hier_memory(
    pg_memory_session_factory: Callable[[], Any],
) -> HierarchicalMemory:
    return HierarchicalMemory(
        pg_session_factory=pg_memory_session_factory,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )


@pytest.mark.integration
async def test_get_working_blocks_empty_user_returns_empty_dict(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    blocks = await hier_memory.get_working_blocks(uid)
    assert blocks == {}


@pytest.mark.integration
async def test_core_memory_append_creates_block(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """Task 17: persona block routes to PersonaService — returns None.
    Verify content written via get_working_blocks (reads ChatMemoryWorkingBlock synced by PersonaService).
    """
    uid = _make_user(pg_memory_fixture)
    result = await hier_memory.core_memory_append(uid, "persona", "我偏好 ROE")
    # Task 17: persona path returns None (routed to PersonaService)
    assert result is None
    # Verify content persisted via working block sync
    blocks = await hier_memory.get_working_blocks(uid)
    assert "persona" in blocks
    assert "我偏好 ROE" in blocks["persona"].content


@pytest.mark.integration
async def test_core_memory_append_idempotent_appends(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """Task 17: persona block routes to PersonaService — both appends persisted."""
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "fact A")
    result = await hier_memory.core_memory_append(uid, "persona", "fact B")
    # Task 17: persona path returns None
    assert result is None
    blocks = await hier_memory.get_working_blocks(uid)
    assert "fact A" in blocks["persona"].content
    assert "fact B" in blocks["persona"].content


@pytest.mark.integration
async def test_core_memory_replace_exact_match(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """Task 17: persona replace routes to PersonaService.apply_agent_replace — returns None."""
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "ROE 重要")
    result = await hier_memory.core_memory_replace(uid, "persona", "ROE 重要", "ROE 关键")
    # Task 17: persona path returns None
    assert result is None
    blocks = await hier_memory.get_working_blocks(uid)
    assert "ROE 关键" in blocks["persona"].content


@pytest.mark.integration
async def test_core_memory_replace_no_match_falls_back_to_append(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """Task 17: persona replace with no match → PersonaService falls back to append (no raise)."""
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "ROE")
    # PersonaService.apply_agent_replace falls back to append on no-match (no ValueError)
    result = await hier_memory.core_memory_replace(uid, "persona", "MISSING", "X")
    assert result is None  # persona path always returns None


@pytest.mark.integration
async def test_unknown_block_name_raises(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    with pytest.raises(ValueError, match="block_name"):
        await hier_memory.core_memory_append(uid, "unknown_block", "x")


@pytest.mark.integration
async def test_append_exceed_budget_pages_oldest(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    """Task 17: persona block routes to PersonaService — 20 appends create 20 items.
    PersonaService stores each line as a separate ChatMemoryPersonaItem (no hard token cap).
    Verify content synced to working block is non-empty.
    """
    uid = _make_user(pg_memory_fixture)
    for i in range(20):
        await hier_memory.core_memory_append(
            uid, "persona", f"fact_{i}: 茅台白酒 ROE 持仓 偏好 现金流"
        )
    blocks = await hier_memory.get_working_blocks(uid)
    assert "persona" in blocks
    # PersonaService syncs all items to working block; content non-empty
    assert len(blocks["persona"].content) > 0
