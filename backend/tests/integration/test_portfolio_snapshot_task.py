"""Integration test — snapshot_portfolios Celery task (eager mode).

Tests:
- Task runs against real PG (db_session fixture, savepoint isolation).
- Seeds Position rows; calls task body directly with injected session.
- Asserts PositionSnapshot rows written with correct market_value.
- Idempotent upsert: second call does NOT create duplicate rows.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.position import Position
from app.models.position_snapshot import PositionSnapshot
from app.services.position_snapshot_repo import PositionSnapshotRepo
from tests.unit._helpers import make_user


def _make_position(
    db_session,
    user,
    ts_code: str,
    quantity: int,
    avg_cost: float,
    last_quote_price: float | None = None,
    asset_class: str = "stock",
) -> Position:
    pos = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code=ts_code,
        name=ts_code,
        quantity=quantity,
        avg_cost=Decimal(str(avg_cost)),
        total_cost=Decimal(str(avg_cost * quantity)),
        last_quote_price=Decimal(str(last_quote_price)) if last_quote_price else None,
        asset_class=asset_class,
    )
    db_session.add(pos)
    db_session.flush()
    return pos


def _run_task_with_session(db_session):
    """Call the task implementation with an injected session (no broker)."""
    from app.tasks.portfolio_snapshot import _run_snapshot

    with patch("app.tasks.portfolio_snapshot._get_session", return_value=db_session):
        # _run_snapshot must NOT close our test session, so we patch close to no-op
        with patch.object(db_session, "close"):
            return _run_snapshot()


def test_snapshot_writes_market_value_from_last_quote_price(db_session):
    """When last_quote_price is set, market_value = quantity * last_quote_price."""
    user = make_user(db_session)
    _make_position(db_session, user, "600519.SH", 100, 1500.0, last_quote_price=1650.0)

    today = datetime.date.today()
    result = _run_task_with_session(db_session)

    assert result["count"] == 1
    assert result["date"] == str(today)

    rows = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user.id, ts_code="600519.SH", snapshot_date=today)
        .all()
    )
    assert len(rows) == 1
    assert float(rows[0].market_value) == pytest.approx(165000.0)
    assert float(rows[0].market_price) == pytest.approx(1650.0)
    assert rows[0].asset_class == "stock"


def test_snapshot_falls_back_to_avg_cost_when_no_quote(db_session):
    """When last_quote_price is None, market_value falls back to avg_cost * quantity."""
    user = make_user(db_session)
    _make_position(db_session, user, "110011.OF", 10000, 2.5, last_quote_price=None, asset_class="fund_otc")

    today = datetime.date.today()
    _run_task_with_session(db_session)

    rows = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user.id, ts_code="110011.OF", snapshot_date=today)
        .all()
    )
    assert len(rows) == 1
    assert float(rows[0].market_value) == pytest.approx(25000.0)
    assert rows[0].asset_class == "fund_otc"


def test_snapshot_skips_zero_quantity_positions(db_session):
    """Positions with quantity == 0 (cleared) must NOT produce a snapshot row."""
    user = make_user(db_session)
    _make_position(db_session, user, "000001.SZ", 0, 10.0, last_quote_price=11.0)

    _run_task_with_session(db_session)

    count = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user.id, ts_code="000001.SZ")
        .count()
    )
    assert count == 0


def test_snapshot_idempotent_upsert(db_session):
    """Running the task twice for the same date must produce exactly 1 row (upsert)."""
    user = make_user(db_session)
    _make_position(db_session, user, "600519.SH", 100, 1500.0, last_quote_price=1650.0)

    _run_task_with_session(db_session)
    _run_task_with_session(db_session)

    count = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user.id, ts_code="600519.SH")
        .count()
    )
    assert count == 1


def test_snapshot_handles_multiple_users_and_positions(db_session):
    """Task must snapshot ALL users' active positions, not just one user."""
    user_a = make_user(db_session)
    user_b = make_user(db_session)

    _make_position(db_session, user_a, "600519.SH", 100, 1500.0, last_quote_price=1650.0)
    _make_position(db_session, user_b, "600036.SH", 200, 40.0, last_quote_price=42.0)
    # user_b also has a zero-quantity cleared position — must be skipped
    _make_position(db_session, user_b, "000001.SZ", 0, 10.0, last_quote_price=11.0)

    today = datetime.date.today()
    result = _run_task_with_session(db_session)

    assert result["count"] == 2

    snap_a = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user_a.id, snapshot_date=today)
        .all()
    )
    snap_b_active = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user_b.id, ts_code="600036.SH", snapshot_date=today)
        .all()
    )
    snap_b_zero = (
        db_session.query(PositionSnapshot)
        .filter_by(user_id=user_b.id, ts_code="000001.SZ")
        .all()
    )

    assert len(snap_a) == 1
    assert float(snap_a[0].market_value) == pytest.approx(165000.0)
    assert len(snap_b_active) == 1
    assert float(snap_b_active[0].market_value) == pytest.approx(8400.0)
    assert len(snap_b_zero) == 0
