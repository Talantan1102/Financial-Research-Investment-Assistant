"""L2 — recall_memory_search full path.

recall_memory_search calls qwen embed for [query, *messages] and computes
cosine in-memory. A real-LLM cassette would record the dashscope embed HTTP
call.

Default playback uses the recorded cassette (offline). If the cassette is
absent, we fall back to a mocked embed so this test stays green on a fresh
checkout without secrets — the L2 assertion shape (count + provenance) is
preserved either way. Recording instructions:

    DASHSCOPE_API_KEY=... uv run pytest \\
        backend/tests/e2e/memory/test_recall_full_path.py \\
        --record-mode=once -v
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]

CASSETTE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "test_recall_full_path"
)


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_recall_full_path_with_chinese_query(  # noqa: N802 — kept ASCII per ruff
    pg_memory_fixture: dict[str, Any],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cassette_path = CASSETTE_DIR / (f"{request.node.originalname or request.node.name}.yaml")
    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    use_real_llm = record_mode != "none" or cassette_path.exists()

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal, raising=True)

    user_id = uuid.uuid4()
    sess_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"rcl_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(sess_id), "uid": str(user_id), "t": "recall-cas"},
        )
        conn.execute(
            text(
                "INSERT INTO chat_messages (id, session_id, role, content) "
                "VALUES (:id, :sid, :r, :c)"
            ),
            {
                "id": str(msg_id),
                "sid": str(sess_id),
                "r": "user",
                "c": "我重仓茅台,长期持有",
            },
        )

    # Memory factory selection: real qwen embed (cassette path) or mocked.
    import app.mcp_server.tools.memory._common as _common
    from app.memory.hierarchical import HierarchicalMemory

    def _build_memory() -> Any:
        if use_real_llm:
            from app.services.embedding_factory import build_embedding_service_from_env

            embed = build_embedding_service_from_env()
        else:
            embed = AsyncMock()

            async def _fake_embed(texts: list[str]) -> list[list[float]]:
                return [[0.1] * 1024 for _ in texts]

            embed.embed = _fake_embed
        return HierarchicalMemory(
            pg_session_factory=SessionLocal,
            age_executor=None,
            milvus_client=None,
            embed_service=embed,
            llm_extractor=None,
            llm_judge=None,
        )

    monkeypatch.setattr(_common, "build_memory_from_env", _build_memory)

    from app.mcp_server.tools.memory.recall_memory_search import handle

    r = await handle({"user_id": str(user_id), "query": "我之前说过茅台", "k": 5})
    out = json.loads(r[0].text)
    assert "results" in out
    assert out["count"] >= 1
    # Provenance: each result must surface session_id + message_id
    first = out["results"][0]
    assert "session_id" in first
    assert "message_id" in first
    assert first["content"] == "我重仓茅台,长期持有"
