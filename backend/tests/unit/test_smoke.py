"""Smoke test: pytest discovers L0 unit layer and LLM_MODE=none."""

import os


def test_unit_layer_llm_mode_none():
    assert os.environ["LLM_MODE"] == "none"


def test_run_control_tables_registered_in_metadata() -> None:
    """The application schema registers durable Run control-plane tables."""
    import app.models  # noqa: F401  ensure all models registered to Base
    from app.core.database import Base

    table_names = set(Base.metadata.tables.keys())
    assert {"runs", "run_attempts", "run_events"}.issubset(table_names)
    assert "chat_tasks" not in table_names
