"""L2 — archival_memory_traverse full path.

The MCP traverse tool wraps HierarchicalMemory.archival_memory_traverse, which
runs AGE Cypher (no HTTP) — so this test does NOT need a VCR cassette. It
exercises the full path end-to-end: PG seed → traverse handle → JSON output.

When AGE is unavailable in the test environment (the default in macOS dev),
graph_traverse falls back to an empty list (spec § 5 fail-safe semantics);
the tool returns `{paths: [], count: 0, hint: "...search"}`. Either outcome
is acceptable for L2 — we assert the contract shape, not the topology.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SKIP_PG_TESTS") == "1",
        reason="PG container required",
    ),
]


@pytest.mark.asyncio
async def test_traverse_industry_neighbors_full_path(
    pg_memory_fixture: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed 茅台/白酒/五粮液 chain → traverse 茅台 hops=2 → returns paths or empty."""
    from sqlalchemy.orm import sessionmaker

    engine = pg_memory_fixture["engine"]
    SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    # Patch app.core.database.SessionLocal so the MCP tool's _common.py points
    # at the test PG.
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal, raising=True)

    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, :p, true)"
            ),
            {
                "id": str(user_id),
                "u": f"trav_{user_id.hex[:8]}",
                "e": f"{user_id.hex[:8]}@test.local",
                "p": "x",
            },
        )

    # Seed 3 edges directly via raw SQL (avoids needing real archival_insert
    # pipeline + AGE in test env). Plan 8 will exercise full insert→traverse
    # in the cassette differential test.
    sess_id = uuid.uuid4()
    ep_id = uuid.uuid4()
    moutai_node = uuid.uuid4()
    baijiu_node = uuid.uuid4()
    wuliangye_node = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, :t)"),
            {"id": str(sess_id), "uid": str(user_id), "t": "trav-seed"},
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_episodes "
                "(episode_id, user_id, session_id, episode_index, "
                " user_message_text, source_kind) "
                "VALUES (:eid, :uid, :sid, 0, 'seed', 'seed')"
            ),
            {"eid": str(ep_id), "uid": str(user_id), "sid": str(sess_id)},
        )
        for nid, etype, label in [
            (moutai_node, "Stock", "贵州茅台"),
            (baijiu_node, "Industry", "白酒"),
            (wuliangye_node, "Stock", "五粮液"),
        ]:
            conn.execute(
                text(
                    "INSERT INTO chat_memory_nodes "
                    "(node_id, user_id, entity_type, entity_label, properties) "
                    "VALUES (:nid, :uid, :et, :el, '{}'::jsonb)"
                ),
                {"nid": str(nid), "uid": str(user_id), "et": etype, "el": label},
            )
        conn.execute(
            text(
                "INSERT INTO chat_memory_edges "
                "(edge_id, user_id, source_node_id, target_node_id, rel_type, "
                " valid_from, source_episode_id, importance, search_tokens, properties) "
                "VALUES "
                " (:e1, :uid, :s1, :t1, 'BELONGS_TO', now(), :eid, 0.5, '茅台 白酒', '{}'::jsonb), "
                " (:e2, :uid, :s2, :t2, 'BELONGS_TO', now(), :eid, 0.5, '五粮液 白酒', '{}'::jsonb)"
            ),
            {
                "e1": str(uuid.uuid4()),
                "e2": str(uuid.uuid4()),
                "uid": str(user_id),
                "s1": str(moutai_node),
                "t1": str(baijiu_node),
                "s2": str(wuliangye_node),
                "t2": str(baijiu_node),
                "eid": str(ep_id),
            },
        )

    # Replace memory factory with a HierarchicalMemory pointing at test PG —
    # AGE absent so traverse will return empty + hint. We still verify the
    # tool layer's contract shape.
    import app.mcp_server.tools.memory._common as _common
    from app.memory.hierarchical import HierarchicalMemory

    def _build_memory() -> Any:
        return HierarchicalMemory(
            pg_session_factory=SessionLocal,
            age_executor=None,
            milvus_client=None,
            embed_service=None,
            llm_extractor=None,
            llm_judge=None,
        )

    monkeypatch.setattr(_common, "build_memory_from_env", _build_memory)

    from app.mcp_server.tools.memory.archival_memory_traverse import handle

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
    # Either AGE-driven traversal returned paths (count >= 0) or fallback
    # empty + hint to fall back to search. Both are valid spec § 5 outcomes.
    if out["count"] == 0:
        assert "search" in (out.get("hint") or "").lower()
