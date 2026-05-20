"""一次性迁移: 已有非默认 title 的老 session 视为 llm_generated, 不再触发 LLM 重跑.

调用方:
  - app_main lifespan 启动时跑一次(幂等)
  - 也可以独立 CLI: `uv run python -m app.scripts.backfill_title_source`

幂等: UPDATE ... WHERE title_source='pending' AND title != '新对话', 重复跑无副作用.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import inspect, text, update
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import sessionmaker

from app.models.chat import ChatSession


def ensure_title_source_column(engine: Engine) -> bool:
    """如果 chat_sessions 表已存在但 title_source 列缺失, 用 ALTER 补上.

    Spec § 4.2 假设 schema 用 `create_all()` 幂等 — 但 create_all 只 CREATE 新表,
    不会给已有表 ADD COLUMN。本函数补这个 gap, 让 startup-time migration 真覆盖
    "新增列" 场景, 兼容 PG / sqlite。

    Returns True if a column was added.
    """
    inspector = inspect(engine)
    if "chat_sessions" not in inspector.get_table_names():
        return False  # 表都没建, create_all 会处理
    cols = [c["name"] for c in inspector.get_columns("chat_sessions")]
    if "title_source" in cols:
        return False
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE chat_sessions "
                "ADD COLUMN title_source VARCHAR(16) NOT NULL DEFAULT 'pending'"
            )
        )
    return True


def backfill(engine: Engine) -> int:
    """Returns the number of rows updated."""
    ensure_title_source_column(engine)
    Session = sessionmaker(bind=engine)
    with Session() as sess:
        cursor = cast(
            CursorResult,
            sess.execute(
                update(ChatSession)
                .where(
                    ChatSession.title_source == "pending",
                    ChatSession.title != "新对话",
                )
                .values(title_source="llm_generated")
            ),
        )
        sess.commit()
        return cursor.rowcount or 0


if __name__ == "__main__":
    from app.core.database import engine

    n = backfill(engine)
    print(f"backfilled {n} old sessions to title_source='llm_generated'")
