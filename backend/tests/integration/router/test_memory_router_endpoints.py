"""L1: memory_router endpoints — real PG db_session (via session alias) + fake_auth.

Plan 7A Task 2-6 — 5 endpoint 集成测试 + 跨用户隔离.
依赖 conftest.py 的 session / fake_auth / client fixtures.

PR-A T15: 迁到真 PG(db_session alias), 所有 PgUUID(as_uuid=True) 列传 UUID 实例而非 str.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)
from app.models.chat import ChatSession
from app.models.user import User
from sqlalchemy.orm import Session

# Helpers ----------------------------------------------------------------


def _mk_user_node(session: Session, user_id: str) -> ChatMemoryNode:
    n = ChatMemoryNode(
        node_id=uuid4(),
        user_id=UUID(user_id),
        entity_type="User",
        entity_label="User",
        properties={},
    )
    session.add(n)
    session.flush()
    return n


def _mk_stock_node(session: Session, user_id: str, ts_code: str) -> ChatMemoryNode:
    n = ChatMemoryNode(
        node_id=uuid4(),
        user_id=UUID(user_id),
        entity_type="Stock",
        entity_label=ts_code,
        properties={"name": ts_code},
    )
    session.add(n)
    session.flush()
    return n


def _mk_chat_session(session: Session, user_id: str) -> ChatSession:
    # PgUUID(as_uuid=True) — must pass UUID instances, not strings.
    cs = ChatSession(
        id=uuid4(),
        user_id=UUID(user_id),
        title="test session",
    )
    session.add(cs)
    session.flush()
    return cs


def _mk_episode_with_session(
    session: Session, user_id: str, chat_session: ChatSession
) -> ChatMemoryEpisode:
    ep = ChatMemoryEpisode(
        episode_id=uuid4(),
        user_id=UUID(user_id),
        session_id=chat_session.id,
        episode_index=int(datetime.now(UTC).timestamp() * 1000) % 1_000_000,
        user_message_text="重仓茅台",
        agent_response_text="ok",
        source_kind="chat_turn",
    )
    session.add(ep)
    session.flush()
    return ep


def _mk_episode(
    session: Session, user_id: str, chat_session: ChatSession | None = None
) -> ChatMemoryEpisode:
    if chat_session is None:
        chat_session = _mk_chat_session(session, user_id)
    return _mk_episode_with_session(session, user_id, chat_session)


def _mk_edge(
    session: Session,
    user_id: str,
    src: ChatMemoryNode,
    tgt: ChatMemoryNode,
    rel: str = "HOLDS",
    importance: float = 0.9,
    valid_to: datetime | None = None,
    invalidated_at: datetime | None = None,
    episode: ChatMemoryEpisode | None = None,
    valid_from: datetime | None = None,
) -> ChatMemoryEdge:
    if episode is None:
        episode = _mk_episode(session, user_id)
    if valid_from is None:
        valid_from = datetime.now(UTC) - timedelta(days=1)
    e = ChatMemoryEdge(
        edge_id=uuid4(),
        user_id=UUID(user_id),
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type=rel,
        valid_from=valid_from,
        valid_to=valid_to,
        invalidated_at=invalidated_at,
        source_episode_id=episode.episode_id,
        importance=importance,
        reasoning="test",
        properties={},
    )
    session.add(e)
    session.commit()
    return e


# Tests — Task 2: graph -----------------------------------------------------


def test_get_graph_returns_current_snapshot_only(client, session, fake_auth):
    """current snapshot = valid_to IS NULL AND invalidated_at IS NULL."""
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    stock2 = _mk_stock_node(session, uid, "300750.SZ")

    # current (in snapshot)
    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    # ended (valid_to set) — NOT in snapshot
    _mk_edge(
        session,
        uid,
        user_node,
        stock2,
        rel="HOLDS",
        valid_to=datetime.now(UTC),
    )
    # invalidated — NOT in snapshot
    _mk_edge(
        session,
        uid,
        user_node,
        stock2,
        rel="WATCHES",
        invalidated_at=datetime.now(UTC),
    )

    r = client.get("/api/v0/memory/graph", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["edges"]) == 1
    assert body["edges"][0]["rel_type"] == "HOLDS"
    # nodes = 仅当前 edges 涉及的 (user + 600519.SH)
    node_labels = {n["entity_label"] for n in body["nodes"]}
    assert "600519.SH" in node_labels
    assert "User" in node_labels


def test_get_graph_does_not_leak_other_user(client, session, fake_auth):
    own = fake_auth["user_id"]
    other = User(
        id=uuid4(),
        username=f"o-{uuid4().hex[:6]}",
        email=f"o-{uuid4().hex[:6]}@x",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()

    own_user = _mk_user_node(session, own)
    own_stock = _mk_stock_node(session, own, "600519.SH")
    _mk_edge(session, own, own_user, own_stock)

    other_user = _mk_user_node(session, str(other.id))
    other_stock = _mk_stock_node(session, str(other.id), "300750.SZ")
    _mk_edge(session, str(other.id), other_user, other_stock)

    r = client.get("/api/v0/memory/graph", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    labels = {n["entity_label"] for n in body["nodes"]}
    assert "300750.SZ" not in labels


# Tests — Task 3: timeline --------------------------------------------------


def test_get_timeline_returns_paginated_sorted(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    base = datetime.now(UTC) - timedelta(days=10)
    chat_session = _mk_chat_session(session, uid)
    for i in range(3):
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=UUID(uid),
            session_id=chat_session.id,
            episode_index=i + 1,
            user_message_text=f"msg-{i}",
            agent_response_text="ok",
            source_kind="chat_turn",
        )
        session.add(ep)
        session.flush()
        e = ChatMemoryEdge(
            edge_id=uuid4(),
            user_id=UUID(uid),
            source_node_id=user_node.node_id,
            target_node_id=stock.node_id,
            rel_type="HOLDS",
            valid_from=base + timedelta(days=i),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning=f"e{i}",
            properties={},
        )
        session.add(e)
    session.commit()

    r = client.get("/api/v0/memory/timeline", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["page"] == 1
    # DESC: 最新的在前
    valid_froms = [item["valid_from"] for item in body["items"]]
    assert valid_froms == sorted(valid_froms, reverse=True)


def test_get_timeline_filters_by_rel_type(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    _mk_edge(session, uid, user_node, stock, rel="WATCHES")

    r = client.get(
        "/api/v0/memory/timeline?rel_type=HOLDS",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["rel_type"] == "HOLDS"


def test_get_timeline_filters_by_entity_label(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock_a = _mk_stock_node(session, uid, "600519.SH")
    stock_b = _mk_stock_node(session, uid, "300750.SZ")

    _mk_edge(session, uid, user_node, stock_a, rel="HOLDS")
    _mk_edge(session, uid, user_node, stock_b, rel="HOLDS")

    r = client.get(
        "/api/v0/memory/timeline?entity_label=600519.SH",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["target_label"] == "600519.SH"


def test_get_timeline_pagination(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    chat_session = _mk_chat_session(session, uid)

    base = datetime.now(UTC) - timedelta(days=10)
    for i in range(5):
        ep = ChatMemoryEpisode(
            episode_id=uuid4(),
            user_id=UUID(uid),
            session_id=chat_session.id,
            episode_index=100 + i,
            user_message_text=f"msg-{i}",
            agent_response_text="ok",
            source_kind="chat_turn",
        )
        session.add(ep)
        session.flush()
        e = ChatMemoryEdge(
            edge_id=uuid4(),
            user_id=UUID(uid),
            source_node_id=user_node.node_id,
            target_node_id=stock.node_id,
            rel_type="HOLDS",
            valid_from=base + timedelta(days=i),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=ep.episode_id,
            importance=0.9,
            reasoning=f"e{i}",
            properties={},
        )
        session.add(e)
    session.commit()

    r = client.get(
        "/api/v0/memory/timeline?page=2&page_size=2",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 5


def test_get_timeline_does_not_leak_other_user(client, session, fake_auth):
    own = fake_auth["user_id"]
    other = User(
        id=uuid4(),
        username=f"t-{uuid4().hex[:6]}",
        email=f"t-{uuid4().hex[:6]}@x",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()

    own_u = _mk_user_node(session, own)
    own_s = _mk_stock_node(session, own, "600519.SH")
    _mk_edge(session, own, own_u, own_s)

    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "300750.SZ")
    _mk_edge(session, str(other.id), o_u, o_s)

    r = client.get("/api/v0/memory/timeline", headers=fake_auth["headers"])
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["target_label"] != "300750.SZ" for item in items)


# Tests — Task 4: audit -----------------------------------------------------


def test_get_audit_returns_only_invalidated(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    # current — NOT in audit
    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    # invalidated — in audit
    inv_uuid = uuid4()
    invalidator_uuid = uuid4()
    ep = _mk_episode(session, uid)
    e = ChatMemoryEdge(
        edge_id=inv_uuid,
        user_id=UUID(uid),
        source_node_id=user_node.node_id,
        target_node_id=stock.node_id,
        rel_type="WATCHES",
        valid_from=datetime.now(UTC) - timedelta(days=5),
        valid_to=None,
        invalidated_at=datetime.now(UTC),
        source_episode_id=ep.episode_id,
        importance=0.5,
        reasoning="bad early extraction",
        properties={"invalidated_by_edge_id": str(invalidator_uuid)},
    )
    session.add(e)
    session.commit()

    r = client.get("/api/v0/memory/audit", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["edge_id"] == str(inv_uuid)
    assert item["invalidated_by_edge_id"] == str(invalidator_uuid)


def test_get_audit_does_not_leak_other_user(client, session, fake_auth):
    other = User(
        id=uuid4(),
        username=f"a-{uuid4().hex[:6]}",
        email=f"a-{uuid4().hex[:6]}@x",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()

    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "999999.SH")
    _mk_edge(
        session,
        str(other.id),
        o_u,
        o_s,
        rel="HOLDS",
        invalidated_at=datetime.now(UTC),
    )

    r = client.get("/api/v0/memory/audit", headers=fake_auth["headers"])
    assert r.status_code == 200
    assert r.json()["total"] == 0


# Tests — Task 5: invalidate ------------------------------------------------


def test_invalidate_edge_marks_invalidated_at(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    edge = _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    eid = str(edge.edge_id)

    r = client.post(
        f"/api/v0/memory/edges/{eid}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "invalidated"
    assert body["edge_id"] == eid

    # DB side check
    session.expire(edge)
    refreshed = session.query(ChatMemoryEdge).filter(ChatMemoryEdge.edge_id == edge.edge_id).first()
    assert refreshed is not None
    assert refreshed.invalidated_at is not None
    assert (refreshed.properties or {}).get("invalidated_by") == "user_manual"


def test_invalidate_edge_cross_user_returns_404(client, session, fake_auth):
    other = User(
        id=uuid4(),
        username=f"x-{uuid4().hex[:6]}",
        email=f"x-{uuid4().hex[:6]}@x",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()
    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "999999.SH")
    edge = _mk_edge(session, str(other.id), o_u, o_s, rel="HOLDS")

    r = client.post(
        f"/api/v0/memory/edges/{edge.edge_id}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 404


def test_invalidate_edge_already_invalidated_returns_400(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    edge = _mk_edge(
        session,
        uid,
        user_node,
        stock,
        rel="HOLDS",
        invalidated_at=datetime.now(UTC),
    )

    r = client.post(
        f"/api/v0/memory/edges/{edge.edge_id}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 400


def test_invalidate_edge_not_found_returns_404(client, session, fake_auth):
    r = client.post(
        f"/api/v0/memory/edges/{uuid4()}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 404


def test_invalidate_edge_invalid_uuid_returns_404(client, session, fake_auth):
    r = client.post(
        "/api/v0/memory/edges/not-a-uuid/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 404


# Tests — Task 6: blocks ----------------------------------------------------


def test_get_blocks_returns_user_blocks(client, session, fake_auth):
    uid = fake_auth["user_id"]
    persona = ChatMemoryWorkingBlock(
        block_id=uuid4(),
        user_id=UUID(uid),
        block_name="persona",
        content="long-term value investor",
        token_count=10,
        max_tokens=500,
    )
    scratch = ChatMemoryWorkingBlock(
        block_id=uuid4(),
        user_id=UUID(uid),
        block_name="scratchpad",
        content="thinking about 茅台",
        token_count=5,
        max_tokens=1000,
    )
    session.add_all([persona, scratch])
    session.commit()

    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    blocks = r.json()["blocks"]
    assert len(blocks) == 2
    names = {b["block_name"] for b in blocks}
    assert names == {"persona", "scratchpad"}


def test_get_blocks_empty_when_no_data(client, session, fake_auth):
    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    assert r.json()["blocks"] == []


def test_get_blocks_does_not_leak_other_user(client, session, fake_auth):
    # fake_auth fixture binds the active user (no own blocks created on purpose)
    other = User(
        id=uuid4(),
        username=f"b-{uuid4().hex[:6]}",
        email=f"b-{uuid4().hex[:6]}@x",
        hashed_password="x",
        is_active=True,
    )
    session.add(other)
    session.flush()
    session.add(
        ChatMemoryWorkingBlock(
            block_id=uuid4(),
            user_id=other.id,
            block_name="persona",
            content="leaked",
            token_count=2,
            max_tokens=500,
        )
    )
    session.commit()

    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    contents = [b["content"] for b in r.json()["blocks"]]
    assert "leaked" not in contents
