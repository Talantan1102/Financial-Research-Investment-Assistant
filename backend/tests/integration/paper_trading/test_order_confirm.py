from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from app.models.paper_account import PaperAccount, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    PaperFill,
    PaperLotReservation,
    PaperOrder,
)
from app.models.user import User
from app.schemas.paper_trading import OrderDraft
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 20, 10, 0, 5, tzinfo=SHANGHAI)


class FixedQuoteProvider:
    def __init__(self, quote: RealtimeQuote) -> None:
        self.quote = quote
        self.calls = 0
        self.on_get: Callable[[int], None] | None = None

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        self.calls += 1
        if self.on_get is not None:
            self.on_get(self.calls)
        return self.quote.model_copy(update={"ts_code": ts_code})


def _quote() -> RealtimeQuote:
    return RealtimeQuote(
        ts_code="600519.SH",
        name="贵州茅台",
        quoted_at=NOW,
        previous_close=Decimal("1500"),
        last_price=Decimal("1501"),
        bids=tuple(QuoteLevel(price=Decimal(1500 - n), quantity=1000) for n in range(5)),
        asks=tuple(QuoteLevel(price=Decimal(1502 + n), quantity=1000) for n in range(5)),
        source="fixed",
        suspended=False,
    )


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(username=f"confirm-{suffix}", email=f"confirm-{suffix}@test", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def _service(
    session: Session,
    provider: FixedQuoteProvider,
    *,
    now: datetime | Callable[[], datetime] = NOW,
) -> PaperOrderService:
    return PaperOrderService(
        session,
        quote_provider=provider,
        clock=TradingClock(FixedTradingCalendar({NOW.date(), date(2026, 7, 21)})),
        rulebook=RuleBook.from_builtin_fixture(),
        now=now if callable(now) else lambda: now,
    )


def _draft(**changes: object) -> OrderDraft:
    values: dict[str, object] = {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "用户输入名",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": Decimal("1500"),
    }
    values.update(changes)
    return OrderDraft.model_validate(values)


def _prepare(service: PaperOrderService, user_id: uuid.UUID, **changes: object) -> PaperOrder:
    draft = _draft(name="贵州茅台", **changes)
    order, _ = service.prepare_order(
        user_id=user_id, session_id="s", message_id=uuid.uuid4().hex, **draft.model_dump()
    )
    return order


def test_confirm_is_idempotent_and_freezes_maximum_buy_exposure_once(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id, order_type="market", limit_price=None)
    draft = _draft(order_type="market", limit_price=None)
    first = service.confirm(
        user_id=user_id, order_id=order.id, draft=draft, client_request_id="confirm-1"
    )
    second = service.confirm(
        user_id=user_id, order_id=order.id, draft=draft, client_request_id="confirm-1"
    )
    account = service.account_service.get_active(user_id=user_id)
    assert first.id == second.id
    assert first.status is OrderStatus.OPEN
    assert first.name == "贵州茅台"
    assert first.confirmed_payload["name"] == "贵州茅台"
    assert first.reserved_cash == Decimal("165051.15")
    assert account.available_cash == Decimal("834948.85")
    assert account.frozen_cash == first.reserved_cash
    ledger = db_session.scalar(
        select(PaperCashLedger).where(PaperCashLedger.business_key == f"order-freeze:{first.id}")
    )
    assert ledger is not None
    assert ledger.order_id == first.id
    assert ledger.fill_id is None


def test_confirmation_keys_fail_closed_on_conflicting_reuse(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    service = _service(db_session, FixedQuoteProvider(_quote()))
    first = _prepare(service, user_id)
    second = _prepare(service, user_id, quantity=200)
    service.confirm(
        user_id=user_id, order_id=first.id, draft=_draft(), client_request_id="confirm-1"
    )
    with pytest.raises(PaperTradingError) as reused:
        service.confirm(
            user_id=user_id,
            order_id=second.id,
            draft=_draft(quantity=200),
            client_request_id="confirm-1",
        )
    assert reused.value.code == "confirmation_idempotency_conflict"
    with pytest.raises(PaperTradingError) as reconfirmed:
        service.confirm(
            user_id=user_id, order_id=first.id, draft=_draft(), client_request_id="confirm-2"
        )
    assert reconfirmed.value.code == "order_not_awaiting_confirmation"


def test_same_confirmation_key_is_scoped_per_user_and_ledgers_link_each_order(
    db_session: Session, user: User
) -> None:
    suffix = uuid.uuid4().hex
    other = User(
        username=f"other-{suffix}",
        email=f"other-{suffix}@test",
        hashed_password="x",
    )
    db_session.add(other)
    db_session.flush()
    user_ids = [cast(uuid.UUID, user.id), cast(uuid.UUID, other.id)]
    service = _service(db_session, FixedQuoteProvider(_quote()))
    confirmed: list[PaperOrder] = []
    for user_id in user_ids:
        PaperAccountService(db_session).get_or_create(user_id=user_id)
        order = _prepare(service, user_id)
        confirmed.append(
            service.confirm(
                user_id=user_id,
                order_id=order.id,
                draft=_draft(),
                client_request_id="same-user-scoped-key",
            )
        )

    ledgers = db_session.scalars(
        select(PaperCashLedger).where(
            PaperCashLedger.order_id.in_([order.id for order in confirmed])
        )
    ).all()
    assert {ledger.order_id for ledger in ledgers} == {order.id for order in confirmed}
    assert {ledger.business_key for ledger in ledgers} == {
        f"order-freeze:{order.id}" for order in confirmed
    }


def test_failed_maximum_buy_reservation_rolls_back_without_ledger(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(
        user_id=user_id, initial_cash=Decimal("160000")
    )
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id, order_type="market", limit_price=None)

    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(order_type="market", limit_price=None),
            client_request_id="max-reserve-too-large",
        )

    assert caught.value.code == "insufficient_cash"
    assert account.available_cash == Decimal("160000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert order.status is OrderStatus.AWAITING_CONFIRMATION
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaperCashLedger)
            .where(PaperCashLedger.business_key == f"order-freeze:{order.id}")
        )
        == 0
    )


def test_confirm_rejects_expired_and_closed_market_but_queues_closed_limit(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    provider = FixedQuoteProvider(_quote())
    open_service = _service(db_session, provider)
    expired = _prepare(open_service, user_id)
    expired.expires_at = NOW - timedelta(seconds=1)
    db_session.flush()
    quote_calls = provider.calls

    def unavailable(_: str) -> RealtimeQuote:
        raise RuntimeError("quote provider must not be called for an expired order")

    provider.get_sync = unavailable  # type: ignore[method-assign]
    cancelled = open_service.confirm(
        user_id=user_id, order_id=expired.id, draft=_draft(), client_request_id="expired"
    )
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.completed_at == NOW
    assert cancelled.client_request_id == "expired"
    assert cancelled.confirmed_at == NOW
    assert cancelled.confirmed_payload == _draft().model_dump(mode="json")
    assert cancelled.user_edits["name"] == {
        "from": "贵州茅台",
        "to": "用户输入名",
    }
    assert cancelled.reserved_cash == Decimal("0.00")
    assert cancelled.reserved_quantity == 0
    retried = open_service.confirm(
        user_id=user_id, order_id=expired.id, draft=_draft(), client_request_id="expired"
    )
    assert retried.id == cancelled.id
    assert provider.calls == quote_calls
    db_session.commit()
    persisted = db_session.get(PaperOrder, expired.id)
    assert persisted is not None
    assert persisted.status is OrderStatus.CANCELLED
    del provider.get_sync
    closed_at = NOW.replace(hour=15, minute=1)
    provider.quote = provider.quote.model_copy(update={"quoted_at": closed_at})
    closed_service = _service(db_session, provider, now=closed_at)
    market = _prepare(closed_service, user_id, order_type="market", limit_price=None)
    with pytest.raises(PaperTradingError) as closed:
        closed_service.confirm(
            user_id=user_id,
            order_id=market.id,
            draft=_draft(order_type="market", limit_price=None),
            client_request_id="closed-market",
        )
    assert closed.value.code == "market_order_outside_continuous_trading"
    limit = _prepare(closed_service, user_id, quantity=200)
    confirmed = closed_service.confirm(
        user_id=user_id,
        order_id=limit.id,
        draft=_draft(quantity=200),
        client_request_id="closed-limit",
    )
    assert confirmed.status is OrderStatus.QUEUED


def test_confirmation_id_length_matches_order_column_boundary(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    provider = FixedQuoteProvider(_quote())
    service = _service(db_session, provider)
    accepted = _prepare(service, user_id)
    confirmed = service.confirm(
        user_id=user_id,
        order_id=accepted.id,
        draft=_draft(),
        client_request_id="x" * 128,
    )
    assert confirmed.client_request_id == "x" * 128

    rejected = _prepare(service, user_id, quantity=200)
    calls_before = provider.calls
    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=rejected.id,
            draft=_draft(quantity=200),
            client_request_id="x" * 129,
        )
    assert caught.value.code == "invalid_order"
    assert provider.calls == calls_before


def test_slow_quote_crossing_expiry_persists_cancelled_without_reservation(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    current = [NOW.replace(hour=14, minute=59, second=58)]
    provider = FixedQuoteProvider(_quote().model_copy(update={"quoted_at": current[0]}))
    service = _service(db_session, provider, now=lambda: current[0])
    order = _prepare(service, user_id)

    def advance_on_confirm(call: int) -> None:
        if call == 2:
            current[0] = current[0] + timedelta(seconds=3)

    provider.on_get = advance_on_confirm
    cancelled = service.confirm(
        user_id=user_id,
        order_id=order.id,
        draft=_draft(),
        client_request_id="slow-expiry",
    )

    assert provider.calls == 2
    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.completed_at == current[0]
    assert cancelled.reserved_cash == Decimal("0.00")
    assert cancelled.reserved_quantity == 0


@pytest.mark.parametrize(
    ("order_type", "expected_status", "expected_error"),
    [
        ("limit", OrderStatus.QUEUED, None),
        ("market", None, "market_order_outside_continuous_trading"),
    ],
)
def test_slow_quote_uses_post_lock_market_phase(
    db_session: Session,
    user: User,
    order_type: str,
    expected_status: OrderStatus | None,
    expected_error: str | None,
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    current = [NOW.replace(hour=14, minute=56, second=59)]
    provider = FixedQuoteProvider(_quote().model_copy(update={"quoted_at": current[0]}))
    service = _service(db_session, provider, now=lambda: current[0])
    limit_price = Decimal("1500") if order_type == "limit" else None
    order = _prepare(service, user_id, order_type=order_type, limit_price=limit_price)

    def advance_on_confirm(call: int) -> None:
        if call == 2:
            current[0] = current[0] + timedelta(seconds=1)

    provider.on_get = advance_on_confirm
    if expected_error is not None:
        with pytest.raises(PaperTradingError) as caught:
            service.confirm(
                user_id=user_id,
                order_id=order.id,
                draft=_draft(order_type=order_type, limit_price=limit_price),
                client_request_id=f"phase-{order_type}",
            )
        assert caught.value.code == expected_error
    else:
        confirmed = service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(order_type=order_type, limit_price=limit_price),
            client_request_id=f"phase-{order_type}",
        )
        assert confirmed.status is expected_status


def test_expired_archived_generation_is_not_mutated(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    accounts = PaperAccountService(db_session)
    accounts.get_or_create(user_id=user_id)
    provider = FixedQuoteProvider(_quote())
    service = _service(db_session, provider)
    order = _prepare(service, user_id)
    order.expires_at = NOW - timedelta(seconds=1)
    accounts.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("800000"),
        source_session_id="expired-generation-reset",
        confirmation_id="expired-generation-reset",
    )
    db_session.flush()
    calls_before = provider.calls

    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(),
            client_request_id="expired-old-generation",
        )

    assert caught.value.code == "stale_account_generation"
    assert order.status is OrderStatus.AWAITING_CONFIRMATION
    assert order.client_request_id is None
    assert order.confirmed_payload is None
    assert provider.calls == calls_before


def _add_lot(
    session: Session,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    generation: int,
    quantity: int,
    available_on: date,
    executed_at: datetime,
) -> PaperHoldingLot:
    order = PaperOrder(
        account_id=account_id,
        account_generation=generation,
        user_id=user_id,
        source_session_id=f"seed-{uuid.uuid4().hex}",
        source_message_id="seed",
        proposal_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type="limit",
        quantity=quantity,
        limit_price=Decimal("100"),
        filled_quantity=quantity,
        avg_fill_price=Decimal("100"),
        status="filled",
        original_proposal={"seed": True},
        confirmed_payload={"seed": True},
        quote_snapshot={"seed": True},
        rules_version="seed",
        client_request_id=f"seed-{uuid.uuid4().hex}",
        expires_at=executed_at,
        confirmed_at=executed_at,
        completed_at=executed_at,
    )
    session.add(order)
    session.flush()
    fill = PaperFill(
        order_id=order.id,
        fill_seq=1,
        quantity=quantity,
        price=Decimal("100"),
        gross_amount=Decimal(100 * quantity),
        commission=Decimal("0"),
        stamp_duty=Decimal("0"),
        transfer_fee=Decimal("0"),
        quote_timestamp=executed_at,
        quote_source="seed",
        executed_at=executed_at,
        trade_id=uuid.uuid4(),
    )
    session.add(fill)
    session.flush()
    lot = PaperHoldingLot(
        account_id=account_id,
        generation=generation,
        ts_code="600519.SH",
        name="贵州茅台",
        source_fill_id=fill.id,
        original_quantity=quantity,
        remaining_quantity=quantity,
        frozen_quantity=0,
        unit_cost=Decimal("100"),
        available_on=available_on,
        created_at=executed_at,
    )
    session.add(lot)
    session.flush()
    return lot


def test_sell_confirmation_reserves_fifo_eligible_lots_atomically(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    first = _add_lot(
        db_session,
        user_id=user_id,
        account_id=account.id,
        generation=account.generation,
        quantity=100,
        available_on=NOW.date(),
        executed_at=NOW - timedelta(days=2),
    )
    second = _add_lot(
        db_session,
        user_id=user_id,
        account_id=account.id,
        generation=account.generation,
        quantity=100,
        available_on=NOW.date(),
        executed_at=NOW - timedelta(days=1),
    )
    _add_lot(
        db_session,
        user_id=user_id,
        account_id=account.id,
        generation=account.generation,
        quantity=100,
        available_on=NOW.date() + timedelta(days=1),
        executed_at=NOW,
    )
    service = _service(db_session, FixedQuoteProvider(_quote()))
    # The final confirmation may change the proposal from buy to sell.
    order = _prepare(service, user_id, quantity=200)
    confirmed = service.confirm(
        user_id=user_id,
        order_id=order.id,
        draft=_draft(side="sell", quantity=200),
        client_request_id="sell-confirm",
    )
    assert confirmed.reserved_cash == Decimal("0.00")
    assert confirmed.reserved_quantity == 200
    assert first.frozen_quantity == 100
    assert second.frozen_quantity == 100
    allocations = db_session.scalars(
        select(PaperLotReservation)
        .where(PaperLotReservation.order_id == confirmed.id)
        .order_by(PaperLotReservation.created_at, PaperLotReservation.id)
    ).all()
    assert {row.lot_id: (row.reserved_quantity, row.remaining_quantity) for row in allocations} == {
        first.id: (100, 100),
        second.id: (100, 100),
    }
    retried = service.confirm(
        user_id=user_id,
        order_id=order.id,
        draft=_draft(side="sell", quantity=200),
        client_request_id="sell-confirm",
    )
    assert retried.id == confirmed.id
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaperLotReservation)
            .where(PaperLotReservation.order_id == confirmed.id)
        )
        == 2
    )
    assert first.frozen_quantity == 100
    assert second.frozen_quantity == 100
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")


def test_failed_sell_reservation_leaves_all_lots_unchanged(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    lot = _add_lot(
        db_session,
        user_id=user_id,
        account_id=account.id,
        generation=account.generation,
        quantity=100,
        available_on=NOW.date(),
        executed_at=NOW - timedelta(days=1),
    )
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id, side="sell", quantity=100)
    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(side="sell", quantity=200),
            client_request_id="too-many",
        )
    assert caught.value.code == "insufficient_sellable_quantity"
    assert lot.frozen_quantity == 0


def test_sell_confirmation_rejects_cross_account_lot_provenance(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    suffix = uuid.uuid4().hex
    source_user = User(
        username=f"source-{suffix}", email=f"source-{suffix}@test", hashed_password="x"
    )
    db_session.add(source_user)
    db_session.flush()
    source_account = PaperAccountService(db_session).get_or_create(
        user_id=cast(uuid.UUID, source_user.id)
    )
    lot = _add_lot(
        db_session,
        user_id=cast(uuid.UUID, source_user.id),
        account_id=source_account.id,
        generation=source_account.generation,
        quantity=100,
        available_on=NOW.date(),
        executed_at=NOW - timedelta(days=1),
    )
    lot.account_id = account.id
    lot.generation = account.generation
    db_session.flush()
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id, side="sell", quantity=100)

    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(side="sell", quantity=100),
            client_request_id="bad-account-provenance",
        )
    assert caught.value.code == "invalid_holding_provenance"
    assert lot.frozen_quantity == 0
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaperLotReservation)
            .where(PaperLotReservation.order_id == order.id)
        )
        == 0
    )


def test_sell_confirmation_rejects_cross_generation_lot_provenance(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account_service = PaperAccountService(db_session)
    old = account_service.get_or_create(user_id=user_id)
    lot = _add_lot(
        db_session,
        user_id=user_id,
        account_id=old.id,
        generation=old.generation,
        quantity=100,
        available_on=NOW.date(),
        executed_at=NOW - timedelta(days=1),
    )
    current = account_service.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("1000000"),
        source_session_id="generation-reset",
        confirmation_id="generation-reset-confirmation",
    )
    lot.account_id = current.id
    lot.generation = current.generation
    db_session.flush()
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id, side="sell", quantity=100)

    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(side="sell", quantity=100),
            client_request_id="bad-generation-provenance",
        )
    assert caught.value.code == "invalid_holding_provenance"
    assert lot.frozen_quantity == 0
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaperLotReservation)
            .where(PaperLotReservation.order_id == order.id)
        )
        == 0
    )


def test_confirm_rejects_proposal_from_reset_generation(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    account_service = PaperAccountService(db_session)
    account_service.get_or_create(user_id=user_id)
    service = _service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id)
    account_service.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("800000"),
        source_session_id="reset-session",
        confirmation_id="reset-confirmation",
    )

    with pytest.raises(PaperTradingError) as caught:
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(),
            client_request_id="stale-confirmation",
        )
    assert caught.value.code == "stale_account_generation"


def test_confirm_persists_full_edited_draft_and_auditable_diff(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    provider = FixedQuoteProvider(_quote())
    service = _service(db_session, provider)
    order = _prepare(service, user_id)
    provider.quote = _quote().model_copy(update={"ts_code": "000001.SZ", "name": "平安银行"})
    edited = _draft(
        ts_code="000001.SZ",
        name="用户写错的名称",
        quantity=200,
        limit_price=Decimal("1500.01"),
    )

    confirmed = service.confirm(
        user_id=user_id,
        order_id=order.id,
        draft=edited,
        client_request_id="edited-confirmation",
    )

    assert confirmed.ts_code == "000001.SZ"
    assert confirmed.name == "平安银行"
    assert confirmed.quantity == 200
    assert confirmed.limit_price == Decimal("1500.01")
    assert confirmed.confirmed_payload == {
        "side": "buy",
        "ts_code": "000001.SZ",
        "name": "平安银行",
        "quantity": 200,
        "order_type": "limit",
        "limit_price": "1500.01",
    }
    assert confirmed.user_edits["name"] == {"from": "贵州茅台", "to": "平安银行"}
    assert confirmed.user_edits["ts_code"] == {"from": "600519.SH", "to": "000001.SZ"}


def test_confirm_fetches_quote_before_acquiring_confirmation_lock(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    provider = FixedQuoteProvider(_quote())
    service = _service(db_session, provider)
    order = _prepare(service, user_id)
    original_lock = service._lock_confirmation_key

    def assert_quote_already_fetched(*, user_id: uuid.UUID, client_request_id: str) -> None:
        assert provider.calls == 2
        original_lock(user_id=user_id, client_request_id=client_request_id)

    monkeypatch.setattr(service, "_lock_confirmation_key", assert_quote_already_fetched)
    service.confirm(
        user_id=user_id,
        order_id=order.id,
        draft=_draft(),
        client_request_id="quote-before-lock",
    )


def _committed_orders(
    engine: Engine, *, previous_close: Decimal, count: int
) -> tuple[uuid.UUID, list[uuid.UUID], RealtimeQuote]:
    quote = _quote().model_copy(
        update={
            "previous_close": previous_close,
            "last_price": previous_close,
            "bids": tuple(
                QuoteLevel(price=previous_close - n - 1, quantity=1000) for n in range(5)
            ),
            "asks": tuple(
                QuoteLevel(price=previous_close + n + 1, quantity=1000) for n in range(5)
            ),
        }
    )
    with Session(engine) as session:
        suffix = uuid.uuid4().hex
        user = User(
            username=f"cc-{suffix}",
            email=f"cc-{suffix}@test",
            hashed_password="x",
        )
        session.add(user)
        session.flush()
        user_id = cast(uuid.UUID, user.id)
        PaperAccountService(session).get_or_create(user_id=user_id)
        service = _service(session, FixedQuoteProvider(quote))
        order_ids = [
            cast(
                uuid.UUID,
                _prepare(service, user_id, order_type="market", limit_price=None).id,
            )
            for _ in range(count)
        ]
        session.commit()
    return user_id, order_ids, quote


def test_concurrent_same_confirmation_key_freezes_once(pg_test_engine: Engine) -> None:
    user_id, order_ids, quote = _committed_orders(
        pg_test_engine, previous_close=Decimal("1500"), count=1
    )
    barrier = threading.Barrier(2)
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def confirm() -> None:
        try:
            with Session(pg_test_engine) as session:
                service = _service(session, FixedQuoteProvider(quote))
                barrier.wait(timeout=5)
                order = service.confirm(
                    user_id=user_id,
                    order_id=order_ids[0],
                    draft=_draft(order_type="market", limit_price=None),
                    client_request_id="shared-confirmation",
                )
                session.commit()
                results.append(cast(uuid.UUID, order.id))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert results == [order_ids[0], order_ids[0]]
    with Session(pg_test_engine) as observer:
        assert (
            observer.scalar(
                select(func.count())
                .select_from(PaperCashLedger)
                .where(PaperCashLedger.business_key == f"order-freeze:{order_ids[0]}")
            )
            == 1
        )


def test_concurrent_orders_competing_for_cash_only_one_succeeds(pg_test_engine: Engine) -> None:
    user_id, order_ids, quote = _committed_orders(
        pg_test_engine, previous_close=Decimal("5000"), count=2
    )
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def confirm(order_id: uuid.UUID, key: str) -> None:
        try:
            with Session(pg_test_engine) as session:
                service = _service(session, FixedQuoteProvider(quote))
                barrier.wait(timeout=5)
                try:
                    service.confirm(
                        user_id=user_id,
                        order_id=order_id,
                        draft=_draft(order_type="market", limit_price=None),
                        client_request_id=key,
                    )
                    session.commit()
                    results.append("confirmed")
                except PaperTradingError as exc:
                    session.rollback()
                    results.append(exc.code)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=confirm, args=(order_id, f"cash-race-{index}"))
        for index, order_id in enumerate(order_ids)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(results) == ["confirmed", "insufficient_cash"]
    with Session(pg_test_engine) as observer:
        account = observer.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
        assert account is not None
        assert account.available_cash >= 0
        assert (
            observer.scalar(
                select(func.count())
                .select_from(PaperCashLedger)
                .where(
                    PaperCashLedger.kind == "order_freeze",
                    PaperCashLedger.account_id == account.id,
                )
            )
            == 1
        )
