"""L1: Working blocks 跟 PG 协作 — append/replace/get 通过 SQLAlchemy.

Plan 1B Task 4 仅 sanity check ChatMemoryWorkingBlock model 可读写;
完整 HierarchicalMemory.{get,append,replace}_working_blocks 在 Task 6 ship.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryWorkingBlock
from sqlalchemy.orm import sessionmaker


@pytest.mark.integration
def test_chat_memory_working_block_insertable(
    pg_memory_fixture: dict[str, Any],
) -> None:
    """sanity: Plan 1A ship 的 model 可以 INSERT."""
    engine = pg_memory_fixture["engine"]
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    try:
        # 用真实 user 引导 FK; Plan 1A pg_memory_fixture 的 users 表已存在(legacy schema)
        # 走 raw SQL 直接 INSERT users 行避免依赖 v0.x User model 的全字段约束差异
        from sqlalchemy import text

        user_uuid = str(uuid4())
        session.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": user_uuid,
                "u": f"wb_{user_uuid[:8]}",
                "e": f"{user_uuid[:8]}@test.local",
                "p": "x",
            },
        )
        session.flush()

        block = ChatMemoryWorkingBlock(
            user_id=user_uuid,
            block_name="persona",
            content="test",
            token_count=1,
            max_tokens=500,
        )
        session.add(block)
        session.flush()
        assert block.block_id is not None
    finally:
        session.rollback()
        session.close()
