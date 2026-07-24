from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

from app.models.paper_account import PaperAccount
from app.models.position import Position
from app.models.user import User
from app.models.watchlist import WatchlistItem
from app.services.monitoring.scope import load_active_subjects
from app.services.paper_trading.account_service import PaperAccountService
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
    paper_account: PaperAccount | None = None,
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
            paper_account_id=None if paper_account is None else paper_account.id,
            paper_account_generation=(
                None if paper_account is None else paper_account.generation
            ),
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


def test_scope_tracks_only_current_paper_account_generation_after_reset(
    db_session: Session,
) -> None:
    user = _user(db_session)
    other_user = _user(db_session)
    account_service = PaperAccountService(db_session)
    old_account = account_service.get_or_create(user_id=cast(uuid.UUID, user.id))

    _position(
        db_session,
        user,
        ts_code="600000.SH",
        name="浦发银行",
        quantity=100,
        paper_account=old_account,
    )
    _position(
        db_session,
        user,
        ts_code="000001.SZ",
        name="平安银行",
        quantity=100,
        paper_account=old_account,
    )
    _position(
        db_session,
        user,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=10,
    )
    _position(
        db_session,
        other_user,
        ts_code="000001.SZ",
        name="平安银行",
        quantity=50,
    )
    db_session.add(
        WatchlistItem(
            user_id=user.id,
            ts_code="600000.SH",
            name="浦发银行",
            monitoring_enabled=True,
        )
    )
    db_session.flush()

    before_reset = {
        (subject.user_id, subject.ts_code): subject
        for subject in load_active_subjects(db_session)
    }
    assert before_reset[(str(user.id), "600000.SH")].sources == (
        "position",
        "watchlist",
    )
    assert before_reset[(str(user.id), "000001.SZ")].sources == ("position",)
    assert before_reset[(str(user.id), "600519.SH")].sources == ("position",)
    assert before_reset[(str(other_user.id), "000001.SZ")].sources == ("position",)

    new_account = account_service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("1000000.00"),
        source_session_id="monitoring-reset-session",
        confirmation_id="monitoring-reset-confirmation",
    )

    after_reset = {
        (subject.user_id, subject.ts_code): subject
        for subject in load_active_subjects(db_session)
    }
    assert after_reset[(str(user.id), "600000.SH")].sources == ("watchlist",)
    assert (str(user.id), "000001.SZ") not in after_reset
    assert after_reset[(str(user.id), "600519.SH")].sources == ("position",)
    assert after_reset[(str(other_user.id), "000001.SZ")].sources == ("position",)

    _position(
        db_session,
        user,
        ts_code="600000.SH",
        name="浦发银行",
        quantity=200,
        paper_account=new_account,
    )

    after_new_position = {
        (subject.user_id, subject.ts_code): subject
        for subject in load_active_subjects(db_session)
    }
    assert after_new_position[(str(user.id), "600000.SH")].sources == (
        "position",
        "watchlist",
    )
    assert len(
        [
            subject
            for subject in after_new_position.values()
            if subject.user_id == str(user.id) and subject.ts_code == "600000.SH"
        ]
    ) == 1
