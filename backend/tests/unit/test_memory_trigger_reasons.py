"""L0 — Path B 触发档校验(per-turn 接线加了 post_turn 档)。"""

from __future__ import annotations

from app.tasks.memory import _VALID_TRIGGER_REASONS


def test_post_turn_is_valid_trigger_reason() -> None:
    assert "post_turn" in _VALID_TRIGGER_REASONS


def test_existing_session_boundary_reasons_kept() -> None:
    assert {"session_closed", "idle_30min", "new_session_started"} <= _VALID_TRIGGER_REASONS
