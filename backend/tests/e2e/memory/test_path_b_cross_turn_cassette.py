"""L2 cassette — Path B 真 LLM 跨轮抽取.

Cassette: tests/fixtures/cassettes/test_path_b_cross_turn_cassette/<test>.yaml
Record 命令:
    DASHSCOPE_API_KEY=... uv run pytest \
      backend/tests/e2e/memory/test_path_b_cross_turn_cassette.py \
      --record-mode=once -v

Default playback uses the recorded cassette (offline). If the cassette is
absent, pytest-recording would attempt a live request — we skip in that case
to keep CI / fresh-checkout green without secrets.

算法深度补丁 #4 ship 闭环 (Plan 2B Task 8).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "cassettes"
    / "test_path_b_cross_turn_cassette"
)


def _seed_three_turn_session(
    pg_memory_fixture: dict[str, Any],
) -> tuple[UUID, UUID, list[UUID]]:
    """seed users + chat_sessions + 3 episodes (4-min spread, all empty agent)."""
    from app.memory.models import ChatMemoryEpisode

    engine = pg_memory_fixture["engine"]
    user_id = uuid4()
    session_id = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"pbct_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(session_id), "uid": str(user_id), "t": "pbct"},
        )

    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    base = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
    eids: list[UUID] = []
    sess = SessionLocal()
    try:
        for i, (msg, ts_offset) in enumerate(
            [
                ("我刚买了股票", 0),
                ("买什么", 2),
                ("茅台 600519, 500 股", 4),
            ]
        ):
            ep = ChatMemoryEpisode(
                episode_id=uuid4(),
                user_id=user_id,
                session_id=session_id,
                episode_index=i,
                user_message_text=msg,
                agent_response_text="",
                source_kind="chat_turn",
                created_at=base + timedelta(minutes=ts_offset),
            )
            sess.add(ep)
            sess.flush()
            eids.append(ep.episode_id)  # type: ignore[arg-type]
        sess.commit()
    finally:
        sess.close()
    return user_id, session_id, eids


@pytest.mark.vcr
@pytest.mark.asyncio
async def test_path_b_real_llm_cross_turn_extracts_holds_fact(
    pg_memory_fixture: dict[str, Any],
    request: pytest.FixtureRequest,
) -> None:
    """3 turn dialogue 走 Path B 真 LLM 抽取 → 至少 1 条 HOLDS edge."""
    cassette_path = CASSETTE_DIR / (f"{request.node.originalname or request.node.name}.yaml")
    record_mode = os.environ.get("VCR_RECORD_MODE", "none")
    if record_mode == "none" and not cassette_path.exists():
        pytest.skip(
            "cassette not recorded yet; record with "
            "VCR_RECORD_MODE=once + DASHSCOPE_API_KEY before running offline"
        )

    from unittest.mock import MagicMock

    from app.memory.extractor import LLMExtractor
    from app.memory.path_b_runner import PathBRunner
    from app.services.openai_client import build_llm_service_from_env

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    _user_id, session_id, _eids = _seed_three_turn_session(pg_memory_fixture)

    llm = build_llm_service_from_env()
    extractor = LLMExtractor(llm_client=llm)

    insert_calls: list[dict[str, Any]] = []

    async def capture_insert(**kwargs: Any) -> Any:
        insert_calls.append(kwargs)
        return MagicMock(edge_id=uuid4())

    runner = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=extractor,
        archival_insert_fn=capture_insert,
    )
    result = await runner.run_for_session(session_id=session_id, trigger_reason="session_closed")

    assert result.episodes_scanned == 3
    assert result.chunks == 1
    assert result.facts_extracted >= 1, f"expected >= 1 fact, got {result}"
    holds_facts = [
        c
        for c in insert_calls
        if (c.get("content") or {}).get("rel_type") == "HOLDS"
        and (c.get("content") or {}).get("target_label") == "600519.SH"
    ]
    # Per Plan 2B Task 8 risk #5: relax to "at least 1 HOLDS for moutai"; full
    # qty=500 recall is Plan 8 50-case golden territory.
    assert len(holds_facts) >= 1, f"未抽出 HOLDS 600519.SH: {insert_calls}"
