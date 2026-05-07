"""TradeService.create + delete 测试 — 单事务 Trade insert/delete + Position UPSERT。"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.portfolio_exceptions import ExpiredDeletionError, ImmutableTradeError
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


def test_delete_within_24h_reverses_position(session: Session, user: User) -> None:
    """spec § 5 场景 2 — 删 buy → Position 回退到 initial+sell 序列结果。"""
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
    buy = svc.create(
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

    svc.delete(buy.id)  # type: ignore[arg-type]
    session.commit()

    pos = session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 170
    assert pos.avg_cost == Decimal("1450.0000")
    assert pos.total_cost == Decimal("246500.00")
    assert pos.realized_pnl == Decimal("4500.00")


def test_delete_after_24h_raises_expired(session: Session, user: User) -> None:
    svc = TradeService(session)
    trade = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=100,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    # 强制把 created_at 改到 25h 前(模拟过期)
    trade.created_at = datetime.utcnow() - timedelta(hours=25)  # type: ignore[assignment]
    session.flush()

    with pytest.raises(ExpiredDeletionError):
        svc.delete(trade.id)  # type: ignore[arg-type]


def test_update_initial_trade_succeeds_anytime(session: Session, user: User) -> None:
    """spec § 5 场景 5 — initial trade 任何时候可改字段。"""
    svc = TradeService(session)
    trade = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    # 强制 48h 前(模拟旧 trade)
    trade.created_at = datetime.utcnow() - timedelta(hours=48)  # type: ignore[assignment]
    session.flush()

    updated = svc.update(trade.id, price=Decimal("1455.00"))  # type: ignore[arg-type]
    session.commit()
    assert updated.price == Decimal("1455.00")

    # Position 应跟着 recompute(total_cost 变了)
    pos = session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.total_cost == Decimal("291000.00")  # 200 * 1455
    assert pos.avg_cost == Decimal("1455.0000")


def test_update_buy_trade_raises_immutable(session: Session, user: User) -> None:
    """spec § 5 场景 3 — 常规 trade(buy/sell)字段不可改。"""
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
    buy = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=50,
        price=Decimal("1500.00"),
        trade_date=date(2026, 1, 15),
    )
    session.commit()

    with pytest.raises(ImmutableTradeError):
        svc.update(buy.id, price=Decimal("1499.00"))  # type: ignore[arg-type]


def test_update_sell_trade_raises_immutable(session: Session, user: User) -> None:
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
    sell = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.SELL,
        quantity=30,
        price=Decimal("1600.00"),
        trade_date=date(2026, 4, 20),
    )
    session.commit()

    with pytest.raises(ImmutableTradeError):
        svc.update(sell.id, quantity=20)  # type: ignore[arg-type]


def test_update_unknown_field_raises_valueerror(session: Session, user: User) -> None:
    """update kwargs not in _INITIAL_UPDATABLE whitelist raise ValueError."""
    svc = TradeService(session)
    trade = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    session.commit()

    with pytest.raises(ValueError, match="unknown fields"):
        svc.update(trade.id, foo="bar")  # type: ignore[arg-type]
