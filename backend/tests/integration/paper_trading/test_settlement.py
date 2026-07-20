from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
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
from app.services.paper_trading.settlement import MatchQuoteEvidence, PaperSettlementService
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from app.services.trade_service import TradeService
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

QUOTE_TIME = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


def _evidence(
    execution: Execution,
    *,
    ts_code: str = "600519.SH",
    timestamp: datetime = QUOTE_TIME,
    source: str = "actual-fixed",
    consumed_price: Decimal | None = None,
    side: OrderSide = OrderSide.BUY,
    book_price: Decimal | None = None,
    visible_quantity: int | None = None,
    suspended: bool = False,
    consumed_levels: tuple[Execution, ...] | None = None,
    execution_index: int = 0,
    remaining_before_match: int | None = None,
) -> MatchQuoteEvidence:
    visible_price = book_price or execution.price
    visible = execution.quantity if visible_quantity is None else visible_quantity
    empty_bids = tuple(
        QuoteLevel(price=visible_price - Decimal(index) / 100, quantity=0) for index in range(1, 6)
    )
    empty_asks = tuple(
        QuoteLevel(price=visible_price + Decimal(index) / 100, quantity=0) for index in range(1, 6)
    )
    if side is OrderSide.BUY:
        bids = empty_bids
        asks = (QuoteLevel(price=visible_price, quantity=visible), *empty_asks[:4])
    else:
        bids = (QuoteLevel(price=visible_price, quantity=visible), *empty_bids[:4])
        asks = empty_asks
    quote = RealtimeQuote(
        ts_code=ts_code,
        name="贵州茅台",
        quoted_at=timestamp,
        previous_close=Decimal("10.00"),
        last_price=execution.price,
        bids=bids,
        asks=asks,
        source=source,
        suspended=suspended,
    )
    return MatchQuoteEvidence(
        quote=quote,
        consumed_levels=consumed_levels
        or (Execution(price=consumed_price or execution.price, quantity=execution.quantity),),
        execution_index=execution_index,
        remaining_before_match=(
            remaining_before_match
            if remaining_before_match is not None
            else sum(level.quantity for level in consumed_levels or (execution,))
        ),
    )


def _multilevel_evidence(
    executions: tuple[Execution, ...],
    execution_index: int,
    *,
    source: str = "actual-depth",
    timestamp: datetime = QUOTE_TIME,
    remaining_before_match: int | None = None,
) -> MatchQuoteEvidence:
    asks = tuple(QuoteLevel(price=level.price, quantity=level.quantity) for level in executions)
    asks += tuple(
        QuoteLevel(price=executions[-1].price + Decimal(index) / 100, quantity=0)
        for index in range(1, 6 - len(asks))
    )
    bids = tuple(
        QuoteLevel(price=executions[0].price - Decimal(index) / 100, quantity=0)
        for index in range(1, 6)
    )
    quote = RealtimeQuote(
        ts_code="600519.SH",
        name="贵州茅台",
        quoted_at=timestamp,
        previous_close=Decimal("10.00"),
        last_price=executions[0].price,
        bids=bids,
        asks=asks,
        source=source,
        suspended=False,
    )
    return MatchQuoteEvidence(
        quote=quote,
        consumed_levels=executions,
        execution_index=execution_index,
        remaining_before_match=(
            remaining_before_match
            if remaining_before_match is not None
            else sum(level.quantity for level in executions)
        ),
    )


def test_match_quote_evidence_is_deeply_immutable() -> None:
    evidence = _evidence(Execution(price=Decimal("10.00"), quantity=100))

    with pytest.raises(ValidationError):
        evidence.quote.source = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        evidence.consumed_levels[0].quantity = 1  # type: ignore[misc]


def test_quote_source_is_trimmed_at_settlement_boundary(db_session: Session, user: User) -> None:
    order = _buy_order(db_session, user, _account(db_session, user))
    execution = Execution(price=Decimal("10.00"), quantity=100)
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: _evidence(execution, source="  actual-feed  "),
    )

    fill = service.apply(
        order_id=order.id,
        execution=execution,
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )

    match_pass = db_session.query(PaperMatchPass).one()
    assert fill.quote_source == "actual-feed"
    assert match_pass.quote_source == "actual-feed"
    assert match_pass.snapshot_summary["source"] == "actual-feed"


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
        quote_snapshot={"source": "fixed", "daily_upper_bound": "11.00", "price_tick": "0.01"},
        rules_version="cn-a-20260706",
        expires_at=now + timedelta(minutes=5),
        confirmed_at=now,
        completed_at=None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _service(db_session: Session, *, at: datetime = QUOTE_TIME) -> PaperSettlementService:
    def evidence_provider(**kwargs: object) -> MatchQuoteEvidence:
        order = db_session.get(PaperOrder, kwargs["order_id"])
        execution = cast(Execution, kwargs["execution"])
        assert order is not None
        return _evidence(
            execution,
            ts_code=cast(str, order.ts_code),
            timestamp=cast(datetime, kwargs["quote_timestamp"]),
            side=OrderSide(order.side),
            remaining_before_match=int(order.quantity)
            - int(order.filled_quantity)
            + sum(
                int(quantity)
                for quantity in db_session.scalars(
                    select(PaperMatchPass.matched_quantity).where(
                        PaperMatchPass.order_id == order.id,
                        PaperMatchPass.quote_timestamp == kwargs["quote_timestamp"],
                    )
                )
            ),
        )

    return PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22)}),
        now=lambda: at,
        evidence_provider=evidence_provider,
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
        quote_snapshot={"source": "fixed", "price_tick": "0.01"},
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
    assert fill.quote_source == "actual-fixed"
    match_row = db_session.query(PaperMatchPass).filter_by(fill_id=fill.id).one()
    assert match_row.snapshot_summary["source"] == "actual-fixed"
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
    conflicting_evidence = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: _evidence(execution, source="different-actual-feed"),
    )
    with pytest.raises(PaperTradingError) as evidence_error:
        conflicting_evidence.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
    assert evidence_error.value.code == "match_pass_conflict"
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
        "price_tick": "0.01",
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


@pytest.mark.parametrize(
    "price",
    [Decimal("10.00001"), Decimal("100000000000000"), Decimal("10.0050")],
)
def test_invalid_execution_price_is_rejected_before_projections(
    db_session: Session, user: User, price: Decimal
) -> None:
    order = _buy_order(db_session, user, _account(db_session, user))

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=order.id,
            execution=Execution(price=price, quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "invalid_execution_price"
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0


def test_three_partial_fills_average_uses_exact_prior_gross(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account, quantity=300, reserve=Decimal("3005.06"))
    order.limit_price = Decimal("10.0001")  # type: ignore[assignment]
    order.quote_snapshot = {"source": "fixed", "price_tick": "0.0001"}  # type: ignore[assignment]
    db_session.flush()
    service = _service(db_session)
    for index, price in enumerate(
        (Decimal("10.0000"), Decimal("10.0001"), Decimal("10.0000")), start=1
    ):
        service.apply(
            order_id=order.id,
            execution=Execution(price=price, quantity=100),
            quote_timestamp=QUOTE_TIME + timedelta(seconds=index),
            match_pass=index,
        )

    assert order.avg_fill_price == Decimal("10.0000")


@pytest.mark.parametrize("mismatch", ["timestamp", "symbol", "consumed", "object"])
def test_mismatched_actual_evidence_is_atomic(
    db_session: Session, user: User, mismatch: str
) -> None:
    order = _buy_order(db_session, user, _account(db_session, user))
    execution = Execution(price=Decimal("10.00"), quantity=100)

    def provider(**kwargs: object) -> MatchQuoteEvidence:
        del kwargs
        if mismatch == "object":
            return cast(MatchQuoteEvidence, object())
        return _evidence(
            execution,
            ts_code="000001.SZ" if mismatch == "symbol" else "600519.SH",
            timestamp=QUOTE_TIME + timedelta(seconds=1) if mismatch == "timestamp" else QUOTE_TIME,
            source="actual-feed",
            consumed_price=Decimal("9.99") if mismatch == "consumed" else None,
        )

    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=provider,
    )
    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "invalid_match_evidence"
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0
    assert db_session.query(PaperCashLedger).count() == 0
    assert db_session.query(Trade).count() == 0
    assert db_session.query(Position).count() == 0


@pytest.mark.parametrize(
    "mismatch",
    [
        "price_not_executable",
        "visible_quantity_short",
        "wrong_side",
        "suspended",
        "misordered",
        "crossed",
        "empty_source",
        "source_too_long",
    ],
)
def test_unmatchable_quote_evidence_is_atomic(
    db_session: Session, user: User, mismatch: str
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    before_account = (account.available_cash, account.frozen_cash)
    before_order = (order.status, order.filled_quantity, order.avg_fill_price)

    def provider(**kwargs: object) -> MatchQuoteEvidence:
        del kwargs
        evidence = _evidence(
            execution,
            book_price=Decimal("10.01") if mismatch == "price_not_executable" else None,
            visible_quantity=99 if mismatch == "visible_quantity_short" else None,
            side=OrderSide.SELL if mismatch == "wrong_side" else OrderSide.BUY,
            suspended=mismatch == "suspended",
            source=(
                "   "
                if mismatch == "empty_source"
                else "x" * 65
                if mismatch == "source_too_long"
                else "actual-feed"
            ),
        )
        if mismatch == "misordered":
            evidence = evidence.model_copy(
                update={
                    "quote": evidence.quote.model_copy(
                        update={
                            "asks": (
                                QuoteLevel(price=Decimal("10.00"), quantity=50),
                                QuoteLevel(price=Decimal("9.99"), quantity=50),
                                *evidence.quote.asks[2:],
                            )
                        }
                    )
                }
            )
        elif mismatch == "crossed":
            evidence = evidence.model_copy(
                update={
                    "quote": evidence.quote.model_copy(
                        update={
                            "bids": (
                                QuoteLevel(price=Decimal("10.00"), quantity=100),
                                *evidence.quote.bids[1:],
                            )
                        }
                    )
                }
            )
        return evidence

    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=provider,
    )
    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "invalid_match_evidence"
    assert (account.available_cash, account.frozen_cash) == before_account
    assert (order.status, order.filled_quantity, order.avg_fill_price) == before_order
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperMatchPass).count() == 0
    assert db_session.query(PaperCashLedger).count() == 0
    assert db_session.query(Trade).count() == 0
    assert db_session.query(Position).count() == 0


def test_two_level_match_settles_in_order_and_second_fill_retry_is_idempotent(
    db_session: Session, user: User
) -> None:
    executions = (
        Execution(price=Decimal("9.99"), quantity=100),
        Execution(price=Decimal("10.00"), quantity=200),
    )
    order = _buy_order(
        db_session,
        user,
        _account(db_session, user),
        quantity=300,
        reserve=Decimal("3010.00"),
    )

    def provider(**kwargs: object) -> MatchQuoteEvidence:
        execution = cast(Execution, kwargs["execution"])
        return _multilevel_evidence(executions, executions.index(execution))

    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=provider,
    )
    first = service.apply(
        order_id=order.id,
        execution=executions[0],
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    first_pass = db_session.query(PaperMatchPass).one()
    first_evidence = _multilevel_evidence(executions, 0)
    assert first_pass.fill_id == first.id
    assert first.order_id == order.id
    assert first.price == executions[0].price
    assert first.quantity == executions[0].quantity
    assert first_pass.matched_quantity == executions[0].quantity
    assert first_pass.quote_source == first_evidence.quote.source
    assert first_pass.snapshot_summary == first_evidence.quote.model_dump(mode="json")
    assert first_pass.consumed_levels == [level.model_dump(mode="json") for level in executions]
    second = service.apply(
        order_id=order.id,
        execution=executions[1],
        quote_timestamp=QUOTE_TIME,
        match_pass=2,
    )

    retry = service.apply(
        order_id=order.id,
        execution=executions[1],
        quote_timestamp=QUOTE_TIME,
        match_pass=2,
    )
    assert retry.id == second.id
    first_retry = service.apply(
        order_id=order.id,
        execution=executions[0],
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    assert first_retry.id == first.id
    fills = db_session.scalars(
        select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_seq)
    ).all()
    assert [fill.id for fill in fills] == [first.id, second.id]
    assert order.status is OrderStatus.FILLED


def test_five_level_match_settles_every_execution_in_price_order(
    db_session: Session, user: User
) -> None:
    executions = tuple(
        Execution(price=Decimal("9.95") + Decimal(index) / 100, quantity=100) for index in range(5)
    )
    order = _buy_order(
        db_session,
        user,
        _account(db_session, user),
        quantity=500,
        reserve=Decimal("5010.00"),
    )

    def provider(**kwargs: object) -> MatchQuoteEvidence:
        execution = cast(Execution, kwargs["execution"])
        return _multilevel_evidence(executions, executions.index(execution))

    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=provider,
    )
    for index, execution in enumerate(executions, start=1):
        service.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=QUOTE_TIME,
            match_pass=index,
        )

    fills = db_session.scalars(
        select(PaperFill).where(PaperFill.order_id == order.id).order_by(PaperFill.fill_seq)
    ).all()
    assert [(fill.price, fill.quantity) for fill in fills] == [
        (execution.price, execution.quantity) for execution in executions
    ]
    assert order.status is OrderStatus.FILLED


@pytest.mark.parametrize("tamper", ["skip_front", "drop_prior", "prior_price", "prior_quantity"])
def test_multilevel_evidence_rejects_skipped_or_tampered_prior_execution_atomically(
    db_session: Session, user: User, tamper: str
) -> None:
    executions = (
        Execution(price=Decimal("9.99"), quantity=100),
        Execution(price=Decimal("10.00"), quantity=200),
    )
    account = _account(db_session, user)
    order = _buy_order(
        db_session,
        user,
        account,
        quantity=300,
        reserve=Decimal("3010.00"),
    )
    evidence = _multilevel_evidence(executions, 1)
    if tamper != "skip_front":
        PaperSettlementService(
            db_session,
            calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
            now=lambda: QUOTE_TIME,
            evidence_provider=lambda **_: _multilevel_evidence(executions, 0),
        ).apply(
            order_id=order.id,
            execution=executions[0],
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
        if tamper == "drop_prior":
            evidence = evidence.model_copy(update={"consumed_levels": (executions[1],)})
        elif tamper == "prior_price":
            evidence = evidence.model_copy(
                update={
                    "consumed_levels": (
                        Execution(price=Decimal("9.98"), quantity=100),
                        executions[1],
                    )
                }
            )
        else:
            evidence = evidence.model_copy(
                update={
                    "consumed_levels": (
                        Execution(price=executions[0].price, quantity=99),
                        executions[1],
                    )
                }
            )
        current = executions[1]
        match_pass = 2
    else:
        current = executions[1]
        match_pass = 1
    before_account = (account.available_cash, account.frozen_cash)
    before_order = (order.status, order.filled_quantity, order.avg_fill_price)
    before_fills = db_session.query(PaperFill).count()
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: evidence,
    )

    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=current,
            quote_timestamp=QUOTE_TIME,
            match_pass=match_pass,
        )

    assert error.value.code == "invalid_match_evidence"
    assert (account.available_cash, account.frozen_cash) == before_account
    assert (order.status, order.filled_quantity, order.avg_fill_price) == before_order
    assert db_session.query(PaperFill).count() == before_fills


@pytest.mark.parametrize("watermarks", [(7, 8), (1, 3)])
def test_multilevel_match_rejects_wrong_global_watermark_sequence_atomically(
    db_session: Session, user: User, watermarks: tuple[int, int]
) -> None:
    executions = (
        Execution(price=Decimal("9.99"), quantity=100),
        Execution(price=Decimal("10.00"), quantity=200),
    )
    account = _account(db_session, user)
    order = _buy_order(
        db_session,
        user,
        account,
        quantity=300,
        reserve=Decimal("3010.00"),
    )
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **kwargs: _multilevel_evidence(
            executions, executions.index(cast(Execution, kwargs["execution"]))
        ),
    )
    before_account = (account.available_cash, account.frozen_cash)
    before_order = (order.status, order.filled_quantity, order.avg_fill_price)
    if watermarks[0] == 1:
        service.apply(
            order_id=order.id,
            execution=executions[0],
            quote_timestamp=QUOTE_TIME,
            match_pass=watermarks[0],
        )
        before_account = (account.available_cash, account.frozen_cash)
        before_order = (order.status, order.filled_quantity, order.avg_fill_price)

    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=executions[1 if watermarks[0] == 1 else 0],
            quote_timestamp=QUOTE_TIME,
            match_pass=watermarks[1 if watermarks[0] == 1 else 0],
        )

    assert error.value.code == "invalid_match_evidence"
    assert (account.available_cash, account.frozen_cash) == before_account
    assert (order.status, order.filled_quantity, order.avg_fill_price) == before_order
    assert db_session.query(PaperFill).count() == (1 if watermarks[0] == 1 else 0)


def test_old_snapshot_retries_after_new_snapshot_and_tamper_still_conflicts(
    db_session: Session, user: User
) -> None:
    snapshot_a = (
        Execution(price=Decimal("9.98"), quantity=100),
        Execution(price=Decimal("9.99"), quantity=100),
    )
    snapshot_b = (Execution(price=Decimal("10.00"), quantity=200),)
    time_b = QUOTE_TIME + timedelta(seconds=1)
    order = _buy_order(
        db_session,
        user,
        _account(db_session, user),
        quantity=400,
        reserve=Decimal("4010.00"),
    )

    def evidence_for(
        executions: tuple[Execution, ...], index: int, timestamp: datetime, remaining: int
    ) -> MatchQuoteEvidence:
        return _multilevel_evidence(
            executions,
            index,
            timestamp=timestamp,
            remaining_before_match=remaining,
        )

    evidence = evidence_for(snapshot_a, 0, QUOTE_TIME, 400)
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: evidence,
    )
    first_a = service.apply(
        order_id=order.id,
        execution=snapshot_a[0],
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    evidence = evidence_for(snapshot_a, 1, QUOTE_TIME, 400)
    second_a = service.apply(
        order_id=order.id,
        execution=snapshot_a[1],
        quote_timestamp=QUOTE_TIME,
        match_pass=2,
    )
    evidence = evidence_for(snapshot_b, 0, time_b, 200)
    service.apply(
        order_id=order.id,
        execution=snapshot_b[0],
        quote_timestamp=time_b,
        match_pass=3,
    )

    evidence = evidence_for(snapshot_a, 0, QUOTE_TIME, 400)
    assert (
        service.apply(
            order_id=order.id,
            execution=snapshot_a[0],
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        ).id
        == first_a.id
    )
    evidence = evidence_for(snapshot_a, 1, QUOTE_TIME, 400)
    assert (
        service.apply(
            order_id=order.id,
            execution=snapshot_a[1],
            quote_timestamp=QUOTE_TIME,
            match_pass=2,
        ).id
        == second_a.id
    )

    evidence = evidence_for(snapshot_a, 1, QUOTE_TIME, 400).model_copy(
        update={
            "quote": evidence_for(snapshot_a, 1, QUOTE_TIME, 400).quote.model_copy(
                update={"source": "tampered-source"}
            )
        }
    )
    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=snapshot_a[1],
            quote_timestamp=QUOTE_TIME,
            match_pass=2,
        )
    assert error.value.code == "match_pass_conflict"
    assert db_session.query(PaperFill).count() == 3


def test_new_snapshot_cannot_move_quote_time_backwards(db_session: Session, user: User) -> None:
    execution = Execution(price=Decimal("10.00"), quantity=100)
    later = QUOTE_TIME + timedelta(seconds=2)
    earlier = QUOTE_TIME + timedelta(seconds=1)
    order = _buy_order(
        db_session,
        user,
        _account(db_session, user),
        quantity=200,
        reserve=Decimal("2010.00"),
    )
    evidence = _evidence(execution, timestamp=later, remaining_before_match=200)
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: evidence,
    )
    service.apply(
        order_id=order.id,
        execution=execution,
        quote_timestamp=later,
        match_pass=1,
    )
    before = (order.status, order.filled_quantity, db_session.query(PaperFill).count())
    evidence = _evidence(execution, timestamp=earlier, remaining_before_match=100)

    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=earlier,
            match_pass=2,
        )

    assert error.value.code == "invalid_match_evidence"
    assert (order.status, order.filled_quantity, db_session.query(PaperFill).count()) == before


def test_global_watermark_cannot_repeat_on_a_new_snapshot(db_session: Session, user: User) -> None:
    execution = Execution(price=Decimal("10.00"), quantity=100)
    later = QUOTE_TIME + timedelta(seconds=1)
    order = _buy_order(
        db_session,
        user,
        _account(db_session, user),
        quantity=200,
        reserve=Decimal("2010.00"),
    )
    evidence = _evidence(execution, remaining_before_match=200)
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: QUOTE_TIME,
        evidence_provider=lambda **_: evidence,
    )
    service.apply(
        order_id=order.id,
        execution=execution,
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    evidence = _evidence(execution, timestamp=later, remaining_before_match=100)

    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=execution,
            quote_timestamp=later,
            match_pass=1,
        )

    assert error.value.code == "invalid_match_evidence"
    assert db_session.query(PaperFill).count() == 1


def test_two_sessions_same_match_watermark_create_one_projection(
    db_session: Session, pg_test_engine: Engine
) -> None:
    del db_session
    session_factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    setup = session_factory()
    token = uuid.uuid4().hex
    user = User(
        username=f"concurrent-{token}",
        email=f"concurrent-{token}@example.test",
        hashed_password="x",
    )
    setup.add(user)
    setup.flush()
    account = _account(setup, user)
    order = _buy_order(setup, user, account)
    setup.commit()
    order_id = cast(uuid.UUID, order.id)
    setup.close()
    execution = Execution(price=Decimal("10.00"), quantity=100)

    def settle() -> uuid.UUID:
        session = session_factory()
        try:

            def provider(**kwargs: object) -> MatchQuoteEvidence:
                del kwargs
                return _evidence(execution, source="actual-concurrent")

            fill = PaperSettlementService(
                session,
                calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
                now=lambda: QUOTE_TIME,
                evidence_provider=provider,
            ).apply(
                order_id=order_id,
                execution=execution,
                quote_timestamp=QUOTE_TIME,
                match_pass=1,
            )
            session.commit()
            return cast(uuid.UUID, fill.id)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        fill_ids = list(pool.map(lambda _: settle(), range(2)))
    verify = session_factory()
    try:
        assert fill_ids[0] == fill_ids[1]
        assert verify.query(PaperFill).filter_by(order_id=order_id).count() == 1
        assert verify.query(Trade).count() == 1
        assert (
            verify.query(PaperCashLedger).filter(PaperCashLedger.fill_id.is_not(None)).count() == 1
        )
    finally:
        verify.close()


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


def test_sell_consumes_lots_by_underlying_lot_age_not_reservation_age(
    db_session: Session, user: User
) -> None:
    account = _account(db_session, user)
    first_buy = _buy_order(db_session, user, account)
    _service(db_session).apply(
        order_id=first_buy.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME,
        match_pass=1,
    )
    older = db_session.query(PaperHoldingLot).one()
    second_buy = _buy_order(db_session, user, account)
    _service(db_session).apply(
        order_id=second_buy.id,
        execution=Execution(price=Decimal("10.00"), quantity=100),
        quote_timestamp=QUOTE_TIME + timedelta(seconds=1),
        match_pass=1,
    )
    lots = db_session.query(PaperHoldingLot).all()
    newer = next(lot for lot in lots if lot.id != older.id)
    older.created_at = datetime(2026, 7, 20, 1, 0)  # type: ignore[assignment]
    newer.created_at = datetime(2026, 7, 20, 2, 0)  # type: ignore[assignment]
    sell = _sell_order(db_session, user, account, newer, quantity=100)
    sell.quantity = 150  # type: ignore[assignment]
    sell.reserved_quantity = 150  # type: ignore[assignment]
    older.frozen_quantity = 100  # type: ignore[assignment]
    db_session.add(
        PaperLotReservation(
            order_id=sell.id,
            lot_id=older.id,
            account_id=account.id,
            account_generation=account.generation,
            reserved_quantity=100,
            remaining_quantity=100,
        )
    )
    newer_reservation = db_session.query(PaperLotReservation).filter_by(lot_id=newer.id).one()
    older_reservation = db_session.query(PaperLotReservation).filter_by(lot_id=older.id).one()
    newer_reservation.reserved_quantity = 50  # type: ignore[assignment]
    newer_reservation.remaining_quantity = 50  # type: ignore[assignment]
    newer_reservation.created_at = datetime(2026, 7, 20, 0, 0)  # type: ignore[assignment]
    older_reservation.created_at = datetime(2026, 7, 20, 3, 0)  # type: ignore[assignment]
    newer.frozen_quantity = 50  # type: ignore[assignment]
    db_session.flush()

    _service(db_session, at=QUOTE_TIME + timedelta(days=1)).apply(
        order_id=sell.id,
        execution=Execution(price=Decimal("11.00"), quantity=150),
        quote_timestamp=QUOTE_TIME + timedelta(days=1),
        match_pass=1,
    )

    assert older.remaining_quantity == older.frozen_quantity == 0
    assert newer.remaining_quantity == 50
    assert newer.frozen_quantity == 0
    assert older_reservation.remaining_quantity == 0
    assert newer_reservation.remaining_quantity == 0


def test_retry_fails_closed_if_linked_fill_resolves_to_another_order(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = _account(db_session, user)
    first_order = _buy_order(db_session, user, account)
    second_order = _buy_order(db_session, user, account)

    def fill_for(order: PaperOrder) -> PaperFill:
        return PaperFill(
            order_id=order.id,
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

    first_fill = fill_for(first_order)
    second_fill = fill_for(second_order)
    db_session.add_all([first_fill, second_fill])
    db_session.flush()
    db_session.add(
        PaperMatchPass(
            order_id=first_order.id,
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
            quote_source="fixed",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=100,
            fill_id=first_fill.id,
        )
    )
    db_session.flush()
    original_get = db_session.get

    def malicious_get(entity: object, ident: object, **kwargs: object) -> object:
        if entity is PaperFill and ident == first_fill.id:
            return second_fill
        return original_get(entity, ident, **kwargs)

    monkeypatch.setattr(db_session, "get", malicious_get)

    with pytest.raises(PaperTradingError) as error:
        _service(db_session).apply(
            order_id=first_order.id,
            execution=Execution(price=Decimal("10.00"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )

    assert error.value.code == "match_pass_conflict"


@pytest.mark.parametrize("target", ["other_account", "next_generation"])
def test_buy_lot_provenance_failure_rolls_back_apply(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    account = _account(db_session, user)
    order = _buy_order(db_session, user, account)
    if target == "other_account":
        token = uuid.uuid4().hex
        other_user = User(
            username=f"lot-target-{token}",
            email=f"lot-target-{token}@example.test",
            hashed_password="x",
        )
        db_session.add(other_user)
        db_session.flush()
        target_account = _account(db_session, other_user)
        target_account_id = target_account.id
        target_generation = target_account.generation
    else:
        target_account_id = account.id
        target_generation = int(account.generation) + 1
    service = _service(db_session)

    def wrong_lot(**kwargs: object) -> PaperHoldingLot:
        fill = cast(PaperFill, kwargs["fill"])
        source_order = cast(PaperOrder, kwargs["order"])
        actual = cast(Decimal, kwargs["actual"])
        return PaperHoldingLot(
            account_id=target_account_id,
            generation=target_generation,
            ts_code=source_order.ts_code,
            name=source_order.name,
            source_fill_id=fill.id,
            original_quantity=fill.quantity,
            remaining_quantity=fill.quantity,
            frozen_quantity=0,
            unit_cost=actual / int(fill.quantity),
            available_on=date(2026, 7, 21),
        )

    monkeypatch.setattr(service, "_build_buy_lot", wrong_lot)
    before_available = account.available_cash
    before_frozen = account.frozen_cash
    before_reserved = order.reserved_cash
    transaction = db_session.begin_nested()

    with pytest.raises(PaperTradingError) as error:
        service.apply(
            order_id=order.id,
            execution=Execution(price=Decimal("10.00"), quantity=100),
            quote_timestamp=QUOTE_TIME,
            match_pass=1,
        )
    transaction.rollback()
    db_session.expire_all()

    assert error.value.code == "invalid_holding_provenance"
    assert db_session.query(PaperMatchPass).count() == 0
    assert db_session.query(PaperFill).count() == 0
    assert db_session.query(PaperHoldingLot).count() == 0
    assert db_session.query(Trade).count() == 0
    assert db_session.query(Position).count() == 0
    assert db_session.query(PaperCashLedger).count() == 0
    restored_order = db_session.get(PaperOrder, order.id)
    restored_account = db_session.get(PaperAccount, account.id)
    assert restored_order is not None and restored_order.filled_quantity == 0
    assert restored_order.reserved_cash == before_reserved
    assert restored_account is not None and restored_account.available_cash == before_available
    assert restored_account.frozen_cash == before_frozen


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
            evidence_provider=_service(db_session)._evidence_provider,
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
