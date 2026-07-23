from __future__ import annotations

import uuid

import pytest
from app.models.user import User
from app.models.watchlist import WatchlistAudit, WatchlistItem
from sqlalchemy import delete, inspect, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session


def _user(session: Session) -> User:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"watchlist-model-{suffix}",
        email=f"watchlist-model-{suffix}@example.test",
        hashed_password="not-used",
    )
    session.add(user)
    session.flush()
    return user


def test_monitoring_defaults_off_and_symbol_is_unique_per_user(
    db_session: Session,
) -> None:
    user = _user(db_session)
    item = WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台")
    db_session.add(item)
    db_session.flush()

    assert item.monitoring_enabled is False
    assert WatchlistItem.__table__.c.monitoring_enabled.server_default is not None

    db_session.add(
        WatchlistItem(user_id=user.id, ts_code="600519.SH", name="重复股票")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_same_symbol_allowed_for_different_users(db_session: Session) -> None:
    first_user = _user(db_session)
    second_user = _user(db_session)
    first = WatchlistItem(
        user_id=first_user.id,
        ts_code="600519.SH",
        name="贵州茅台",
    )
    second = WatchlistItem(
        user_id=second_user.id,
        ts_code="600519.SH",
        name="贵州茅台",
    )
    db_session.add_all([first, second])
    db_session.flush()

    assert first.id != second.id


def test_watchlist_audit_rows_are_append_only_by_contract() -> None:
    assert WatchlistAudit.__table__.name == "watchlist_audits"
    assert "updated_at" not in WatchlistAudit.__table__.c


def test_enabled_monitoring_has_a_partial_index(db_session: Session) -> None:
    indexes = inspect(db_session.bind).get_indexes("watchlist_items")
    monitoring_index = next(
        index
        for index in indexes
        if index["name"] == "ix_watchlist_items_monitoring_enabled_true"
    )
    assert "monitoring_enabled" in str(
        monitoring_index["dialect_options"]["postgresql_where"]
    )


def test_audit_update_and_delete_are_rejected_and_session_recovers(
    db_session: Session,
) -> None:
    user = _user(db_session)
    item = WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台")
    db_session.add(item)
    db_session.flush()
    audit = WatchlistAudit(
        item_id=item.id,
        user_id=user.id,
        action="add",
        before_json=None,
        after_json={"ts_code": "600519.SH"},
    )
    db_session.add(audit)
    db_session.flush()
    audit_id = audit.id
    db_session.commit()

    with pytest.raises(DBAPIError):
        db_session.execute(
            update(WatchlistAudit)
            .where(WatchlistAudit.id == audit_id)
            .values(action="tampered")
        )
    db_session.rollback()
    assert db_session.get(WatchlistAudit, audit_id).action == "add"

    with pytest.raises(DBAPIError):
        db_session.execute(delete(WatchlistAudit).where(WatchlistAudit.id == audit_id))
    db_session.rollback()
    assert db_session.get(WatchlistAudit, audit_id).action == "add"
