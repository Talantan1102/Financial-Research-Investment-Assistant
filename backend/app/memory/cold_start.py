"""Cold Start Populator — 静态版.

spec ref: § 8 Cold Start Populator
contract ref: § 5 normalize_entity / Plan 1A 幂等键 UNIQUE constraint

3 路 seed:
- 持仓 (positions) → User → HOLDS Stock(valid_from=position.updated_at 或 default)
- preferences (users.preferences JSONB) → PREFERS edge (Plan 1B 留 hook,
  当前 User model 无 preferences 列, 留 v1.x 接 PR #39 / v0.8 ship 的 user prefs)
- watchlist (如表存在) → WATCHES edge

幂等保证:
- 检查 cold_start_seed episode 存在 → 跳过(spec § 8)
- 走幂等键 UNIQUE constraint(Plan 1A 已建): 重跑 INSERT 命中 UNIQUE 走 ON CONFLICT DO NOTHING

CLI 入口::

    python -m app.memory.cold_start --user-id <uuid>

启动 lifespan auto-trigger:
    在 chat router 第一次拿 session 时调用(本 plan Task 10 接).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

logger = logging.getLogger(__name__)


def has_been_seeded_for_user(pg_session_factory: Any, user_id: Any) -> bool:
    """检查是否已 cold start(找 source_kind='cold_start_seed' episode)."""
    from app.memory.models import ChatMemoryEpisode

    sess = pg_session_factory()
    try:
        existing = (
            sess.query(ChatMemoryEpisode)
            .filter(
                ChatMemoryEpisode.user_id == user_id,
                ChatMemoryEpisode.source_kind == "cold_start_seed",
            )
            .first()
        )
        return existing is not None
    finally:
        sess.close()


def build_holds_edge_payload(
    ts_code: str,
    qty: int,
    avg_cost: float,
    purchase_date: datetime | None,
    fallback_date: datetime,
) -> dict[str, Any]:
    """构造 HOLDS edge payload.

    valid_from 优先 purchase_date(spec § 8 提示 position.purchase_date 或 last_updated_at);
    无则 fallback_date.
    """
    valid_from = purchase_date or fallback_date
    return {
        "rel_type": "HOLDS",
        "target_label": ts_code,
        "qty": qty,
        "avg_cost": avg_cost,
        "valid_from": valid_from,
        "importance": 0.9,
        "reasoning": "cold start from positions table",
    }


def _get_or_create_seed_session(sess: Any, user_id: Any) -> UUID:
    """Cold start 需要一个真实 chat_sessions 行做 episode FK 目标.

    方案: 每用户一个 'cold_start_system_session' (title 标记), 多次 cold start 复用.
    """
    row = sess.execute(
        text(
            "SELECT id FROM chat_sessions WHERE user_id = :uid "
            "AND title = 'cold_start_system_session' LIMIT 1"
        ),
        {"uid": str(user_id)},
    ).fetchone()
    if row is not None:
        return UUID(str(row[0]))

    new_sid = uuid4()
    sess.execute(
        text(
            "INSERT INTO chat_sessions (id, user_id, title, session_type) "
            "VALUES (:id, :uid, 'cold_start_system_session', 'system')"
        ),
        {"id": str(new_sid), "uid": str(user_id)},
    )
    return new_sid


async def seed_user_graph(
    user_id: Any,
    pg_session_factory: Any,
) -> None:
    """3 路 seed user 的 memory graph(幂等).

    - 已 seeded 则 skip
    - 否则建 cold_start_seed episode + User node + per-position Stock node + HOLDS edge
    - preferences / watchlist 路在 Plan 1B 留 stub(当前 user model 无 preferences 列)
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
    )
    from app.memory.registry import jieba_tokenize_for_search
    from app.models.position import Position

    if has_been_seeded_for_user(pg_session_factory, user_id):
        logger.info("cold_start: user %s already seeded, skip", user_id)
        return

    sess = pg_session_factory()
    try:
        seed_sid = _get_or_create_seed_session(sess, user_id)
        sess.flush()

        # 1. 创建 cold_start_seed episode(extracted_at 已设置, 跳过 reconciliation)
        seed_episode = ChatMemoryEpisode(
            user_id=user_id,
            session_id=seed_sid,
            episode_index=0,
            user_message_text="COLD_START_SEED",
            agent_response_text="COLD_START_SEED",
            source_kind="cold_start_seed",
            extracted_at=datetime.now(UTC),
            extracted_by="cold_start",
        )
        sess.add(seed_episode)
        sess.flush()  # need episode_id for FK

        # 2. 创建或获取 User node
        user_node = (
            sess.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user_id,
                ChatMemoryNode.entity_type == "User",
                ChatMemoryNode.entity_label == "User",
            )
            .first()
        )
        if user_node is None:
            user_node = ChatMemoryNode(
                user_id=user_id,
                entity_type="User",
                entity_label="User",
                properties={},
                search_tokens=jieba_tokenize_for_search("User"),
            )
            sess.add(user_node)
            sess.flush()

        # 3. 持仓 → HOLDS edges
        positions = sess.query(Position).filter(Position.user_id == user_id).all()
        for pos in positions:
            ts_code = pos.ts_code
            # Stock node 幂等 get_or_create
            stock_node = (
                sess.query(ChatMemoryNode)
                .filter(
                    ChatMemoryNode.user_id == user_id,
                    ChatMemoryNode.entity_type == "Stock",
                    ChatMemoryNode.entity_label == ts_code,
                )
                .first()
            )
            if stock_node is None:
                stock_node = ChatMemoryNode(
                    user_id=user_id,
                    entity_type="Stock",
                    entity_label=ts_code,
                    properties={"name": pos.name},
                    search_tokens=jieba_tokenize_for_search(f"{ts_code} {pos.name}"),
                )
                sess.add(stock_node)
                sess.flush()

            payload = build_holds_edge_payload(
                ts_code=ts_code,
                qty=pos.quantity,
                avg_cost=float(pos.avg_cost),
                purchase_date=None,  # Position model 当前无 purchase_date 字段
                fallback_date=pos.updated_at or datetime(2024, 1, 1),
            )

            # 走 ON CONFLICT DO NOTHING(幂等键 UNIQUE constraint Plan 1A 已建)
            stmt = pg_insert(ChatMemoryEdge).values(
                user_id=user_id,
                source_node_id=user_node.node_id,
                target_node_id=stock_node.node_id,
                rel_type=payload["rel_type"],
                valid_from=payload["valid_from"],
                source_episode_id=seed_episode.episode_id,
                importance=payload["importance"],
                reasoning=payload["reasoning"],
                properties={"qty": payload["qty"], "avg_cost": payload["avg_cost"]},
                search_tokens=jieba_tokenize_for_search(f"HOLDS User Stock {ts_code} {pos.name}"),
            )
            stmt = stmt.on_conflict_do_nothing(constraint="uq_edges_idempotency_key")
            sess.execute(stmt)

        # 4. (留 hook) preferences 路 — User model 无 preferences 列, 跳过
        # TODO Plan 1B+: 若 PR #39 / v0.8 加了 preferences JSONB, 这里补 PREFERS edges
        logger.info("cold_start: preferences seed skipped (User.preferences not yet present)")

        # 5. (留 hook) watchlist 路 — model 不存在, 跳过
        logger.info("cold_start: watchlist seed skipped (no watchlist model)")

        sess.commit()
        logger.info(
            "cold_start: seeded user %s with %d HOLDS edges",
            user_id,
            len(positions),
        )
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


# === CLI entry ===


def _build_pg_session_factory() -> Any:
    """从 env 建 sync session factory(给 CLI 用)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    def _factory() -> Session:
        return SessionFactory()

    return _factory


def main() -> None:
    parser = argparse.ArgumentParser(description="C.5 cold start populator")
    parser.add_argument("--user-id", required=True, help="user UUID to seed")
    args = parser.parse_args()

    factory = _build_pg_session_factory()
    asyncio.run(seed_user_graph(args.user_id, pg_session_factory=factory))
    print(f"cold_start: done for user {args.user_id}")


if __name__ == "__main__":
    main()
