"""TradeService.create 测试 — 单事务 Trade insert + Position UPSERT。"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal

import pytest
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.trade_service import TradeService
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user  # NEW: from cleanup


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


def test_create_initial_trade_creates_position_row(session: Session, user: User) -> None:
    svc = TradeService(session)
    trade = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
        note="initial",
    )
    session.commit()
    assert trade.id is not None

    pos = session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 200
    assert pos.avg_cost == Decimal("1450.0000")
    assert pos.total_cost == Decimal("290000.00")
    assert pos.realized_pnl == Decimal("0.00")
    assert pos.name == "贵州茅台"


def test_create_sequence_initial_buy_sell_matches_spec_scenario_1(
    session: Session, user: User
) -> None:
    """spec § 5 测试场景 1 的 e2e 重现 — TradeService 链式调用后 Position 数值。"""
    svc = TradeService(session)
    svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=50,
        price=Decimal("1500.00"),
        trade_date=date(2026, 1, 15),
    )
    svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.SELL,
        quantity=30,
        price=Decimal("1600.00"),
        trade_date=date(2026, 4, 20),
    )
    session.commit()

    pos = session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 220
    assert pos.avg_cost == Decimal("1460.0000")
    assert pos.total_cost == Decimal("321200.00")
    assert pos.realized_pnl == Decimal("4200.00")
    assert session.query(Trade).filter_by(user_id=user.id).count() == 3


def test_create_does_not_leak_to_other_user(session: Session, user: User) -> None:
    """Multi-account 隔离 — user_a 的 create 不影响 user_b 的 Position(spec § 5 场景 8)。"""
    svc = TradeService(session)
    user_b = make_user(session)

    svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    session.commit()

    assert session.query(Position).filter_by(user_id=user_b.id).count() == 0
