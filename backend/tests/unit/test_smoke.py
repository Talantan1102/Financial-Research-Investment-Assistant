"""Smoke test: pytest discovers L0 unit layer and LLM_MODE=none."""

import os


def test_unit_layer_llm_mode_none():
    assert os.environ["LLM_MODE"] == "none"


def test_chat_tasks_table_registered_in_metadata() -> None:
    """守护:ChatTask 必须在 Base.metadata 中注册,否则 lifespan create_all 不会建表。

    模拟 app_main.py lifespan 的 barrel import 行为(`import app.models as _models`),
    再断言 chat_tasks 出现在 metadata。

    若该 test 失败,通常是 backend/app/models/__init__.py 漏 re-export ChatTask,
    或 chat.py 的 ChatTask 类定义被破坏。
    """
    import app.models  # noqa: F401  ensure all models registered to Base
    from app.core.database import Base

    table_names = set(Base.metadata.tables.keys())
    assert "chat_tasks" in table_names, (
        f"chat_tasks 未注册到 Base.metadata。当前注册的表: {sorted(table_names)}"
    )
