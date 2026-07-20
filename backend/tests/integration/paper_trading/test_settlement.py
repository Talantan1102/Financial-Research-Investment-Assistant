from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import PaperAccount, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution
from app.services.paper_trading.settlement import PaperSettlementService
from app.services.trade_service import TradeService
from sqlalchemy.orm import Session

QUOTE_TIME = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


@pytest.fixture
def user(db_session: Session) -> User:
    token = uuid.uuid4().hex
    row = User(
        username=f"settle-{token}", email=f"settle-{token}@example.test", hashed_password="x"
    )
    db_session.add(row)
    db_session.flush()
    return row


def _account(db_session: Session, user: User, *, generation: int = 1) -> PaperAccount:
    row = PaperAccount.new(
        user_id=cast(uuid.UUID, user.id),
        generation=generation,
        initial_cash=Decimal("100000.00"),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _buy_order(
    db_session: Session,
    user: User,
    account: PaperAccount,
    *,
    quantity: int = 100,
    reserve: Decimal = Decimal("1005.01"),
) -> PaperOrder:
    account.available_cash = Decimal("100000.00") - reserve
    account.frozen_cash = reserve
    now = QUOTE_TIME
    row = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"confirm-{uuid.uuid4()}",
        source_session_id="session-1",
        source_message_id="message-1",
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=Decimal("10.00"),
        filled_quantity=0,
        avg_fill_price=None,
        reserved_cash=reserve,
        reserved_quantity=0,
        status=OrderStatus.OPEN,
        original_proposal={"quantity": quantity},
        confirmed_payload={"quantity": quantity},
        user_edits=None,
        quote_snapshot={"source": "fixed", "daily_upper_bound": "11.00"},
        rules_version="cn-a-20260706",
        expires_at=now + timedelta(minutes=5),
        confirmed_at=now,
        completed_at=None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _service(db_session: Session, *, at: datetime = QUOTE_TIME) -> PaperSettlementService:
    return PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)}),
        now=lambda: at,
    )


def _sell_order(
    db_session: Session,
    user: User,
    account: PaperAccount,
    lot: PaperHoldingLot,
    *,
    quantity: int = 100,
) -> PaperOrder:
    now = QUOTE_TIME + timedelta(days=1)
    row = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"sell-{uuid.uuid4()}",
        source_session_id="session-1",
        source_message_id="message-sell",
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=Decimal("11.00"),
        filled_quantity=0,
        avg_fill_price=None,
        reserved_cash=Decimal("0.00"),
        reserved_quantity=quantity,
        status=OrderStatus.OPEN,
        original_proposal={"quantity": quantity},
        confirmed_payload={"quantity": quantity},
        user_edits=None,
        quote_snapshot={"source": "fixed"},
        rules_version="cn-a-20260706",
        expires_at=now + timedelta(minutes=5),
        confirmed_at=now,
        completed_at=None,
    )
    lot.frozen_quantity = quantity
    db_session.add(row)
    db_session.flush()
    db_session.add(
        PaperLotReservation(
            order_id=row.id,
            lot_id=lot.id,
            account_id=account.id,
            account_generation=account.generation,
            reserved_quantity=quantity,
            remaining_quantity=quantity,
        )
    )
    db_session.flush()
    return row


def test_buy_fill_updates_every_projection_in_one_transaction(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account)

    fill = _service(db_session).apply(
        order_id=order.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )

    assert db_session.query(Trade).filter_by(id=str(fill.trade_id)).one().type is TradeType.BUY
    assert db_session.query(Position).filter_by(ts_code=order.ts_code).one().quantity == 100
    lot = db_session.query(PaperHoldingLot).one()
    assert lot.available_on == date(2026, 7, 21)
    assert lot.unit_cost == Decimal("10.0501")
    assert db_session.query(PaperCashLedger).filter_by(fill_id=fill.id).count() == 1
    assert order.status is OrderStatus.FILLED
    assert account.available_cash == Decimal("98994.99")
    assert account.frozen_cash == Decimal("0.00")


def test_partial_fills_charge_minimum_commission_only_once(db_session: Session, user: User) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account, quantity=200, reserve=Decimal("2005.02"))
    service = _service(db_session)

    first = service.apply(
        order_id=order.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    second = service.apply(
        order_id=order.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME + timedelta(seconds=1),
        match_pass=2,
    )

    assert first.commission == Decimal("5.0000")
    assert second.commission == Decimal("0.0000")
    assert first.transfer_fee == second.transfer_fee == Decimal("0.0100")
    assert account.available_cash == Decimal("97994.98")
    assert account.frozen_cash == Decimal("0.00")


def test_same_match_pass_retry_returns_same_fill_and_conflict_is_rejected(
    db_session: Session, user: User
) -> None:
    order = _buy_order(db_session, user, _account(db_session, user))
    service = _service(db_session)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    first = service.apply(
        order_id=order.id, execution=execution, quote_timestamp=QUOTE_TIME, match_pass=1
    )

    assert (
        service.apply(
            order_id=order.id, execution=execution, quote_timestamp=QUOTE_TIME, match_pass=1
        ).id
        == first.id
    )
    with pytest.raises(PaperTradingError, match="watermark"):
        service.apply(
            order_id=order.id,
            execution=Execution(price=Decimal("9.99"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
    assert db_session.query(PaperFill).count() == 1
    assert db_session.query(PaperMatchPass).count() == 1


@pytest.mark.parametrize(
    ("execution", "code"),
    [
        (Execution(price=Decimal("10.01"), quantity=100), "execution_price_mismatch"),
        (Execution(price=Decimal("10.00"), quantity=101), "execution_quantity_exceeds_remaining"),
    ],
)
def test_invalid_execution_leaves_no_projection(
    db_session: Session,
    user: User,
    execution: Execution,
    code: str,
) -> None:
    order = _buy_order(db_session, user, _account(db_session, user))

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=order.id, execution=execution, quote_timestamp=QUOTE_TIME, match_pass=1
        )

    assert error.value.code == code
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(Trade).count() == 0


def test_market_execution_must_stay_within_confirmed_daily_bounds(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account, reserve=Decimal("1105.01"))
    order.order_type = OrderType.MARKET  # type: ignore[assignment]
    order.limit_price = None  # type: ignore[assignment]
    order.quote_snapshot = {  # type: ignore[assignment]
        "source": "fixed",
        "daily_lower_bound": "9.00",
        "daily_upper_bound": "11.00",
    }
    db_session.flush()

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=order.id,
            execution=Execution(price=Decimal("11.01"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "execution_price_mismatch"
    assert db_session.query(PaperFill).count() == 0


def test_rejects_stale_account_generation_before_writes(db_session: Session, user: User) -> None:
    old = _account(db_session, user)
    order = _buy_order(db_session, user, old)
    old.status = "archived"
    new = _account(db_session, user, generation=2)
    db_session.flush()

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=order.id,
            execution=Execution(price=Decimal("10.00"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "stale_account_generation"
    assert new.available_cash == Decimal("100000.00")
    assert db_session.query(PaperFill).count() == 0


def test_sell_fill_consumes_fifo_reservation_and_credits_net_proceeds(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    buy = _buy_order(db_session, user, account)
    _service(db_session).apply(
        order_id=buy.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    lot = db_session.query(PaperHoldingLot).one()
    sell = _sell_order(db_session, user, account, lot)

    fill = _service(db_session, at=QUOTE_TIME + timedelta(days=1)).apply(
        order_id=sell.id,
        execution=Execution(price=Decimal("11.00"), quantity=100),
        quote_timestamp=QUOTE_TIME + timedelta(days=1),
        match_pass=1,
    )

    assert fill.commission == Decimal("5.0000")
    assert fill.stamp_duty == Decimal("0.5500")
    assert fill.transfer_fee == Decimal("0.0100")
    assert lot.remaining_quantity == lot.frozen_quantity == 0
    assert sell.reserved_quantity == 0
    assert account.available_cash == Decimal("100089.43")
    assert db_session.query(Position).filter_by(ts_code=sell.ts_code).one().quantity == 0


def test_cross_account_lot_provenance_is_rejected_without_partial_projection(
    db_session: Session, user: User
) -> None:
    source_account = _account(db_session, user)
    source_order = _buy_order(db_session, user, source_account)
    source_fill = PaperFill(
        order_id=source_order.id,
        fill_seq=1,
        quantity=100,
        price=Decimal("10.00"),
        gross_amount=Decimal("1000.0000"),
        commission=Decimal("5.0000"),
        stamp_duty=Decimal("0.0000"),
        transfer_fee=Decimal("0.0100"),
        quote_timestamp=QUOTE_TIME,
        quote_source="fixed",
        executed_at=QUOTE_TIME,
        trade_id=uuid.uuid4(),
    )
    db_session.add(source_fill)
    db_session.flush()
    other_token = uuid.uuid4().hex
    other_user = User(
        username=f"other-{other_token}",
        email=f"other-{other_token}@example.test",
        hashed_password="x",
    )
    db_session.add(other_user)
    db_session.flush()
    other_account = _account(db_session, other_user)
    bad_lot = PaperHoldingLot(
        account_id=other_account.id,
        generation=other_account.generation,
        ts_code="600519.SH",
        name="贵州茅台",
        source_fill_id=source_fill.id,
        original_quantity=100,
        remaining_quantity=100,
        frozen_quantity=0,
        unit_cost=Decimal("10.0501"),
        available_on=date(2026, 7, 21),
    )
    db_session.add(bad_lot)
    db_session.flush()
    sell = _sell_order(db_session, other_user, other_account, bad_lot)
    before_fills = db_session.query(PaperFill).count()
    before_lots = db_session.query(PaperHoldingLot).count()
    before_trades = db_session.query(Trade).count()
    before_positions = db_session.query(Position).count()
    before_ledger = db_session.query(PaperCashLedger).count()

    with pytest.raises(PaperTradingError) as error:
        _service(db_session, at=QUOTE_TIME + timedelta(days=1)).apply(
            order_id=sell.id,
            execution=Execution(price=Decimal("11.00"), quantity=100),
            quote_timestamp=QUOTE_TIME + timedelta(days=1),
            match_pass=1,
        )

    assert error.value.code == "invalid_holding_provenance"
    assert db_session.query(PaperFill).count() == before_fills
    assert db_session.query(PaperMatchPass).filter_by(order_id=sell.id).count() == 0
    assert db_session.query(PaperHoldingLot).count() == before_lots
    assert db_session.query(Trade).count() == before_trades
    assert db_session.query(Position).count() == before_positions
    assert db_session.query(PaperCashLedger).count() == before_ledger


def test_cross_generation_lot_provenance_is_rejected_without_partial_projection(
    db_session: Session, user: User
) -> None:
    old_account = _account(db_session, user)
    source_order = _buy_order(db_session, user, old_account)
    source_fill = PaperFill(
        order_id=source_order.id,
        fill_seq=1,
        quantity=100,
        price=Decimal("10.00"),
        gross_amount=Decimal("1000.0000"),
        commission=Decimal("5.0000"),
        stamp_duty=Decimal("0.0000"),
        transfer_fee=Decimal("0.0100"),
        quote_timestamp=QUOTE_TIME,
        quote_source="fixed",
        executed_at=QUOTE_TIME,
        trade_id=uuid.uuid4(),
    )
    db_session.add(source_fill)
    db_session.flush()
    old_account.status = "archived"
    current = _account(db_session, user, generation=2)
    bad_lot = PaperHoldingLot(
        account_id=current.id,
        generation=current.generation,
        ts_code="600519.SH",
        name="贵州茅台",
        source_fill_id=source_fill.id,
        original_quantity=100,
        remaining_quantity=100,
        frozen_quantity=0,
        unit_cost=Decimal("10.0501"),
        available_on=date(2026, 7, 21),
    )
    db_session.add(bad_lot)
    db_session.flush()
    sell = _sell_order(db_session, user, current, bad_lot)
    before_fills = db_session.query(PaperFill).count()
    before_lots = db_session.query(PaperHoldingLot).count()
    before_trades = db_session.query(Trade).count()
    before_positions = db_session.query(Position).count()
    before_ledger = db_session.query(PaperCashLedger).count()

    with pytest.raises(PaperTradingError) as error:
        _service(db_session, at=QUOTE_TIME + timedelta(days=1)).apply(
            order_id=sell.id,
            execution=Execution(price=Decimal("11.00"), quantity=100),
            quote_timestamp=QUOTE_TIME + timedelta(days=1),
            match_pass=1,
        )

    assert error.value.code == "invalid_holding_provenance"
    assert db_session.query(PaperFill).count() == before_fills
    assert db_session.query(PaperMatchPass).filter_by(order_id=sell.id).count() == 0
    assert db_session.query(PaperHoldingLot).count() == before_lots
    assert db_session.query(Trade).count() == before_trades
    assert db_session.query(Position).count() == before_positions
    assert db_session.query(PaperCashLedger).count() == before_ledger


def test_trade_projection_failure_rolls_back_all_fill_projections(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account)

    class FailingTradeService:
        def create(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("project trade failed")

    transaction = db_session.begin_nested()
    with pytest.raises(RuntimeError, match="project trade failed"):
        PaperSettlementService(
            db_session,
            calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
            now=lambda: QUOTE_TIME,
            trade_service=cast(TradeService, FailingTradeService()),
        ).apply(
            order_id=order.id,
            execution=Execution(price=Decimal("10.00"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
    transaction.rollback()
    db_session.expire_all()

    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperHoldingLot).count() == 0
    assert db_session.query(PaperCashLedger).count() == 0
    assert db_session.query(Trade).count() == 0
    assert db_session.query(Position).count() == 0


def test_insufficient_buy_reservation_can_be_rolled_back_without_partial_projection(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account, reserve=Decimal("1000.00"))
    transaction = db_session.begin_nested()

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=order.id,
            execution=Execution(price=Decimal("10.00"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
    transaction.rollback()
    db_session.expire_all()

    assert error.value.code == "insufficient_reservation"
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0
    assert db_session.query(PaperHoldingLot).count() == 0
    assert db_session.query(PaperCashLedger).count() == 0
    assert db_session.query(Trade).count() == 0
    assert db_session.query(Position).count() == 0
