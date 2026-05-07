"""PositionService read + update_quote 测试。"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime
from decimal import Decimal

import pytest
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.position_service import PositionService
from app.services.trade_service import TradeService
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Trade.__table__.create(engine)
    Position.__table__.create(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def user(session: Session) -> User:
    return make_user(session)


def test_list_for_user_returns_only_active_positions(session: Session, user: User) -> None:
    """list_for_user 返回该 user 的全部 Position(包括 quantity=0 的清仓行)。"""
    trade_svc = TradeService(session)
    trade_svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    trade_svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="000001.SZ",
        name="平安银行",
        ttype=TradeType.INITIAL,
        quantity=1000,
        price=Decimal("12.00"),
        trade_date=date(2024, 6, 1),
    )
    session.commit()

    pos_svc = PositionService(session)
    positions = pos_svc.list_for_user(user.id)  # type: ignore[arg-type]
    codes = {p.ts_code for p in positions}
    assert codes == {"600519.SH", "000001.SZ"}


def test_update_quote_sets_price_and_timestamp(session: Session, user: User) -> None:
    """spec § 3.2 — 监控周期写 last_quote_price + last_quote_at。"""
    trade_svc = TradeService(session)
    trade_svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    session.commit()

    now = datetime.utcnow()
    pos_svc = PositionService(session)
    pos_svc.update_quote(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        price=Decimal("1580.00"),
        at=now,
    )
    session.commit()

    pos = session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.last_quote_price == Decimal("1580.0000")
    assert pos.last_quote_at == now


def test_update_quote_for_unknown_position_raises_lookup(session: Session, user: User) -> None:
    pos_svc = PositionService(session)
    with pytest.raises(LookupError):
        pos_svc.update_quote(
            user_id=user.id,  # type: ignore[arg-type]
            ts_code="000001.SZ",
            price=Decimal("12.00"),
            at=datetime.utcnow(),
        )
