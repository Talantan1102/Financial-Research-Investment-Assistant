"""Trade SQLAlchemy model basic field tests (sqlite-override)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.trade import Trade, TradeType
from app.models.user import User
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    # Create only the tables under test to avoid JSONB compile errors
    # from unrelated models (e.g. industry_data) that lack sqlite with_variant.
    User.__table__.create(engine)
    Trade.__table__.create(engine)
    with Session(engine) as s:
        yield s


def test_trade_can_be_persisted(session: Session) -> None:
    user = make_user(session)
    trade = Trade(
        id=str(uuid4()),
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        type=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
        note="initial position",
    )
    session.add(trade)
    session.commit()

    fetched = session.query(Trade).filter_by(ts_code="600519.SH").one()
    assert fetched.type == TradeType.INITIAL
    assert fetched.quantity == 200
    assert fetched.price == Decimal("1450.00")
    assert fetched.note == "initial position"


def test_trade_type_enum_accepts_all_three_values(session: Session) -> None:
    user = make_user(session)
    for ttype in [TradeType.INITIAL, TradeType.BUY, TradeType.SELL]:
        session.add(
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
    session.commit()
    assert session.query(Trade).count() == 3
