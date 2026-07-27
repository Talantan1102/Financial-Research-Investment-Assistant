from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.models.user import User
from app.models.watchlist import WatchlistAudit, WatchlistItem
from app.services.watchlist_service import ChangeSource, WatchlistService
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_user(factory: sessionmaker[Session]) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:12]
    with factory() as session:
        user = User(
            username=f"watch-concurrent-{suffix}",
            email=f"watch-concurrent-{suffix}@example.test",
            hashed_password="not-used",
        )
        session.add(user)
        session.commit()
        return user.id


def _set_timeout(session: Session) -> None:
    session.execute(text("SET LOCAL statement_timeout = '5s'"))


def test_concurrent_add_returns_existing_without_error_or_duplicate_audit(
    pg_test_engine: Engine,
) -> None:
    factory = _factory(pg_test_engine)
    user_id = _seed_user(factory)
    barrier = Barrier(2)

    def add(note: str) -> bool:
        with factory() as session:
            _set_timeout(session)
            barrier.wait()
            result = WatchlistService(session).add(
                user_id=user_id,
                ts_code="600519.SH",
                name="贵州茅台",
                note=note,
                source=ChangeSource(),
            )
            session.commit()
            return result.created

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(add, ("first", "second")))

    with factory() as session:
        assert sorted(created) == [False, True]
        assert (
            session.scalar(
                select(func.count())
                .select_from(WatchlistItem)
                .where(WatchlistItem.user_id == user_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WatchlistAudit)
                .where(WatchlistAudit.user_id == user_id)
            )
            == 1
        )
        assert (
            session.scalar(select(WatchlistAudit.action).where(WatchlistAudit.user_id == user_id))
            == "add"
        )


def test_concurrent_updates_form_a_contiguous_audit_chain(
    pg_test_engine: Engine,
) -> None:
    factory = _factory(pg_test_engine)
    user_id = _seed_user(factory)
    with factory() as session:
        WatchlistService(session).add(
            user_id=user_id,
            ts_code="600519.SH",
            name="贵州茅台",
            note="original",
            source=ChangeSource(),
        )
        session.commit()

    barrier = Barrier(2)

    def update_note(note: str) -> None:
        with factory() as session:
            _set_timeout(session)
            barrier.wait()
            item = WatchlistService(session).update(
                user_id=user_id,
                ts_code="600519.SH",
                changes={"note": note},
                source=ChangeSource(),
            )
            assert item is not None
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update_note, ("first-update", "second-update")))

    with factory() as session:
        item = session.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user_id))
        updates = list(
            session.scalars(
                select(WatchlistAudit)
                .where(
                    WatchlistAudit.user_id == user_id,
                    WatchlistAudit.action == "update",
                )
                .order_by(WatchlistAudit.created_at, WatchlistAudit.id)
            )
        )
        assert len(updates) == 2
        assert updates[0].before_json["note"] == "original"
        assert updates[0].after_json["note"] == updates[1].before_json["note"]
        assert updates[1].after_json["note"] == item.note


def test_concurrent_same_update_appends_only_one_audit(
    pg_test_engine: Engine,
) -> None:
    factory = _factory(pg_test_engine)
    user_id = _seed_user(factory)
    with factory() as session:
        WatchlistService(session).add(
            user_id=user_id,
            ts_code="600519.SH",
            name="贵州茅台",
            note="original",
            source=ChangeSource(),
        )
        session.commit()

    barrier = Barrier(2)

    def update_once() -> None:
        with factory() as session:
            _set_timeout(session)
            barrier.wait()
            WatchlistService(session).update(
                user_id=user_id,
                ts_code="600519.SH",
                changes={"note": "same-target"},
                source=ChangeSource(),
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: update_once(), range(2)))

    with factory() as session:
        update_count = session.scalar(
            select(func.count())
            .select_from(WatchlistAudit)
            .where(
                WatchlistAudit.user_id == user_id,
                WatchlistAudit.action == "update",
            )
        )
        assert update_count == 1


def test_concurrent_remove_returns_true_then_false_without_deadlock(
    pg_test_engine: Engine,
) -> None:
    factory = _factory(pg_test_engine)
    user_id = _seed_user(factory)
    with factory() as session:
        WatchlistService(session).add(
            user_id=user_id,
            ts_code="600519.SH",
            name="贵州茅台",
            source=ChangeSource(),
        )
        session.commit()

    barrier = Barrier(2)

    def remove() -> bool:
        with factory() as session:
            _set_timeout(session)
            barrier.wait()
            result = WatchlistService(session).remove(
                user_id=user_id,
                ts_code="600519.SH",
                source=ChangeSource(),
            )
            session.commit()
            return result.removed

    with ThreadPoolExecutor(max_workers=2) as pool:
        removed = list(pool.map(lambda _: remove(), range(2)))

    with factory() as session:
        assert sorted(removed) == [False, True]
        assert (
            session.scalar(
                select(func.count())
                .select_from(WatchlistItem)
                .where(WatchlistItem.user_id == user_id)
            )
            == 0
        )
        actions = list(
            session.scalars(
                select(WatchlistAudit.action)
                .where(WatchlistAudit.user_id == user_id)
                .order_by(WatchlistAudit.created_at)
            )
        )
        assert actions == ["add", "remove"]
