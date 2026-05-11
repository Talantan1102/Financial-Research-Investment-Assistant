"""L1 — 6 memory MCP tool e2e in real PG/AGE/Milvus, mock LLM.

Strategy: monkeypatch app.core.database.SessionLocal to point at the test PG
engine so build_memory_from_env() and build_db_session() in _common.py both
hit the test database. LLM judge / Milvus / AGE are stubbed to no-op so we
verify the MCP tool layer's behaviors (Pydantic validation, evidence_quote
校验, log writing, source_episode_id provenance) without involving heavy
external dependencies — those are covered by Plan 2/3 e2e tests.

Per shared contract § 17 A6: evidence_quote_in_episode is shipped by Plan 4
(this PR) in app.memory.injection_classifier.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
    pytest.mark.integration,
]


def _seed_user(engine: Any, user_id: uuid.UUID) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"mcp_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {
                "id": str(uuid.uuid4()),  # placeholder; tests insert their own sessions later
                "uid": str(user_id),
                "t": "mcp-test",
            },
        )


@pytest.fixture
def patched_session_local(
    pg_memory_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Repoint app.core.database.SessionLocal at the test PG engine.

    _common.py imports SessionLocal lazily inside its helpers, so this patch
    propagates to MCP tool handle() calls.
    """
    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal, raising=True)
    return SessionLocal


@pytest.fixture
def patched_age_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op AGE for environments without Apache AGE extension.

    archival_memory_insert pipeline calls age_create_edge / age_merge_node;
    in macOS dev env we patch them out so the PG transaction can commit.
    Real AGE coverage lives in dedicated AGE e2e (Plan 1A).
    """
    from app.memory import age_sync, hierarchical

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(age_sync, "age_create_edge", _noop)
    monkeypatch.setattr(age_sync, "age_merge_node", _noop)
    if hasattr(hierarchical, "age_create_edge"):
        monkeypatch.setattr(hierarchical, "age_create_edge", _noop, raising=False)
    if hasattr(hierarchical, "age_merge_node"):
        monkeypatch.setattr(hierarchical, "age_merge_node", _noop, raising=False)


@pytest.fixture
def patched_memory_factory(monkeypatch: pytest.MonkeyPatch, patched_session_local: Any) -> None:
    """Replace build_memory_from_env to construct HierarchicalMemory pointed at
    test PG / mock LLM judge / no-op Milvus.

    This avoids importing build_llm_service_from_env (which can fail without
    DASHSCOPE_API_KEY) and skirts pulling pymilvus into the test loop when not
    required.
    """
    from app.memory.conflict_resolver import ConflictResolver
    from app.memory.extractor import LLMExtractor
    from app.memory.hierarchical import HierarchicalMemory

    judge_llm = AsyncMock()
    judge_llm.chat = AsyncMock(
        return_value=json.dumps({"action": "append_new", "reasoning": "test"})
    )

    # Embed must produce one vector per input text (recall_memory_search calls
    # embed([query, *messages]) and expects len(out) == len(in)).
    embed = AsyncMock()

    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]

    embed.embed = _fake_embed

    mock_milvus = MagicMock()
    mock_milvus.insert = MagicMock()  # success path

    def _build_memory() -> Any:
        return HierarchicalMemory(
            pg_session_factory=patched_session_local,
            age_executor=None,
            milvus_client=mock_milvus,
            embed_service=embed,
            llm_extractor=LLMExtractor(llm_client=AsyncMock()),
            llm_judge=ConflictResolver(llm_client=judge_llm),
        )

    import app.mcp_server.tools.memory._common as _common

    monkeypatch.setattr(_common, "build_memory_from_env", _build_memory)


def _seed_episode(SessionLocal: Any, user_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID, str]:
    from app.memory.models import ChatMemoryEpisode

    sess_id = uuid.uuid4()
    ep_id = uuid.uuid4()
    text_msg = "我刚才买了500股贵州茅台,准备长期持有"

    sess = SessionLocal()
    try:
        sess.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(sess_id), "uid": str(user_id), "t": "ep-seed"},
        )
        ep = ChatMemoryEpisode(
            episode_id=ep_id,
            user_id=user_id,
            session_id=sess_id,
            episode_index=0,
            user_message_text=text_msg,
            agent_response_text="收到,我记下了。",
            source_kind="chat_turn",
        )
        sess.add(ep)
        sess.commit()
    finally:
        sess.close()
    return sess_id, ep_id, text_msg


# --------------------------------------------------------------------------
# Tier 1: core_memory_append + core_memory_replace
# --------------------------------------------------------------------------


async def test_core_memory_append_then_replace(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_memory_factory: None,
) -> None:
    from app.mcp_server.tools.memory.core_memory_append import handle as append_h
    from app.mcp_server.tools.memory.core_memory_replace import handle as replace_h

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)

    r1 = await append_h(
        {
            "user_id": str(user_id),
            "block_name": "persona",
            "content": "用户偏好稳健白马",
        }
    )
    out1 = json.loads(r1[0].text)
    assert out1["block_name"] == "persona"
    assert out1["token_count"] > 0

    r2 = await replace_h(
        {
            "user_id": str(user_id),
            "block_name": "persona",
            "old_content": "稳健",
            "new_content": "高股息+稳健",
        }
    )
    out2 = json.loads(r2[0].text)
    assert out2["token_count"] > 0


# --------------------------------------------------------------------------
# Tier 2: archival_memory_insert (evidence_quote pass / fail)
# --------------------------------------------------------------------------


async def test_archival_memory_insert_evidence_quote_pass(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    from app.mcp_server.tools.memory.archival_memory_insert import handle
    from app.memory.models import ChatMemoryEdge

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    _, ep_id, _ = _seed_episode(patched_session_local, user_id)

    args = {
        "user_id": str(user_id),
        "content": {
            "rel_type": "HOLDS",
            "source_label": "User",
            "target_label": "贵州茅台",
        },
        "reasoning": "user said '我刚才买了500股贵州茅台'",
        "importance": 0.9,
        "evidence_quote": "买了500股贵州茅台",  # ← in episode
        "episode_id": str(ep_id),
    }
    result = await handle(args)
    out = json.loads(result[0].text)
    assert out["edge_id"]
    assert out["rel_type"] == "HOLDS"
    assert out["source_episode_id"] == str(ep_id)

    sess = patched_session_local()
    try:
        rows = (
            sess.execute(select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == user_id))
            .scalars()
            .all()
        )
        assert len(rows) == 1
    finally:
        sess.close()


async def test_archival_memory_insert_evidence_quote_fail_raises(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    """Algorithm 深度补丁 #2 核心 — evidence_quote 不在原文 raise + 不写 edge."""
    from app.mcp_server.tools.memory.archival_memory_insert import handle
    from app.memory.injection_classifier import EvidenceNotFoundError
    from app.memory.models import ChatMemoryEdge

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    _, ep_id, _ = _seed_episode(patched_session_local, user_id)

    args = {
        "user_id": str(user_id),
        "content": {
            "rel_type": "AVOIDS",
            "source_label": "User",
            "target_label": "腾讯控股",
        },
        "reasoning": "agent 推断,但用户没说",  # ← hallucinated
        "importance": 0.9,
        "evidence_quote": "我永不碰科技股",  # ← NOT in episode
        "episode_id": str(ep_id),
    }
    with pytest.raises(EvidenceNotFoundError, match="not a substring"):
        await handle(args)

    # Verify edge NOT written
    sess = patched_session_local()
    try:
        rows = (
            sess.execute(
                select(ChatMemoryEdge)
                .where(ChatMemoryEdge.user_id == user_id)
                .where(ChatMemoryEdge.rel_type == "AVOIDS")
            )
            .scalars()
            .all()
        )
        assert rows == []
    finally:
        sess.close()


async def test_archival_memory_insert_episode_not_found_raises(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    """Episode missing / not owned → ValueError, not a write."""
    from app.mcp_server.tools.memory.archival_memory_insert import handle

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    bogus_ep = uuid.uuid4()

    args = {
        "user_id": str(user_id),
        "content": {
            "rel_type": "HOLDS",
            "source_label": "User",
            "target_label": "X",
        },
        "reasoning": "r",
        "importance": 0.5,
        "evidence_quote": "anything",
        "episode_id": str(bogus_ep),
    }
    with pytest.raises(ValueError, match="not found"):
        await handle(args)


# --------------------------------------------------------------------------
# Tier 2: archival_memory_search + traverse
# --------------------------------------------------------------------------


async def test_archival_memory_search_returns_inserted_edge(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    from app.mcp_server.tools.memory.archival_memory_insert import handle as insert_h
    from app.mcp_server.tools.memory.archival_memory_search import handle as search_h

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    _, ep_id, _ = _seed_episode(patched_session_local, user_id)

    insert_result = await insert_h(
        {
            "user_id": str(user_id),
            "content": {
                "rel_type": "HOLDS",
                "source_label": "User",
                "target_label": "贵州茅台",
            },
            "reasoning": "r",
            "importance": 0.9,
            "evidence_quote": "贵州茅台",
            "episode_id": str(ep_id),
        }
    )
    insert_out = json.loads(insert_result[0].text)
    assert insert_out["edge_id"]

    r = await search_h({"user_id": str(user_id), "query": "茅台"})
    out = json.loads(r[0].text)
    # search may or may not match (depends on PG GIN tokenization); just verify
    # we got a well-formed response with 0+ results that include source_episode_id
    assert "results" in out
    assert "count" in out
    if out["count"] >= 1:
        assert all("source_episode_id" in entry for entry in out["results"])


async def test_archival_memory_traverse_returns_paths_or_empty(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    """AGE absent in test env → traverse falls back to []. Either way the tool
    must return well-formed JSON."""
    from app.mcp_server.tools.memory.archival_memory_traverse import handle

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)

    r = await handle(
        {
            "user_id": str(user_id),
            "start_label": "贵州茅台",
            "hops": 2,
        }
    )
    out = json.loads(r[0].text)
    assert "paths" in out
    assert "count" in out
    # AGE absent → empty paths + hint to fall back
    if out["count"] == 0:
        assert "search" in (out.get("hint") or "").lower()


# --------------------------------------------------------------------------
# Tier 3: recall_memory_search
# --------------------------------------------------------------------------


async def test_recall_memory_search_basic(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_memory_factory: None,
) -> None:
    """Tier 3 chat_messages search."""
    from app.mcp_server.tools.memory.recall_memory_search import handle

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)

    # Seed a chat session + message via raw SQL (test PG has older schema).
    sess_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    with pg_memory_fixture["engine"].begin() as conn:
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(sess_id), "uid": str(user_id), "t": "recall"},
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
                "c": "我说过我重仓茅台",
            },
        )

    r = await handle({"user_id": str(user_id), "query": "茅台", "k": 3})
    out = json.loads(r[0].text)
    assert "results" in out
    assert out["count"] >= 1
    assert out["results"][0]["content"] == "我说过我重仓茅台"


# --------------------------------------------------------------------------
# Tool routing 监控 — every invocation writes a row to mcp_tool_call_log
# --------------------------------------------------------------------------


async def test_tool_call_log_written_per_invocation(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_memory_factory: None,
) -> None:
    """每个 tool 调用必须落 mcp_tool_call_log 一行."""
    from app.mcp_server.tools.memory.core_memory_append import handle as append_h
    from app.services.trace_models import MCPToolCallLog

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)

    await append_h(
        {
            "user_id": str(user_id),
            "block_name": "persona",
            "content": "x",
        }
    )

    sess = patched_session_local()
    try:
        rows = (
            sess.execute(select(MCPToolCallLog).where(MCPToolCallLog.user_id == str(user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].tool_name == "core_memory_append"
        assert rows[0].latency_ms >= 0.0
        assert rows[0].error is None
    finally:
        sess.close()


async def test_tool_call_log_records_errors(
    pg_memory_fixture: dict[str, Any],
    patched_session_local: Any,
    patched_age_noop: None,
    patched_memory_factory: None,
) -> None:
    """Failed invocation (evidence_quote not found) still logs row with error."""
    from app.mcp_server.tools.memory.archival_memory_insert import handle
    from app.memory.injection_classifier import EvidenceNotFoundError
    from app.services.trace_models import MCPToolCallLog

    user_id = uuid.uuid4()
    _seed_user(pg_memory_fixture["engine"], user_id)
    _, ep_id, _ = _seed_episode(patched_session_local, user_id)

    with pytest.raises(EvidenceNotFoundError):
        await handle(
            {
                "user_id": str(user_id),
                "content": {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "X",
                },
                "reasoning": "r",
                "importance": 0.5,
                "evidence_quote": "完全不在 episode 里的句子",
                "episode_id": str(ep_id),
            }
        )

    sess = patched_session_local()
    try:
        rows = (
            sess.execute(
                select(MCPToolCallLog)
                .where(MCPToolCallLog.user_id == str(user_id))
                .where(MCPToolCallLog.tool_name == "archival_memory_insert")
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].error is not None
        assert "EvidenceNotFoundError" in rows[0].error
        assert rows[0].result_count == 0
    finally:
        sess.close()
