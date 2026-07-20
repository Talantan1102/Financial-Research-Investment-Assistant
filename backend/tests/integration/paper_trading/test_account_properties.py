from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperLotReservation,
    PaperOrder,
)
from app.models.position import Position
from app.models.user import User
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution
from app.services.paper_trading.reconciliation import reconcile_account
from app.services.paper_trading.settlement import MatchQuoteEvidence, PaperSettlementService
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy.orm import Session

NOW = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


def _user_account(session: Session) -> tuple[User, PaperAccount]:
    token = uuid.uuid4().hex
    user = User(username=f"prop-{token}", email=f"{token}@example.test", hashed_password="x")
    session.add(user)
    session.flush()
    account = PaperAccountService(session).get_or_create(
        user_id=cast(uuid.UUID, user.id), initial_cash=Decimal("100000.00")
    )
    return user, account


def _buy_order(session: Session, user: User, account: PaperAccount, quantity: int) -> PaperOrder:
    reserve = Decimal(quantity) * Decimal("11.00") + Decimal("5.00")
    order = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"prop-{uuid.uuid4()}",
        source_session_id="property",
        source_message_id=uuid.uuid4().hex,
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
        quote_snapshot={
            "source": "property",
            "daily_lower_bound": "9.00",
            "daily_upper_bound": "11.00",
            "price_tick": "0.01",
        },
        rules_version="cn-a-20260706",
        expires_at=NOW + timedelta(hours=1),
        confirmed_at=NOW,
        completed_at=None,
    )
    session.add(order)
    session.flush()
    PaperAccountService(session).append_ledger(
        account=account,
        kind="order_freeze",
        amount=-reserve,
        available_after=cast(Decimal, account.available_cash) - reserve,
        frozen_after=cast(Decimal, account.frozen_cash) + reserve,
        business_key=f"order-freeze:{order.id}",
        order_id=order.id,
    )
    return order


def _evidence(
    execution: Execution,
    remaining: int,
    side: OrderSide = OrderSide.BUY,
    quoted_at: datetime = NOW,
) -> MatchQuoteEvidence:
    empty = tuple(QuoteLevel(price=Decimal("9.99"), quantity=0) for _ in range(5))
    level = QuoteLevel(price=execution.price, quantity=execution.quantity)
    return MatchQuoteEvidence(
        quote=RealtimeQuote(
            ts_code="600519.SH",
            name="贵州茅台",
            quoted_at=quoted_at,
            previous_close=Decimal("10.00"),
            last_price=execution.price,
            bids=(level, *empty[:4]) if side is OrderSide.SELL else empty,
            asks=(level, *empty[:4]) if side is OrderSide.BUY else empty,
            source="property",
            suspended=False,
        ),
        consumed_levels=(execution,),
        execution_index=0,
        remaining_before_match=remaining,
    )


@pytest.mark.parametrize("chunks", [(100,), (100, 100), (100, 200)])
def test_generated_partial_buy_sequences_preserve_every_invariant(
    db_session: Session, chunks: tuple[int, ...]
) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, sum(chunks))
    remaining = sum(chunks)
    for match_pass, quantity in enumerate(chunks, 1):
        execution = Execution(price=Decimal("10.00"), quantity=quantity)
        quote_time = NOW + timedelta(seconds=match_pass - 1)
        evidence = _evidence(execution, remaining, quoted_at=quote_time)
        PaperSettlementService(
            db_session,
            calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
            now=lambda: NOW,
            evidence_provider=lambda evidence=evidence, **_: evidence,
        ).apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=quote_time,
            match_pass=match_pass,
        )
        remaining -= quantity
        assert reconcile_account(db_session, account.id) == [], (
            f"chunks={chunks}, pass={match_pass}"
        )


def test_cancel_and_reset_generations_preserve_cash_and_share_conservation(
    db_session: Session,
) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    service = PaperAccountService(db_session)
    service.append_ledger(
        account=account,
        kind="reservation_release",
        amount=cast(Decimal, order.reserved_cash),
        available_after=cast(Decimal, account.available_cash) + cast(Decimal, order.reserved_cash),
        frozen_after=cast(Decimal, account.frozen_cash) - cast(Decimal, order.reserved_cash),
        business_key=f"cancel-release:{order.id}",
        order_id=order.id,
    )
    order.reserved_cash = Decimal("0.00")
    order.status = OrderStatus.CANCELLED
    order.completed_at = NOW
    db_session.flush()
    assert reconcile_account(db_session, account.id) == []

    replacement = service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("50000.00"),
        source_session_id="property-reset",
        confirmation_id="property-reset-1",
    )
    assert replacement.generation == 2
    assert reconcile_account(db_session, account.id) == []
    assert reconcile_account(db_session, replacement.id) == []


def test_buy_lot_quantity_equals_total_projected_position(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    evidence = _evidence(execution, 100)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: evidence,
    ).apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)

    lots = db_session.query(PaperHoldingLot).filter_by(account_id=account.id).all()
    assert sum(int(lot.remaining_quantity) for lot in lots) == 100
    assert reconcile_account(db_session, account.id) == []


def test_t1_sell_sequence_preserves_cash_and_share_conservation(db_session: Session) -> None:
    user, account = _user_account(db_session)
    buy = _buy_order(db_session, user, account, 100)
    buy_execution = Execution(price=Decimal("10.00"), quantity=100)
    buy_evidence = _evidence(buy_execution, 100)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: buy_evidence,
    ).apply(order_id=buy.id, execution=buy_execution, quote_timestamp=NOW, match_pass=1)
    lot = db_session.query(PaperHoldingLot).filter_by(account_id=account.id).one()
    assert lot.available_on == date(2026, 7, 21)

    sell_time = NOW + timedelta(days=1)
    sell = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"sell-{uuid.uuid4()}",
        source_session_id="property",
        source_message_id=uuid.uuid4().hex,
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("10.00"),
        filled_quantity=0,
        avg_fill_price=None,
        reserved_cash=Decimal("0.00"),
        reserved_quantity=100,
        status=OrderStatus.OPEN,
        original_proposal={"quantity": 100},
        confirmed_payload={"quantity": 100},
        user_edits=None,
        quote_snapshot={"source": "property", "price_tick": "0.01"},
        rules_version="cn-a-20260706",
        expires_at=sell_time + timedelta(hours=1),
        confirmed_at=sell_time,
        completed_at=None,
    )
    lot.frozen_quantity = 100
    db_session.add(sell)
    db_session.flush()
    db_session.add(
        PaperLotReservation(
            order_id=sell.id,
            lot_id=lot.id,
            account_id=account.id,
            account_generation=account.generation,
            reserved_quantity=100,
            remaining_quantity=100,
        )
    )
    db_session.flush()
    sell_execution = Execution(price=Decimal("10.00"), quantity=100)
    sell_evidence = _evidence(sell_execution, 100, side=OrderSide.SELL, quoted_at=sell_time)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: sell_time,
        evidence_provider=lambda **_: sell_evidence,
    ).apply(
        order_id=sell.id,
        execution=sell_execution,
        quote_timestamp=sell_time,
        match_pass=1,
    )

    assert lot.remaining_quantity == 0
    assert reconcile_account(db_session, account.id) == []


def test_reconciler_detects_lot_and_position_projection_corruption(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    evidence = _evidence(execution, 100)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: evidence,
    ).apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)
    lot = db_session.query(PaperHoldingLot).filter_by(account_id=account.id).one()
    lot.original_quantity = 101
    position = db_session.query(Position).filter_by(paper_account_id=account.id).one()
    position.quantity = 99
    db_session.flush()

    codes = [row.code for row in reconcile_account(db_session, account.id)]

    assert codes == [
        "buy_fill_lot_mismatch",
        "lot_source_fill_invalid",
        "position_projection_mismatch",
    ]


def test_suspended_account_cannot_settle_an_existing_open_order(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    account.available_cash = cast(Decimal, account.available_cash) - Decimal("1.00")
    db_session.flush()
    assert reconcile_account(db_session, account.id)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    evidence = _evidence(execution, 100)

    with pytest.raises(PaperTradingError) as exc_info:
        PaperSettlementService(
            db_session,
            calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
            now=lambda: NOW,
            evidence_provider=lambda **_: evidence,
        ).apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)

    assert exc_info.value.code == "stale_account_generation"
