"""Cutover gate: legacy chat execution must not be importable or registered."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_chat_execution_surfaces_are_removed() -> None:
    """Run APIs are the only execution surface after Phase 4 cutover."""
    forbidden_files = (
        "app/router/chat.py",
        "app/router/chat_finalize.py",
        "app/router/chats.py",
        "app/services/chat_task_repo.py",
        "app/services/chat_session_repo.py",
        "app/services/chat_event_bus.py",
        "app/services/chat_cancel_bus.py",
        "app/services/chat_steer_bus.py",
        "app/tasks/chat_runner.py",
        "app/tasks/chat_stale_scanner.py",
        "app/scripts/cleanup_anonymous_chat_sessions.py",
    )
    present = [path for path in forbidden_files if (ROOT / path).exists()]
    assert not present, f"legacy execution files remain: {present}"

    forbidden_markers = (
        "ChatTask",
        "app.router.chat",
        "chat_runner",
        "chat_stale_scanner",
        "/api/v0/chat",
        "/chat/steer/",
        "/chat/retry/",
    )
    app_main = (ROOT / "app/app_main.py").read_text(encoding="utf-8")
    celery = (ROOT / "app/tasks/celery_app.py").read_text(encoding="utf-8")
    registered = app_main + "\n" + celery
    offenders = [marker for marker in forbidden_markers if marker in registered]
    assert not offenders, f"legacy execution markers remain registered: {offenders}"
