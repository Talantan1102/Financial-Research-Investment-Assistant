# mypy: disable-error-code="assignment"

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from app.models.paper_account import (
    PaperAccount,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
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
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

SHANGHAI = ZoneInfo("Asia/Shanghai")
OPEN_DAY = date(2026, 7, 20)
MORNING = datetime(2026, 7, 20, 10, 0, tzinfo=SHANGHAI)
CLOSE = datetime(2026, 7, 20, 15, 1, tzinfo=SHANGHAI)


class FixedQuoteProvider:
    def __init__(self, quoted_at: datetime = MORNING) -> None:
        self.quoted_at = quoted_at

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        return RealtimeQuote(
            ts_code=ts_code,
            name="贵州茅台",
            quoted_at=self.quoted_at,
            previous_close=Decimal("1500"),
            last_price=Decimal("1501"),
            bids=tuple(QuoteLevel(price=Decimal(1500 - n), quantity=1000) for n in range(5)),
            asks=tuple(QuoteLevel(price=Decimal(1502 + n), quantity=1000) for n in range(5)),
            source="fixed",
            suspended=False,
        )

    async def get(self, ts_code: str) -> RealtimeQuote:
        return self.get_sync(ts_code)


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(username=f"terminal-{suffix}", email=f"terminal-{suffix}@test", hashed_password="x")
    db_session.add(row)
    db_session.flush()
    return row


def _service(session: Session, *, now: datetime = MORNING) -> PaperOrderService:
    return PaperOrderService(
        session,
        quote_provider=FixedQuoteProvider(now),
        clock=TradingClock(FixedTradingCalendar({OPEN_DAY, date(2026, 7, 21)})),
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: now,
    )


def _confirmed_buy(
    session: Session,
    user_id: uuid.UUID,
    *,
    message_id: str | None = None,
    now: datetime = MORNING,
) -> tuple[PaperOrderService, PaperOrder, PaperAccount]:
    accounts = PaperAccountService(session)
    account = accounts.get_or_create(user_id=user_id)
    service = _service(session, now=now)
    order, _ = service.prepare_order(
        user_id=user_id,
        session_id="terminal-session",
        message_id=message_id or uuid.uuid4().hex,
        side="buy",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
        order_type="limit",
        limit_price=Decimal("1500"),
    )
    order = service.confirm(
        user_id=user_id,
        order_id=cast(uuid.UUID, order.id),
        draft=OrderDraft.model_validate(
            {
                "side": "buy",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "quantity": 100,
                "order_type": "limit",
                "limit_price": Decimal("1500"),
            }
        ),
        client_request_id=f"confirm-{message_id or order.id}",
    )
    return service, order, account


def _add_sellable_lot(
    session: Session, *, user_id: uuid.UUID, account: PaperAccount, quantity: int, days_ago: int
) -> PaperHoldingLot:
    executed_at = MORNING - timedelta(days=days_ago)
    source = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
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
        status=OrderStatus.FILLED,
        original_proposal={"seed": True},
        confirmed_payload={"seed": True},
        quote_snapshot={"seed": True},
        rules_version="seed",
        client_request_id=f"seed-{uuid.uuid4().hex}",
        expires_at=executed_at,
        confirmed_at=executed_at,
        completed_at=executed_at,
    )
    session.add(source)
    session.flush()
    fill = PaperFill(
        order_id=source.id,
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
        account_id=account.id,
        generation=account.generation,
        ts_code="600519.SH",
        name="贵州茅台",
        source_fill_id=fill.id,
        original_quantity=quantity,
        remaining_quantity=quantity,
        frozen_quantity=0,
        unit_cost=Decimal("100"),
        available_on=OPEN_DAY,
        created_at=executed_at,
    )
    session.add(lot)
    session.flush()
    return lot


def _confirmed_sell(
    session: Session, user_id: uuid.UUID
) -> tuple[PaperOrderService, PaperOrder, list[PaperHoldingLot]]:
    account = PaperAccountService(session).get_or_create(user_id=user_id)
    lots = [
        _add_sellable_lot(session, user_id=user_id, account=account, quantity=100, days_ago=2),
        _add_sellable_lot(session, user_id=user_id, account=account, quantity=100, days_ago=1),
    ]
    service = _service(session)
    order, _ = service.prepare_order(
        user_id=user_id,
        session_id="sell-session",
        message_id=uuid.uuid4().hex,
        side="sell",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=200,
        order_type="limit",
        limit_price=Decimal("1500"),
    )
    confirmed = service.confirm(
        user_id=user_id,
        order_id=cast(uuid.UUID, order.id),
        draft=OrderDraft.model_validate(
            {
                "side": "sell",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "quantity": 200,
                "order_type": "limit",
                "limit_price": Decimal("1500"),
            }
        ),
        client_request_id="confirm-sell",
    )
    return service, confirmed, lots


def test_cancel_releases_only_current_unfilled_reservation_and_preserves_fill_state(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, account = _confirmed_buy(db_session, user_id)
    # The settlement service continuously shrinks reserved_cash.  Model a
    # partially-filled order at that public boundary: cancellation must release
    # exactly this remaining reservation and never undo its fill summary.
    remaining = Decimal("75005.00")
    released_earlier = cast(Decimal, order.reserved_cash) - remaining
    account.frozen_cash = remaining
    account.available_cash = cast(Decimal, account.available_cash) + released_earlier
    order.filled_quantity = 50
    order.avg_fill_price = Decimal("1499.0000")
    order.reserved_cash = remaining
    order.status = OrderStatus.PARTIALLY_FILLED
    db_session.flush()
    available_before_cancel = cast(Decimal, account.available_cash)

    cancelled = service.cancel_confirmed(
        user_id=user_id,
        order_id=cast(uuid.UUID, order.id),
        confirmation_id="cancel-1",
    )

    assert cancelled.status is OrderStatus.CANCELLED
    assert cancelled.filled_quantity == 50
    assert cancelled.avg_fill_price == Decimal("1499.0000")
    assert cancelled.reserved_cash == Decimal("0.00")
    assert account.frozen_cash == Decimal("0.00")
    assert account.available_cash == available_before_cancel + remaining
    ledger = db_session.scalar(
        select(PaperCashLedger).where(PaperCashLedger.business_key == f"order-release:{order.id}")
    )
    assert ledger is not None
    assert ledger.amount == remaining
    assert ledger.order_id == order.id


def test_cancel_retry_is_idempotent_and_cross_user_is_hidden(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, account = _confirmed_buy(db_session, user_id)
    first = service.cancel_confirmed(
        user_id=user_id, order_id=cast(uuid.UUID, order.id), confirmation_id="cancel-once"
    )
    available = account.available_cash
    second = service.cancel_confirmed(
        user_id=user_id, order_id=cast(uuid.UUID, order.id), confirmation_id="cancel-once"
    )
    assert second.id == first.id
    assert account.available_cash == available
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaperCashLedger)
            .where(PaperCashLedger.business_key == f"order-release:{order.id}")
        )
        == 1
    )

    other = User(
        username=f"other-{uuid.uuid4().hex}",
        email=f"other-{uuid.uuid4().hex}@test",
        hashed_password="x",
    )
    db_session.add(other)
    db_session.flush()
    with pytest.raises(PaperTradingError) as hidden:
        service.cancel_confirmed(
            user_id=cast(uuid.UUID, other.id),
            order_id=cast(uuid.UUID, order.id),
            confirmation_id="cancel-once",
        )
    assert hidden.value.code == "paper_order_not_found"


def test_cancel_partially_filled_sell_releases_exact_remaining_lot_allocations(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, lots = _confirmed_sell(db_session, user_id)
    reservations = db_session.scalars(
        select(PaperLotReservation)
        .where(PaperLotReservation.order_id == order.id)
        .order_by(PaperLotReservation.created_at, PaperLotReservation.id)
    ).all()
    assert [row.remaining_quantity for row in reservations] == [100, 100]
    reservation_by_lot = {row.lot_id: row for row in reservations}
    # Model an 80-share FIFO settlement.  The already sold quantity stays out
    # of the lot; cancellation releases only the outstanding 20 + 100 shares.
    reservation_by_lot[lots[0].id].remaining_quantity = 20
    lots[0].remaining_quantity = 20
    lots[0].frozen_quantity = 20
    order.filled_quantity = 80
    order.avg_fill_price = Decimal("1500")
    order.reserved_quantity = 120
    order.status = OrderStatus.PARTIALLY_FILLED
    db_session.flush()

    service.cancel_confirmed(
        user_id=user_id, order_id=cast(uuid.UUID, order.id), confirmation_id="cancel-sell"
    )

    assert order.status is OrderStatus.CANCELLED
    assert order.filled_quantity == 80
    assert order.reserved_quantity == 0
    assert [row.remaining_quantity for row in reservations] == [0, 0]
    assert [lot.remaining_quantity for lot in lots] == [20, 100]
    assert [lot.frozen_quantity for lot in lots] == [0, 0]


def test_cancelled_order_is_idempotent_across_repeated_confirmations(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, _ = _confirmed_buy(db_session, user_id)
    service.cancel_confirmed(
        user_id=user_id, order_id=cast(uuid.UUID, order.id), confirmation_id="cancel-1"
    )
    repeated = service.cancel_confirmed(
        user_id=user_id,
        order_id=cast(uuid.UUID, order.id),
        confirmation_id="different-confirmation",
    )
    assert repeated.status is OrderStatus.CANCELLED


def test_expire_open_orders_releases_reservations_at_close_once(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, account = _confirmed_buy(db_session, user_id)
    frozen = account.frozen_cash
    assert service.expire_open_orders(at=CLOSE) == 1
    assert order.status is OrderStatus.EXPIRED
    assert order.completed_at == CLOSE
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert service.expire_open_orders(at=CLOSE) == 0
    assert (
        db_session.scalar(
            select(PaperCashLedger.amount).where(
                PaperCashLedger.business_key == f"order-release:{order.id}"
            )
        )
        == frozen
    )


@pytest.mark.parametrize(
    "recovery_time",
    [
        datetime(2026, 7, 21, 9, 30, tzinfo=SHANGHAI),
        datetime(2026, 7, 26, 12, 0, tzinfo=SHANGHAI),
    ],
)
def test_expiry_catches_up_overdue_orders_outside_close_window(
    db_session: Session, user: User, recovery_time: datetime
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, account = _confirmed_buy(db_session, user_id)

    assert service.expire_open_orders(at=recovery_time) == 1
    assert order.status is OrderStatus.EXPIRED
    assert order.completed_at == recovery_time
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert service.expire_open_orders(at=recovery_time) == 0


def test_expiry_processes_active_orders_without_rolling_back_for_archived_generation(
    db_session: Session, user: User
) -> None:
    stale_user_id = cast(uuid.UUID, user.id)
    service, stale_order, archived_account = _confirmed_buy(db_session, stale_user_id)
    stale_reserved = cast(Decimal, stale_order.reserved_cash)
    service.reset_account_confirmed(
        user_id=stale_user_id,
        initial_cash=Decimal("500000.00"),
        session_id="expire-stale-reset",
        confirmation_id="expire-stale-reset",
    )
    suffix = uuid.uuid4().hex
    active_user = User(
        username=f"active-expire-{suffix}",
        email=f"active-expire-{suffix}@test",
        hashed_password="x",
    )
    db_session.add(active_user)
    db_session.flush()
    _, active_order, active_account = _confirmed_buy(db_session, cast(uuid.UUID, active_user.id))

    recovery = datetime(2026, 7, 21, 9, 30, tzinfo=SHANGHAI)
    assert service.expire_open_orders(at=recovery) == 2
    assert active_order.status is OrderStatus.EXPIRED
    assert active_account.frozen_cash == Decimal("0.00")
    assert stale_order.status is OrderStatus.EXPIRED
    assert archived_account.status is PaperAccountStatus.ARCHIVED
    assert archived_account.frozen_cash == Decimal("0.00")
    assert archived_account.available_cash == Decimal("1000000.00")
    assert (
        db_session.scalar(
            select(PaperCashLedger.amount).where(
                PaperCashLedger.business_key == f"order-release:{stale_order.id}"
            )
        )
        == stale_reserved
    )


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (datetime(2026, 7, 20, 14, 59, tzinfo=SHANGHAI), 0),
        (datetime(2026, 7, 19, 15, 1, tzinfo=SHANGHAI), 0),
    ],
)
def test_expiry_does_nothing_before_close_or_on_non_trading_day(
    db_session: Session, user: User, at: datetime, expected: int
) -> None:
    service, order, _ = _confirmed_buy(db_session, cast(uuid.UUID, user.id))
    assert service.expire_open_orders(at=at) == expected
    assert order.status is OrderStatus.OPEN


def test_open_queued_orders_only_during_continuous_session(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    auction = datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)
    service, order, _ = _confirmed_buy(db_session, user_id, now=auction)
    assert order.status is OrderStatus.QUEUED
    assert service.open_queued_orders(at=auction) == 0
    assert service.open_queued_orders(at=datetime(2026, 7, 20, 9, 30, tzinfo=SHANGHAI)) == 1
    assert order.status is OrderStatus.OPEN
    assert service.open_queued_orders(at=datetime(2026, 7, 20, 13, 0, tzinfo=SHANGHAI)) == 0


def test_open_queued_orders_skips_archived_generation(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    auction = datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)
    service, order, account = _confirmed_buy(db_session, user_id, now=auction)
    account.status = PaperAccountStatus.ARCHIVED
    db_session.flush()
    assert service.open_queued_orders(at=MORNING) == 0
    assert order.status is OrderStatus.QUEUED


def test_open_queued_orders_rechecks_account_after_concurrent_reset(
    pg_test_engine: Engine,
) -> None:
    session_factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    auction = datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)
    with session_factory() as setup:
        suffix = uuid.uuid4().hex
        user = User(
            username=f"open-reset-{suffix}",
            email=f"open-reset-{suffix}@test",
            hashed_password="x",
        )
        setup.add(user)
        setup.flush()
        user_id = cast(uuid.UUID, user.id)
        service, order, _ = _confirmed_buy(setup, user_id, now=auction)
        order_id = cast(uuid.UUID, order.id)
        setup.commit()

    candidate_locked = Event()
    allow_write = Event()
    result: list[int] = []
    failures: list[BaseException] = []

    def pause_after_candidates(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            "FROM paper_orders JOIN paper_accounts" in statement
            and "paper_orders.status =" in statement
            and "FOR UPDATE OF paper_orders SKIP LOCKED" in statement
        ):
            candidate_locked.set()
            if not allow_write.wait(timeout=10):
                raise TimeoutError("reset did not release queued-order worker")

    def run_open() -> None:
        try:
            with session_factory() as worker:
                result.append(
                    _service(worker, now=auction).open_queued_orders(
                        at=datetime(2026, 7, 20, 9, 30, tzinfo=SHANGHAI)
                    )
                )
                worker.commit()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    event.listen(pg_test_engine, "after_cursor_execute", pause_after_candidates)
    thread = Thread(target=run_open, daemon=True)
    try:
        thread.start()
        assert candidate_locked.wait(timeout=10)
        with session_factory() as resetter:
            PaperAccountService(resetter).reset_confirmed(
                user_id=user_id,
                initial_cash=Decimal("500000.00"),
                source_session_id="concurrent-reset",
                confirmation_id="concurrent-reset",
            )
            resetter.commit()
        allow_write.set()
        thread.join(timeout=10)
    finally:
        allow_write.set()
        event.remove(pg_test_engine, "after_cursor_execute", pause_after_candidates)
    assert not thread.is_alive()
    assert failures == []
    assert result == [0]
    with session_factory() as verify:
        persisted = verify.get(PaperOrder, order_id)
        assert persisted is not None
        assert persisted.status is OrderStatus.QUEUED


def test_open_queued_orders_never_reopens_a_stale_prior_day_order(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    auction = datetime(2026, 7, 20, 9, 20, tzinfo=SHANGHAI)
    service, order, _ = _confirmed_buy(db_session, user_id, now=auction)
    assert service.open_queued_orders(at=datetime(2026, 7, 21, 9, 30, tzinfo=SHANGHAI)) == 0
    assert order.status is OrderStatus.QUEUED


def test_reset_rejects_processing_match_pass_atomically(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, account = _confirmed_buy(db_session, user_id)
    db_session.add(
        PaperMatchPass(
            order_id=order.id,
            quote_timestamp=MORNING,
            match_pass=1,
            quote_source="fixed",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=1,
            fill_id=None,
        )
    )
    db_session.flush()
    with pytest.raises(PaperTradingError) as processing:
        service.reset_account_confirmed(
            user_id=user_id,
            initial_cash=Decimal("500000.00"),
            session_id="reset-session",
            confirmation_id="reset-1",
        )
    assert processing.value.code == "match_in_progress"
    assert account.status is PaperAccountStatus.ACTIVE
    assert service.account_service.get_active(user_id=user_id).id == account.id


def test_reset_is_generation_safe_and_idempotent(db_session: Session, user: User) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, order, old = _confirmed_buy(db_session, user_id)
    first = service.reset_account_confirmed(
        user_id=user_id,
        initial_cash=Decimal("500000.00"),
        session_id="reset-session",
        confirmation_id="reset-1",
    )
    second = service.reset_account_confirmed(
        user_id=user_id,
        initial_cash=Decimal("500000.00"),
        session_id="reset-session",
        confirmation_id="reset-1",
    )
    assert first.id == second.id
    assert first.generation == 2
    assert first.available_cash == Decimal("500000.00")
    assert old.status is PaperAccountStatus.ARCHIVED
    assert order.account_generation == 1
    assert order.status is OrderStatus.OPEN


def test_reset_retry_returns_original_account_even_when_new_generation_is_matching(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, _, _ = _confirmed_buy(db_session, user_id)
    first = service.reset_account_confirmed(
        user_id=user_id,
        initial_cash=Decimal("500000.00"),
        session_id="reset-replay-session",
        confirmation_id="reset-replay",
    )
    _, new_order, _ = _confirmed_buy(db_session, user_id, message_id="new-generation-order")
    db_session.add(
        PaperMatchPass(
            order_id=new_order.id,
            quote_timestamp=MORNING,
            match_pass=1,
            quote_source="fixed",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=1,
            fill_id=None,
        )
    )
    db_session.flush()

    replay = service.reset_account_confirmed(
        user_id=user_id,
        initial_cash=Decimal("500000.00"),
        session_id="reset-replay-session",
        confirmation_id="reset-replay",
    )

    assert replay.id == first.id
    assert replay.generation == 2
    assert service.account_service.get_active(user_id=user_id).id == first.id


def test_reset_conflict_precedes_new_generation_processing_guard(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    service, _, _ = _confirmed_buy(db_session, user_id)
    service.reset_account_confirmed(
        user_id=user_id,
        initial_cash=Decimal("500000.00"),
        session_id="reset-conflict-session",
        confirmation_id="reset-conflict",
    )
    _, new_order, _ = _confirmed_buy(db_session, user_id, message_id="conflict-new-order")
    db_session.add(
        PaperMatchPass(
            order_id=new_order.id,
            quote_timestamp=MORNING,
            match_pass=1,
            quote_source="fixed",
            snapshot_summary={},
            consumed_levels=[],
            matched_quantity=1,
            fill_id=None,
        )
    )
    db_session.flush()

    with pytest.raises(PaperTradingError) as conflict:
        service.reset_account_confirmed(
            user_id=user_id,
            initial_cash=Decimal("600000.00"),
            session_id="reset-conflict-session",
            confirmation_id="reset-conflict",
        )

    assert conflict.value.code == "reset_confirmation_conflict"
    assert service.account_service.get_active(user_id=user_id).generation == 2


def test_terminal_actions_reject_naive_timestamps_and_invalid_ids(
    db_session: Session, user: User
) -> None:
    service = _service(db_session)
    with pytest.raises(PaperTradingError) as naive:
        service.expire_open_orders(at=datetime(2026, 7, 20, 15, 1))
    assert naive.value.code == "invalid_order_time"
    with pytest.raises(PaperTradingError) as bad_id:
        service.cancel_confirmed(
            user_id=cast(uuid.UUID, user.id),
            order_id=cast(uuid.UUID, "bad"),
            confirmation_id="cancel",
        )
    assert bad_id.value.code == "invalid_order"
