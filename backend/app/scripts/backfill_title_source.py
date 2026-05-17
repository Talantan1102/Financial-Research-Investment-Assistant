"""一次性迁移: 已有非默认 title 的老 session 视为 llm_generated, 不再触发 LLM 重跑.

调用方:
  - app_main lifespan 启动时跑一次(幂等)
  - 也可以独立 CLI: `uv run python -m app.scripts.backfill_title_source`

幂等: UPDATE ... WHERE title_source='pending' AND title != '新对话', 重复跑无副作用.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import sessionmaker

from app.models.chat import ChatSession


def backfill(engine: Engine) -> int:
    """Returns the number of rows updated."""
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
