"""Position SQLAlchemy model basic field tests (pg db_session fixture)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.position import Position
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


def test_position_can_be_persisted(db_session: Session) -> None:
    user = make_user(db_session)
    pos_id = str(uuid4())
    pos = Position(
        id=pos_id,
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
    db_session.add(pos)
    db_session.commit()

    fetched = db_session.query(Position).filter_by(id=pos_id).one()
    assert fetched.quantity == 220
    assert fetched.avg_cost == Decimal("1460.00")
    assert fetched.is_silenced is False


def test_position_unique_user_tscode(db_session: Session) -> None:
    user = make_user(db_session)
    common = {
        "user_id": user.id,
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "avg_cost": Decimal("1450.00"),
        "total_cost": Decimal("145000.00"),
        "realized_pnl": Decimal("0.00"),
    }
    db_session.add(Position(id=str(uuid4()), **common))
    db_session.commit()
    db_session.add(Position(id=str(uuid4()), **common))
    with pytest.raises(IntegrityError):
        db_session.commit()
