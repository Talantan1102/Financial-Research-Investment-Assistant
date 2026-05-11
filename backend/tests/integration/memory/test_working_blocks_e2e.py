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
    uid = _make_user(pg_memory_fixture)
    block = await hier_memory.core_memory_append(uid, "persona", "我偏好 ROE")
    assert block.block_name == "persona"
    assert "我偏好 ROE" in block.content
    assert block.max_tokens == 500


@pytest.mark.integration
async def test_core_memory_append_idempotent_appends(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "fact A")
    block = await hier_memory.core_memory_append(uid, "persona", "fact B")
    assert "fact A" in block.content
    assert "fact B" in block.content


@pytest.mark.integration
async def test_core_memory_replace_exact_match(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "ROE 重要")
    block = await hier_memory.core_memory_replace(uid, "persona", "重要", "关键")
    assert "ROE 关键" in block.content


@pytest.mark.integration
async def test_core_memory_replace_no_match_raises(
    hier_memory: HierarchicalMemory, pg_memory_fixture: dict[str, Any]
) -> None:
    uid = _make_user(pg_memory_fixture)
    await hier_memory.core_memory_append(uid, "persona", "ROE")
    with pytest.raises(ValueError, match="not found"):
        await hier_memory.core_memory_replace(uid, "persona", "MISSING", "X")


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
    """超 max_tokens 自动 paging — paged_lines 通过 logger 记录(Plan 2 ship 后归档)."""
    uid = _make_user(pg_memory_fixture)
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
