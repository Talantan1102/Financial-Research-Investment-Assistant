from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from random import Random
from typing import cast

import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperLotReservation,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.matcher import Execution
from app.services.paper_trading.reconciliation import reconcile_account
from app.services.paper_trading.settlement import MatchQuoteEvidence, PaperSettlementService
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy import delete, select, text
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


def _assert_conservation(session: Session, account: PaperAccount) -> None:
    rows = session.execute(
        select(PaperFill, PaperOrder)
        .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
        .where(
            PaperOrder.account_id == account.id,
            PaperOrder.account_generation == account.generation,
        )
    ).all()
    expected_cash = cast(Decimal, account.initial_cash)
    expected_shares = 0
    for fill, order in rows:
        fees = (
            cast(Decimal, fill.commission)
            + cast(Decimal, fill.stamp_duty)
            + cast(Decimal, fill.transfer_fee)
        )
        if order.side is OrderSide.BUY:
            expected_cash -= cast(Decimal, fill.gross_amount) + fees
            expected_shares += int(fill.quantity)
        else:
            expected_cash += cast(Decimal, fill.gross_amount) - fees
            expected_shares -= int(fill.quantity)
    assert (
        cast(Decimal, account.available_cash) + cast(Decimal, account.frozen_cash) == expected_cash
    )
    lots = session.query(PaperHoldingLot).filter_by(
        account_id=account.id, generation=account.generation
    )
    assert sum(int(lot.remaining_quantity) for lot in lots) == expected_shares
    position = (
        session.query(Position)
        .filter_by(
            paper_account_id=account.id,
            paper_account_generation=account.generation,
            ts_code="600519.SH",
        )
        .one_or_none()
    )
    assert (int(position.quantity) if position is not None else 0) == expected_shares
    assert reconcile_account(session, account.id) == []


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


@pytest.mark.parametrize("seed", [7, 17, 29])
def test_fixed_seed_action_sequences_preserve_cash_shares_and_reservations(
    db_session: Session, seed: int
) -> None:
    rng = Random(seed)
    user, account = _user_account(db_session)
    sequence: list[str] = []
    quote_offset = 0
    for action in range(8):
        quantity = rng.choice((100, 200, 300))
        order = _buy_order(db_session, user, account, quantity)
        if rng.random() < 0.25:
            release = cast(Decimal, order.reserved_cash)
            PaperAccountService(db_session).append_ledger(
                account=account,
                kind="reservation_release",
                amount=release,
                available_after=cast(Decimal, account.available_cash) + release,
                frozen_after=cast(Decimal, account.frozen_cash) - release,
                business_key=f"seed-cancel:{seed}:{action}",
                order_id=order.id,
            )
            order.reserved_cash = Decimal("0.00")
            order.status = OrderStatus.CANCELLED
            order.completed_at = NOW
            db_session.flush()
            sequence.append(f"cancel:{quantity}")
            _assert_conservation(db_session, account)
            continue

        chunks = (quantity,) if rng.random() < 0.5 else (100, quantity - 100)
        chunks = tuple(chunk for chunk in chunks if chunk)
        remaining = quantity
        for match_pass, chunk in enumerate(chunks, 1):
            quote_offset += 1
            quote_time = NOW + timedelta(seconds=quote_offset)
            execution = Execution(price=Decimal("10.00"), quantity=chunk)
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
            remaining -= chunk
            sequence.append(f"buy:{chunk}")
            _assert_conservation(db_session, account)

    lots = (
        db_session.query(PaperHoldingLot)
        .filter(
            PaperHoldingLot.account_id == account.id,
            PaperHoldingLot.generation == account.generation,
            PaperHoldingLot.remaining_quantity > 0,
        )
        .all()
    )
    total = sum(int(lot.remaining_quantity) for lot in lots)
    assert total > 0, sequence
    sell_time = NOW + timedelta(days=1)
    sell = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"seed-sell-{seed}",
        source_session_id="property-seed",
        source_message_id=uuid.uuid4().hex,
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=total,
        limit_price=Decimal("10.00"),
        filled_quantity=0,
        avg_fill_price=None,
        reserved_cash=Decimal("0.00"),
        reserved_quantity=total,
        status=OrderStatus.OPEN,
        original_proposal={"quantity": total},
        confirmed_payload={"quantity": total},
        user_edits=None,
        quote_snapshot={"source": "property", "price_tick": "0.01"},
        rules_version="cn-a-20260706",
        expires_at=sell_time + timedelta(hours=1),
        confirmed_at=sell_time,
        completed_at=None,
    )
    db_session.add(sell)
    db_session.flush()
    for lot in lots:
        quantity = int(lot.remaining_quantity)
        lot.frozen_quantity = quantity
        db_session.add(
            PaperLotReservation(
                order_id=sell.id,
                lot_id=lot.id,
                account_id=account.id,
                account_generation=account.generation,
                reserved_quantity=quantity,
                remaining_quantity=quantity,
            )
        )
    db_session.flush()
    execution = Execution(price=Decimal("10.00"), quantity=total)
    evidence = _evidence(execution, total, side=OrderSide.SELL, quoted_at=sell_time)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: sell_time,
        evidence_provider=lambda **_: evidence,
    ).apply(order_id=sell.id, execution=execution, quote_timestamp=sell_time, match_pass=1)
    sequence.append(f"sell:{total}")

    _assert_conservation(db_session, account)
    assert all(int(row.remaining_quantity) == 0 for row in lots)
    assert all(int(row.frozen_quantity) == 0 for row in lots)
    assert sell.status is OrderStatus.FILLED
    assert sell.reserved_quantity == 0


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
        "position_share_balance_mismatch",
    ]


def test_reconciler_detects_missing_remaining_shares_and_suspends_idempotently(
    db_session: Session,
) -> None:
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
    lot.remaining_quantity = 50
    db_session.flush()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == ["lot_share_balance_mismatch"]
    assert first == second
    assert first[0].details == {
        "actual_lot_quantity": 50,
        "expected_net_quantity": 100,
        "ts_code": "600519.SH",
    }
    assert account.status is PaperAccountStatus.SUSPENDED


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


def test_recorded_filled_quantity_above_order_quantity_has_exact_codes(
    db_session: Session,
) -> None:
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
    db_session.execute(
        text("ALTER TABLE paper_orders DROP CONSTRAINT ck_paper_orders_filled_quantity_range")
    )
    db_session.execute(
        text("ALTER TABLE paper_orders DROP CONSTRAINT ck_paper_orders_status_filled_quantity")
    )
    db_session.execute(
        text("UPDATE paper_orders SET filled_quantity = 101 WHERE id = :id"), {"id": order.id}
    )
    db_session.expire_all()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == [
        "order_filled_quantity_exceeds_order",
        "order_filled_quantity_mismatch",
    ]
    assert second == first
    refreshed = db_session.get(PaperAccount, account.id)
    assert refreshed is not None
    assert refreshed.status is PaperAccountStatus.SUSPENDED


def test_fill_aggregate_above_order_quantity_has_exact_codes(db_session: Session) -> None:
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
    db_session.add(
        PaperFill(
            order_id=order.id,
            fill_seq=2,
            quantity=1,
            price=Decimal("10.0000"),
            gross_amount=Decimal("10.0000"),
            commission=Decimal("0.0000"),
            stamp_duty=Decimal("0.0000"),
            transfer_fee=Decimal("0.0000"),
            quote_timestamp=NOW + timedelta(seconds=1),
            quote_source="corruption",
            executed_at=NOW,
            trade_id=uuid.uuid4(),
        )
    )
    db_session.flush()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == [
        "buy_fill_lot_mismatch",
        "fill_quantity_exceeds_order",
        "fill_trade_mismatch",
        "lot_share_balance_mismatch",
        "order_filled_quantity_mismatch",
        "position_share_balance_mismatch",
    ]
    assert second == first
    assert account.status is PaperAccountStatus.SUSPENDED


def test_negative_lot_remaining_has_exact_codes(db_session: Session) -> None:
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
    db_session.execute(
        text(
            "ALTER TABLE paper_holding_lots "
            "DROP CONSTRAINT ck_paper_holding_lots_remaining_nonnegative"
        )
    )
    db_session.execute(
        text(
            "ALTER TABLE paper_holding_lots "
            "DROP CONSTRAINT ck_paper_holding_lots_frozen_within_remaining"
        )
    )
    db_session.execute(
        text("UPDATE paper_holding_lots SET remaining_quantity = -1 WHERE id = :id"),
        {"id": lot.id},
    )
    db_session.expire_all()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == ["lot_quantity_invalid", "lot_share_balance_mismatch"]
    assert second == first
    refreshed = db_session.get(PaperAccount, account.id)
    assert refreshed is not None
    assert refreshed.status is PaperAccountStatus.SUSPENDED


def test_negative_lot_frozen_quantity_has_exact_codes(db_session: Session) -> None:
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
    db_session.execute(
        text(
            "ALTER TABLE paper_holding_lots "
            "DROP CONSTRAINT ck_paper_holding_lots_frozen_nonnegative"
        )
    )
    db_session.execute(
        text("UPDATE paper_holding_lots SET frozen_quantity = -1 WHERE id = :id"),
        {"id": lot.id},
    )
    db_session.expire_all()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == ["lot_quantity_invalid", "lot_reservation_mismatch"]
    assert second == first
    refreshed = db_session.get(PaperAccount, account.id)
    assert refreshed is not None
    assert refreshed.status is PaperAccountStatus.SUSPENDED


def test_missing_trade_projection_has_exact_codes(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    evidence = _evidence(execution, 100)
    fill = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: evidence,
    ).apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)
    db_session.execute(delete(Trade).where(Trade.id == str(fill.trade_id)))
    db_session.flush()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == [
        "fill_trade_mismatch",
        "position_projection_mismatch",
    ]
    assert second == first
    assert account.status is PaperAccountStatus.SUSPENDED


def test_reconciliation_corruption_is_isolated_by_user_generation_and_manual_scope(
    db_session: Session,
) -> None:
    user_a, generation_one = _user_account(db_session)
    order = _buy_order(db_session, user_a, generation_one, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    evidence = _evidence(execution, 100)
    PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: evidence,
    ).apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)
    generation_two = PaperAccountService(db_session).reset_confirmed(
        user_id=cast(uuid.UUID, user_a.id),
        initial_cash=Decimal("50000.00"),
        source_session_id="isolation-reset",
        confirmation_id="isolation-reset-1",
    )
    user_b, other_account = _user_account(db_session)
    db_session.add(
        Position(
            id=str(uuid.uuid4()),
            user_id=user_a.id,
            ts_code="600519.SH",
            name="manual-isolated",
            quantity=999,
            avg_cost=Decimal("1.0000"),
            total_cost=Decimal("999.00"),
            realized_pnl=Decimal("0.00"),
            paper_account_id=None,
            paper_account_generation=None,
        )
    )
    lot = db_session.query(PaperHoldingLot).filter_by(account_id=generation_one.id).one()
    lot.remaining_quantity = 50
    db_session.flush()

    broken = reconcile_account(db_session, generation_one.id)
    other = reconcile_account(db_session, other_account.id)
    next_generation = reconcile_account(db_session, generation_two.id)

    assert [row.code for row in broken] == ["lot_share_balance_mismatch"]
    assert other == []
    assert next_generation == []
    assert generation_one.status is PaperAccountStatus.SUSPENDED
    assert other_account.status is PaperAccountStatus.ACTIVE
    assert generation_two.status is PaperAccountStatus.ACTIVE
    assert user_b.id != user_a.id
