"""ChatTask ORM model 基础字段 + 默认值测试。

只覆盖 model 层 — Repo 行为见 test_chat_task_repo.py。
"""

from __future__ import annotations

from app.models.chat import ChatMessage, ChatTask


def test_chat_task_has_required_columns() -> None:
    cols = {c.name for c in ChatTask.__table__.columns}
    expected = {
        "id",
        "session_id",
        "user_id",
        "status",
        "langgraph_thread_id",
        "langgraph_checkpoint_id",
        "created_at",
        "started_at",
        "finished_at",
        "error_message",
        "last_event_seq",
        "initial_prompt_message_id",
        "parent_task_id",
    }
    missing = expected - cols
    assert not missing, f"ChatTask 缺字段: {missing}"


def test_chat_message_has_task_columns() -> None:
    cols = {c.name for c in ChatMessage.__table__.columns}
    assert "task_id" in cols, "ChatMessage 应该有 task_id 列"
    assert "status" in cols, "ChatMessage 应该有 status 列"


def test_chat_task_status_check_constraint() -> None:
    """6 个合法状态值都应在 CHECK 约束里。"""
    constraints = [
        c for c in ChatTask.__table__.constraints if c.__class__.__name__ == "CheckConstraint"
    ]
    sqls = [str(c.sqltext) for c in constraints]
    joined = " ".join(sqls)
    for status in ("queued", "running", "done", "cancelled", "partial", "error"):
        assert f"'{status}'" in joined, f"CHECK 约束缺 {status}"
