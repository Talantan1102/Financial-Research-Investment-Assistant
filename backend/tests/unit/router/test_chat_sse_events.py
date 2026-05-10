"""L0 — SSE event Literal contains skill_execute_*."""

from __future__ import annotations

from app.router.chat import StreamEvent


def test_skill_execute_start_accepted():
    evt = StreamEvent(
        type="skill_execute_start", seq=1, data={"skill": "x", "script": "scripts/y.py"}
    )
    assert evt.type == "skill_execute_start"


def test_skill_execute_end_accepted():
    evt = StreamEvent(type="skill_execute_end", seq=2, data={"stdout_json": {}})
    assert evt.type == "skill_execute_end"


def test_skill_execute_error_accepted():
    evt = StreamEvent(type="skill_execute_error", seq=3, data={"error_kind": "timeout"})
    assert evt.type == "skill_execute_error"
