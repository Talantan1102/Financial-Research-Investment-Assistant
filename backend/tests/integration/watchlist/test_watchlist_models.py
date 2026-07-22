import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.watchlist import WatchlistItem
from tests.unit._helpers import make_user


def test_monitoring_defaults_off_and_symbol_is_unique_per_user(db_session: Session) -> None:
    user = make_user(db_session)
    item = WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台")
    db_session.add(item)
    db_session.flush()
    assert item.monitoring_enabled is False

    db_session.add(WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_same_symbol_allowed_for_different_users(db_session: Session) -> None:
    user = make_user(db_session)
    other = make_user(db_session)
    first = WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台")
    second = WatchlistItem(user_id=other.id, ts_code="600519.SH", name="贵州茅台")
    db_session.add_all([first, second])
    db_session.flush()
    assert first.id != second.id
