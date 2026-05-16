"""Migration 单元 — Plan Task 6.

spec § 9: 一次性 backfill 老 persona blob → items 表，全部标 source='agent'.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryPersonaItem, ChatMemoryWorkingBlock
from scripts.migrate_persona_blob_to_items import migrate_user_persona, parse_existing_blob_for_user


@pytest.mark.unit
def test_parse_existing_blob_no_blob_returns_empty() -> None:
    drafts = parse_existing_blob_for_user(
        existing_blob=None,
    )
    assert drafts == []


@pytest.mark.unit
def test_parse_existing_blob_marks_all_agent() -> None:
    """老 blob 没有 H2 → 全部 source='agent'."""
    blob = "- 持有茅台\n- 关注新能源\n"
    drafts = parse_existing_blob_for_user(existing_blob=blob)
    assert len(drafts) == 2
    assert all(d.source == "agent" for d in drafts)


@pytest.mark.unit
def test_migrate_user_persona_skips_if_already_has_items() -> None:
    """已经有 persona_items → skip（避免重复跑）."""
    session = MagicMock()
    user_id = uuid4()
    session.query.return_value.filter_by.return_value.count.return_value = 3

    result = migrate_user_persona(session=session, user_id=user_id)

    assert result == {"status": "skipped", "reason": "items already present"}
    session.add.assert_not_called()


@pytest.mark.unit
def test_migrate_user_persona_inserts_items_from_blob() -> None:
    session = MagicMock()
    user_id = uuid4()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    block = ChatMemoryWorkingBlock(
        user_id=user_id,
        block_name="persona",
        content="- 关注高股息\n- 偏好长期持有\n",
        max_tokens=500,
        token_count=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = block

    result = migrate_user_persona(session=session, user_id=user_id)

    assert result["status"] == "migrated"
    assert result["count"] == 2
    assert session.add.call_count == 2
    added_objects = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(o, ChatMemoryPersonaItem) for o in added_objects)
    session.commit.assert_called_once()


@pytest.mark.unit
def test_migrate_user_persona_no_block_no_op() -> None:
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    session.query.return_value.filter_by.return_value.first.return_value = None

    result = migrate_user_persona(session=session, user_id=uuid4())

    assert result == {"status": "noop", "reason": "no persona block"}


@pytest.mark.unit
def test_migrate_user_persona_block_with_empty_content_is_noop() -> None:
    """block 存在但 content 为空 → empty blob noop, 不 insert/commit."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.count.return_value = 0
    block = ChatMemoryWorkingBlock(
        user_id=uuid4(),
        block_name="persona",
        content="",
        max_tokens=500,
        token_count=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = block

    result = migrate_user_persona(session=session, user_id=uuid4())

    assert result == {"status": "noop", "reason": "empty blob"}
    session.add.assert_not_called()
    session.commit.assert_not_called()
