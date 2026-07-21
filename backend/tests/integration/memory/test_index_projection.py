"""L1 — MEMORY.md 等价索引从 PG 当前快照投影，且不携带正文。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.memory.index_projection import build_memory_index_projection
from sqlalchemy import text


def test_projection_counts_current_db_rows_without_labels(
    pg_memory_fixture: dict[str, Any],
    pg_memory_session_factory: Callable[[], Any],
) -> None:
    uid, sid, episode_id = uuid4(), uuid4(), uuid4()
    source_id, target_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    with pg_memory_fixture["engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:id, :u, :e, 'x', true)"
            ),
            {"id": str(uid), "u": f"idx-{uid.hex[:8]}", "e": f"idx-{uid.hex[:8]}@t.local"},
        )
        conn.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:id, :uid, 't')"),
            {"id": str(sid), "uid": str(uid)},
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_working_blocks "
                "(block_id, user_id, block_name, content, token_count, max_tokens) "
                "VALUES (:id, :uid, 'persona', :content, 9, 500)"
            ),
            {"id": str(uuid4()), "uid": str(uid), "content": "绝密偏好正文"},
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_episodes "
                "(episode_id, user_id, session_id, episode_index, user_message_text, source_kind) "
                "VALUES (:id, :uid, :sid, 0, '绝密对话正文', 'chat_turn')"
            ),
            {"id": str(episode_id), "uid": str(uid), "sid": str(sid)},
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_nodes "
                "(node_id, user_id, entity_type, entity_label, properties) VALUES "
                "(:s, :uid, 'User', '绝密用户标签', '{}'),"
                "(:t, :uid, 'Stock', '贵州茅台绝密详情', '{}')"
            ),
            {"s": str(source_id), "t": str(target_id), "uid": str(uid)},
        )
        conn.execute(
            text(
                "INSERT INTO chat_memory_edges "
                "(edge_id, user_id, source_node_id, target_node_id, rel_type, valid_from, "
                "source_episode_id, importance, properties) VALUES "
                "(:id, :uid, :s, :t, 'HOLDS', :now, :ep, 0.5, '{}')"
            ),
            {
                "id": str(uuid4()),
                "uid": str(uid),
                "s": str(source_id),
                "t": str(target_id),
                "now": now,
                "ep": str(episode_id),
            },
        )

    projection = build_memory_index_projection(pg_memory_session_factory, uid)

    assert projection["working_blocks"] == [{"name": "persona", "token_count": 9}]
    assert projection["archival"]["total"] == 1
    assert projection["archival"]["relations"] == {"HOLDS": 1}
    serialized = str(projection)
    assert "绝密" not in serialized
    assert "贵州茅台" not in serialized
