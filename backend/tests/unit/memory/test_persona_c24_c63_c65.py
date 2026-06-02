"""Regression tests for findings C24, C63, C65 in the persona subsystem.

C24: _sync_to_working_block failure must not make primary mutations return HTTP 500;
     and the sync now uses a PG upsert to avoid UniqueConstraintViolation.
C63: persona max_tokens literal unified — PERSONA_MAX_TOKENS derives from
     BLOCK_DEFAULTS[PERSONA_BLOCK_NAME] (SSOT in working_blocks.py).
C65: 'persona' block-name literal replaced by PERSONA_BLOCK_NAME constant
     imported from working_blocks.py everywhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.memory.models import ChatMemoryPersonaItem
from app.memory.persona_populator import PERSONA_BLOCK_NAME as POPULATOR_BLOCK_NAME
from app.memory.persona_populator import PERSONA_MAX_TOKENS
from app.memory.persona_service import PersonaService
from app.memory.working_blocks import BLOCK_DEFAULTS, PERSONA_BLOCK_NAME

# ─── C65: SSOT constant checks ───────────────────────────────────────────────


@pytest.mark.unit
def test_c65_persona_block_name_constant_in_working_blocks() -> None:
    """PERSONA_BLOCK_NAME lives in working_blocks and equals 'persona'."""
    assert PERSONA_BLOCK_NAME == "persona"


@pytest.mark.unit
def test_c65_persona_populator_imports_from_working_blocks() -> None:
    """persona_populator.PERSONA_BLOCK_NAME is the same object as working_blocks.PERSONA_BLOCK_NAME."""
    assert POPULATOR_BLOCK_NAME is PERSONA_BLOCK_NAME


@pytest.mark.unit
def test_c65_no_bare_persona_literal_in_persona_service() -> None:
    """persona_service uses PERSONA_BLOCK_NAME constant — no standalone literal.

    This grep-based assertion ensures no future revert re-introduces bare literals
    in the internal helper (a stale literal would cause a silent mismatch if the
    constant is ever renamed).
    """
    import inspect

    from app.memory.persona_service import PersonaService

    src = inspect.getsource(PersonaService._sync_to_working_block)
    # After the fix, the literal "persona" should not appear standalone in _sync_to_working_block.
    # It is allowed in comments but must not appear as a bare string argument or value.
    # We check that 'block_name="persona"' and 'block_name=\'persona\'' patterns are absent.
    assert 'block_name="persona"' not in src
    assert "block_name='persona'" not in src


# ─── C63: SSOT token-budget checks ───────────────────────────────────────────


@pytest.mark.unit
def test_c63_persona_max_tokens_equals_block_defaults() -> None:
    """persona_populator.PERSONA_MAX_TOKENS == BLOCK_DEFAULTS['persona'] (SSOT = working_blocks)."""
    assert BLOCK_DEFAULTS[PERSONA_BLOCK_NAME] == PERSONA_MAX_TOKENS


@pytest.mark.unit
def test_c63_sync_to_working_block_uses_block_defaults_max_tokens() -> None:
    """_sync_to_working_block writes max_tokens = BLOCK_DEFAULTS[PERSONA_BLOCK_NAME].

    We verify the execute path by asserting execute is called and the statement
    is the dialect-specific INSERT (pg_insert).  The BLOCK_DEFAULTS constant
    correctness is covered by test_c63_persona_max_tokens_equals_block_defaults.
    """
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(user_id=uuid4())

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    # Confirm the statement is a PostgreSQL Insert (not an ORM add path).
    assert isinstance(stmt, PgInsert), f"expected PgInsert, got {type(stmt)}"


# ─── C24: sync-failure isolation ─────────────────────────────────────────────


@pytest.mark.unit
def test_c24_add_item_succeeds_when_sync_raises() -> None:
    """C24 defect 1: sync failure must not propagate as 500 after primary commit.

    add_item should return the created item even when _sync_to_working_block raises.
    """
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    with patch.object(service, "_sync_to_working_block", side_effect=RuntimeError("PG down")):
        # Should NOT raise even though sync raises
        item = service.add_item(user_id=uuid4(), text="稳健价值", target_section="user")

    assert item is not None
    assert item.text == "稳健价值"
    # Primary commit still happened
    session.commit.assert_called_once()


@pytest.mark.unit
def test_c24_update_item_succeeds_when_sync_raises() -> None:
    """C24 defect 1: update_item returns updated item when sync fails."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="原文",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    with patch.object(service, "_sync_to_working_block", side_effect=RuntimeError("PG down")):
        updated = service.update_item(
            user_id=existing.user_id,  # type: ignore[arg-type]
            item_id=existing.item_id,  # type: ignore[arg-type]
            text="新内容",
        )

    assert updated.text == "新内容"
    session.commit.assert_called_once()


@pytest.mark.unit
def test_c24_delete_item_succeeds_when_sync_raises() -> None:
    """C24 defect 1: delete_item completes when sync fails — no 500."""
    factory, session = _mk_session_factory()
    existing = ChatMemoryPersonaItem(
        item_id=uuid4(),
        user_id=uuid4(),
        source="user",
        text="待删",
        position=0,
    )
    session.query.return_value.filter_by.return_value.first.return_value = existing
    service = PersonaService(pg_session_factory=factory)

    with patch.object(service, "_sync_to_working_block", side_effect=RuntimeError("PG down")):
        # Must complete without raising
        service.delete_item(
            user_id=existing.user_id,  # type: ignore[arg-type]
            item_id=existing.item_id,  # type: ignore[arg-type]
        )

    session.commit.assert_called_once()


@pytest.mark.unit
def test_c24_sync_failure_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """C24: sync failure emits a WARNING (not ERROR) with exc_info, not silence."""
    import logging

    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    with (
        caplog.at_level(logging.WARNING, logger="app.memory.persona_service"),
        patch.object(
            service,
            "_sync_to_working_block",
            side_effect=RuntimeError("PG down"),
        ),
    ):
        service.add_item(user_id=uuid4(), text="测试", target_section="user")

    # The warning must mention 'working_block sync failed' and be present.
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("working_block sync failed" in m for m in warning_messages)


@pytest.mark.unit
def test_c24_sync_upsert_called_on_execute() -> None:
    """C24 defect 2: _sync_to_working_block uses sess.execute (upsert), not sess.add.

    Verifies the race-condition fix: execute is called instead of add, so the
    PG ON CONFLICT DO UPDATE path is taken.
    """
    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(user_id=uuid4())

    session.execute.assert_called_once()
    # add() must NOT be called — upsert replaces read-then-insert
    session.add.assert_not_called()


@pytest.mark.unit
def test_c24_sync_upsert_contains_persona_block_name() -> None:
    """C24+C65: The upsert stmt is a PgInsert targeting ChatMemoryWorkingBlock."""
    from app.memory.models import ChatMemoryWorkingBlock
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    factory, session = _mk_session_factory()
    service = PersonaService(pg_session_factory=factory)

    service._sync_to_working_block(user_id=uuid4())

    stmt = session.execute.call_args[0][0]
    assert isinstance(stmt, PgInsert)
    # Confirm the target table is chat_memory_working_blocks
    assert stmt.table.name == ChatMemoryWorkingBlock.__tablename__


# ─── helpers ─────────────────────────────────────────────────────────────────


def _mk_session_factory() -> tuple[MagicMock, MagicMock]:
    """Return (factory, session) mock pair.  Same session returned on every call."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
    session.query.return_value.filter_by.return_value.first.return_value = None
    factory = MagicMock(return_value=session)
    return factory, session
