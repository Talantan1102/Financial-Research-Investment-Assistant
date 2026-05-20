"""Trade SQLAlchemy model basic field tests (pg db_session fixture)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.models.trade import Trade, TradeType
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


def test_trade_can_be_persisted(db_session: Session) -> None:
    user = make_user(db_session)
    trade_id = str(uuid4())
    trade = Trade(
        id=trade_id,
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        type=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
        note="initial position",
    )
    db_session.add(trade)
    db_session.commit()

    fetched = db_session.query(Trade).filter_by(id=trade_id).one()
    assert fetched.type == TradeType.INITIAL
    assert fetched.quantity == 200
    assert fetched.price == Decimal("1450.00")
    assert fetched.note == "initial position"


def test_trade_type_enum_accepts_all_three_values(db_session: Session) -> None:
    user = make_user(db_session)
    for ttype in [TradeType.INITIAL, TradeType.BUY, TradeType.SELL]:
        db_session.add(
            Trade(
                id=str(uuid4()),
                user_id=user.id,
                ts_code="600519.SH",
                name="贵州茅台",
                type=ttype,
                quantity=10,
                price=Decimal("1500.00"),
                trade_date=date.today(),
            )
        )
    db_session.commit()
    assert db_session.query(Trade).filter_by(user_id=user.id).count() == 3
