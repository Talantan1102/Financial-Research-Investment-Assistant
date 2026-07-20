"""TradeService.create + delete 测试 — 单事务 Trade insert/delete + Position UPSERT。"""

# TODO(test): spec § 5 scenario 9 (transaction atomicity — Trade write fail leaves
# Position untouched) deferred. Architecturally guaranteed by single-session
# contract (svc.create flushes; caller commits). Add explicit DB error injection
# test in v1.x if monitoring engine surfaces atomicity violations.

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.portfolio_exceptions import ExpiredDeletionError, ImmutableTradeError
from app.services.trade_service import TradeService
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user  # NEW: from cleanup


@pytest.fixture
def user(db_session: Session) -> User:
    return make_user(db_session)


def test_create_initial_trade_creates_position_row(db_session: Session, user: User) -> None:
    svc = TradeService(db_session)
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
    db_session.commit()
    assert trade.id is not None

    pos = db_session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 200
    assert pos.avg_cost == Decimal("1450.0000")
    assert pos.total_cost == Decimal("290000.00")
    assert pos.realized_pnl == Decimal("0.00")
    assert pos.name == "贵州茅台"


def test_create_preserves_explicit_trade_id(db_session: Session, user: User) -> None:
    trade = TradeService(db_session).create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=100,
        price=Decimal("1500.00"),
        trade_date=date(2026, 7, 20),
        trade_id="11111111-1111-1111-1111-111111111111",
    )

    assert trade.id == "11111111-1111-1111-1111-111111111111"


def test_manual_and_paper_trades_do_not_blend_positions(db_session: Session, user: User) -> None:
    account = PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000"))
    db_session.add(account)
    db_session.flush()
    service = TradeService(db_session)
    common = {
        "user_id": user.id,
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "ttype": TradeType.BUY,
        "price": Decimal("10"),
        "trade_date": date(2026, 7, 20),
    }
    service.create(**common, quantity=100)
    service.create(**common, quantity=200, paper_account_id=account.id, paper_account_generation=1)

    positions = db_session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").all()
    assert sorted(position.quantity for position in positions) == [100, 200]


def test_paper_generations_keep_separate_positions(db_session: Session, user: User) -> None:
    first = PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000"))
    db_session.add(first)
    db_session.flush()
    service = TradeService(db_session)
    service.create(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=100,
        price=Decimal("10"),
        trade_date=date(2026, 7, 20),
        paper_account_id=first.id,
        paper_account_generation=1,
    )
    first.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
    second = PaperAccount.new(user_id=user.id, generation=2, initial_cash=Decimal("1000"))
    db_session.add(second)
    db_session.flush()
    service.create(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=200,
        price=Decimal("10"),
        trade_date=date(2026, 7, 21),
        paper_account_id=second.id,
        paper_account_generation=2,
    )

    positions = db_session.query(Position).filter(Position.paper_account_id.is_not(None)).all()
    assert {(position.paper_account_generation, position.quantity) for position in positions} == {
        (1, 100),
        (2, 200),
    }


def test_paper_trade_is_immutable_for_delete_and_update(db_session: Session, user: User) -> None:
    account = PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000"))
    db_session.add(account)
    db_session.flush()
    service = TradeService(db_session)
    trade = service.create(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.BUY,
        quantity=100,
        price=Decimal("10"),
        trade_date=date(2026, 7, 20),
        paper_account_id=account.id,
        paper_account_generation=1,
    )

    with pytest.raises(ImmutableTradeError):
        service.delete(trade.id, user_id=user.id)
    with pytest.raises(ImmutableTradeError):
        service.update(trade.id, user_id=user.id, price=Decimal("11"))


def test_create_sequence_initial_buy_sell_matches_spec_scenario_1(
    db_session: Session, user: User
) -> None:
    """spec § 5 测试场景 1 的 e2e 重现 — TradeService 链式调用后 Position 数值。"""
    svc = TradeService(db_session)
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
    db_session.commit()

    pos = db_session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 220
    assert pos.avg_cost == Decimal("1460.0000")
    assert pos.total_cost == Decimal("321200.00")
    assert pos.realized_pnl == Decimal("4200.00")
    assert db_session.query(Trade).filter_by(user_id=user.id).count() == 3


def test_create_does_not_leak_to_other_user(db_session: Session, user: User) -> None:
    """Multi-account 隔离 — user_a 的 create 不影响 user_b 的 Position(spec § 5 场景 8)。"""
    svc = TradeService(db_session)
    user_b = make_user(db_session)

    svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    db_session.commit()

    assert db_session.query(Position).filter_by(user_id=user_b.id).count() == 0


def test_delete_within_24h_reverses_position(db_session: Session, user: User) -> None:
    """spec § 5 场景 2 — 删 buy → Position 回退到 initial+sell 序列结果。"""
    svc = TradeService(db_session)
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
    db_session.commit()

    svc.delete(buy.id, user_id=user.id)  # type: ignore[arg-type]
    db_session.commit()

    pos = db_session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.quantity == 170
    assert pos.avg_cost == Decimal("1450.0000")
    assert pos.total_cost == Decimal("246500.00")
    assert pos.realized_pnl == Decimal("4500.00")


def test_delete_after_24h_raises_expired(db_session: Session, user: User) -> None:
    svc = TradeService(db_session)
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
    db_session.flush()

    with pytest.raises(ExpiredDeletionError):
        svc.delete(trade.id, user_id=user.id)  # type: ignore[arg-type]


def test_update_initial_trade_succeeds_anytime(db_session: Session, user: User) -> None:
    """spec § 5 场景 5 — initial trade 任何时候可改字段。"""
    svc = TradeService(db_session)
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
    db_session.flush()

    updated = svc.update(trade.id, user_id=user.id, price=Decimal("1455.00"))  # type: ignore[arg-type]
    db_session.commit()
    assert updated.price == Decimal("1455.00")

    # Position 应跟着 recompute(total_cost 变了)
    pos = db_session.query(Position).filter_by(user_id=user.id, ts_code="600519.SH").one()
    assert pos.total_cost == Decimal("291000.00")  # 200 * 1455
    assert pos.avg_cost == Decimal("1455.0000")


def test_update_buy_trade_raises_immutable(db_session: Session, user: User) -> None:
    """spec § 5 场景 3 — 常规 trade(buy/sell)字段不可改。"""
    svc = TradeService(db_session)
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
    db_session.commit()

    with pytest.raises(ImmutableTradeError):
        svc.update(buy.id, user_id=user.id, price=Decimal("1499.00"))  # type: ignore[arg-type]


def test_update_sell_trade_raises_immutable(db_session: Session, user: User) -> None:
    svc = TradeService(db_session)
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
    db_session.commit()

    with pytest.raises(ImmutableTradeError):
        svc.update(sell.id, user_id=user.id, quantity=20)  # type: ignore[arg-type]


def test_update_unknown_field_raises_valueerror(db_session: Session, user: User) -> None:
    """update kwargs not in _INITIAL_UPDATABLE whitelist raise ValueError."""
    svc = TradeService(db_session)
    trade = svc.create(
        user_id=user.id,  # type: ignore[arg-type]
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=200,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    db_session.commit()

    with pytest.raises(ValueError, match="unknown fields"):
        svc.update(trade.id, user_id=user.id, foo="bar")  # type: ignore[arg-type]
