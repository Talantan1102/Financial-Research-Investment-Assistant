"""L1 — RecallSearcher real PG + mock qwen embed.

Tier 3 chat_messages semantic search via in-memory cosine over qwen-embedded
user messages.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_PG_TESTS") == "1",
    reason="PG container required",
)


def _seed_user(engine: Any, user_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"recall_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )


def _seed_session_and_messages(
    engine: Any,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    contents: list[str],
) -> None:
    """Use raw SQL — test PG chat_messages / chat_sessions schema may lag
    backend ORM additions (message_count / message_type / etc.)."""
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_id), "uid": str(user_id), "t": "recall-test"},
        )
        for content in contents:
            conn.execute(
                text(
                    "INSERT INTO chat_messages (id, session_id, role, content) "
                    "VALUES (:id, :sid, :r, :c)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "sid": str(session_id),
                    "r": "user",
                    "c": content,
                },
            )


def _make_mock_embed(dim: int = 8) -> Any:
    """Returns deterministic embeds based on text content (sum of char codes)."""

    embed = AsyncMock()

    async def _embed(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            # deterministic per-text vector (text hash → distribute across dim slots)
            vec = [0.0] * dim
            for i, ch in enumerate(t):
                vec[i % dim] += float(ord(ch))
            # normalize-ish so cosine is well-defined
            out.append(vec)
        return out

    embed.embed = _embed
    embed.dimension = dim
    return embed


@pytest.mark.integration
async def test_recall_search_returns_top_k_by_cosine(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """Seed 5 chat_messages, query for top-3 most similar."""
    from app.memory.recall_search import RecallSearcher

    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    _seed_session_and_messages(
        pg_memory_fixture["engine"],
        user_id,
        session_id,
        [
            "我重仓了贵州茅台 500 股",
            "今天纳斯达克跌了 3%",
            "上证指数怎么样",
            "我对消费股很看好",
            "白酒行业的护城河",
        ],
    )

    searcher = RecallSearcher(
        session_factory=pg_memory_session_factory,
        embed_service=_make_mock_embed(),
    )
    results = await searcher.search(user_id=user_id, query="我的茅台持仓", k=3)
    assert len(results) <= 3
    assert all(
        "message_id" in r and "content" in r and "session_id" in r and "similarity" in r
        for r in results
    )


@pytest.mark.integration
async def test_recall_search_user_isolation(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """User A messages must NOT be returned to User B."""
    from app.memory.recall_search import RecallSearcher

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    sess_a = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_a)
    _seed_user(pg_memory_fixture["engine"], user_b)
    _seed_session_and_messages(
        pg_memory_fixture["engine"],
        user_a,
        sess_a,
        ["A's secret about 茅台"],
    )

    searcher = RecallSearcher(
        session_factory=pg_memory_session_factory,
        embed_service=_make_mock_embed(),
    )
    results_b = await searcher.search(user_id=user_b, query="secret", k=5)
    assert results_b == []


@pytest.mark.integration
async def test_recall_search_no_messages_returns_empty(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    """No messages for user → empty list (no exception)."""
    from app.memory.recall_search import RecallSearcher

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)

    searcher = RecallSearcher(
        session_factory=pg_memory_session_factory,
        embed_service=_make_mock_embed(),
    )
    results = await searcher.search(user_id=user_id, query="anything", k=5)
    assert results == []
