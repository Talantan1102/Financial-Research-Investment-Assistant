"""Position SQLAlchemy model basic field tests (sqlite-override)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.position import Position
from app.models.user import User
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Position.__table__.create(engine)
    with Session(engine) as s:
        yield s


def _make_user(session: Session) -> User:
    uid = uuid4().hex[:8]
    user = User(
        id=str(uuid4()),
        username=f"user-{uid}",
        email=f"u-{uid}@test",
        hashed_password="x",
    )
    session.add(user)
    session.flush()
    return user


def test_position_can_be_persisted(session: Session) -> None:
    user = _make_user(session)
    pos = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=220,
        avg_cost=Decimal("1460.00"),
        total_cost=Decimal("321200.00"),
        realized_pnl=Decimal("4200.00"),
        last_quote_price=None,
        last_quote_at=None,
        is_silenced=False,
    )
    session.add(pos)
    session.commit()

    fetched = session.query(Position).filter_by(ts_code="600519.SH").one()
    assert fetched.quantity == 220
    assert fetched.avg_cost == Decimal("1460.00")
    assert fetched.is_silenced is False


def test_position_unique_user_tscode(session: Session) -> None:
    user = _make_user(session)
    common = {
        "user_id": user.id,
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "avg_cost": Decimal("1450.00"),
        "total_cost": Decimal("145000.00"),
        "realized_pnl": Decimal("0.00"),
    }
    session.add(Position(id=str(uuid4()), **common))
    session.commit()
    session.add(Position(id=str(uuid4()), **common))
    with pytest.raises(IntegrityError):
        session.commit()
