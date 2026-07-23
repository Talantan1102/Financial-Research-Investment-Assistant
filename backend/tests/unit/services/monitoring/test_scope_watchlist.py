from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.position import Position
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.services.monitoring.scope import load_active_subjects
from sqlalchemy.orm import Session


def _user(session: Session) -> User:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"monitoring-scope-{suffix}",
        email=f"monitoring-scope-{suffix}@example.test",
        hashed_password="not-used",
    )
    session.add(user)
    session.flush()
    return user


def _position(
    session: Session,
    user: User,
    *,
    ts_code: str,
    name: str,
    quantity: int,
) -> None:
    session.add(
        Position(
            id=str(uuid.uuid4()),
            user_id=user.id,
            ts_code=ts_code,
            name=name,
            quantity=quantity,
            avg_cost=Decimal("10"),
            total_cost=Decimal(10 * quantity),
            realized_pnl=Decimal("0"),
        )
    )
    session.flush()


def test_scope_unions_and_deduplicates_positions_and_enabled_watchlist(
    db_session: Session,
) -> None:
    user = _user(db_session)
    _position(
        db_session,
        user,
        ts_code="600000.SH",
        name="浦发银行",
        quantity=100,
    )
    db_session.add_all(
        [
            WatchlistItem(
                user_id=user.id,
                ts_code="600000.SH",
                name="浦发银行",
                monitoring_enabled=True,
            ),
            WatchlistItem(
                user_id=user.id,
                ts_code="000001.SZ",
                name="平安银行",
                monitoring_enabled=True,
            ),
            WatchlistItem(
                user_id=user.id,
                ts_code="600519.SH",
                name="贵州茅台",
                monitoring_enabled=False,
            ),
        ]
    )
    db_session.flush()

    subjects = load_active_subjects(db_session)
    by_code = {subject.ts_code: subject for subject in subjects}

    assert set(by_code) == {"600000.SH", "000001.SZ"}
    assert set(by_code["600000.SH"].sources) == {"position", "watchlist"}
    assert by_code["000001.SZ"].sources == ("watchlist",)


def test_disabling_watchlist_monitoring_keeps_position_in_scope(
    db_session: Session,
) -> None:
    user = _user(db_session)
    _position(
        db_session,
        user,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
    )
    db_session.add(
        WatchlistItem(
            user_id=user.id,
            ts_code="600519.SH",
            name="贵州茅台",
            monitoring_enabled=False,
        )
    )
    db_session.flush()

    subjects = load_active_subjects(db_session)

    assert len(subjects) == 1
    assert subjects[0].ts_code == "600519.SH"
    assert subjects[0].sources == ("position",)
