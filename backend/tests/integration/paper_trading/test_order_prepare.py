from __future__ import annotations

import threading
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from app.models.paper_account import PaperAccount, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import OrderStatus, PaperFill, PaperOrder
from app.models.user import User
from app.schemas.paper_trading import OrderDraft
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 20, 10, 0, 5, tzinfo=SHANGHAI)


class FixedQuoteProvider:
    def __init__(self, quote: RealtimeQuote) -> None:
        self.quote = quote
        self.calls: list[str] = []

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        self.calls.append(ts_code)
        return self.quote


def _quote(
    *,
    ts_code: str = "600519.SH",
    name: str = "贵州茅台",
    quoted_at: datetime = NOW,
    previous_close: Decimal = Decimal("1500"),
    last_price: Decimal = Decimal("1501"),
    bid_quantity: int = 1000,
    ask_quantity: int = 1000,
    suspended: bool = False,
    price_step: Decimal = Decimal("1"),
) -> RealtimeQuote:
    return RealtimeQuote(
        ts_code=ts_code,
        name=name,
        quoted_at=quoted_at,
        previous_close=previous_close,
        last_price=last_price,
        bids=tuple(
            QuoteLevel(price=last_price - price_step * level, quantity=bid_quantity)
            for level in range(1, 6)
        ),
        asks=tuple(
            QuoteLevel(price=last_price + price_step * level, quantity=ask_quantity)
            for level in range(1, 6)
        ),
        source="fixed",
        suspended=suspended,
    )


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-prepare-{suffix}",
        email=f"paper-prepare-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def quote_provider() -> FixedQuoteProvider:
    return FixedQuoteProvider(_quote())


@pytest.fixture
def clock() -> TradingClock:
    return TradingClock(FixedTradingCalendar({NOW.date(), date(2026, 7, 21)}))


def _service(
    session: Session,
    provider: FixedQuoteProvider,
    clock: TradingClock,
    *,
    now: datetime = NOW,
):
    from app.services.paper_trading.order_service import PaperOrderService

    return PaperOrderService(
        session,
        quote_provider=provider,
        clock=clock,
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: now,
    )


def _prepare(
    service: object,
    user_id: uuid.UUID,
    **changes: object,
) -> tuple[PaperOrder, object]:
    values: dict[str, object] = {
        "user_id": user_id,
        "session_id": "session-1",
        "message_id": "message-1",
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": Decimal("1500"),
    }
    values.update(changes)
    return service.prepare_order(**values)  # type: ignore[attr-defined, no-any-return]


def test_prepare_order_only_persists_proposal_without_account_mutation(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    account_service = PaperAccountService(db_session)
    account = account_service.get_or_create(user_id=cast(uuid.UUID, user.id))
    before = (
        account.available_cash,
        account.frozen_cash,
        db_session.query(PaperCashLedger).count(),
    )

    order, preview = _prepare(_service(db_session, quote_provider, clock), cast(uuid.UUID, user.id))

    assert order.status is OrderStatus.AWAITING_CONFIRMATION
    assert order.client_request_id is None
    assert order.confirmed_payload is None
    assert (account.available_cash, account.frozen_cash) == before[:2]
    assert db_session.query(PaperCashLedger).count() == before[2]
    assert preview.estimated_gross == Decimal("150000.00")
    assert preview.estimated_cash_required == Decimal("150046.50")
    assert preview.available_cash == Decimal("1000000.00")
    assert preview.quote.name == "贵州茅台"
    assert order.quote_snapshot["ts_code"] == "600519.SH"
    assert "cn-a-fees-2023-08-28-v1" in order.rules_version
    assert order.expires_at.tzinfo is not None


def test_prepare_retry_returns_same_proposal_but_same_message_can_hold_distinct_drafts(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    service = _service(db_session, quote_provider, clock)

    first, _ = _prepare(service, cast(uuid.UUID, user.id))
    retried, preview = _prepare(service, cast(uuid.UUID, user.id))
    changed, _ = _prepare(service, cast(uuid.UUID, user.id), quantity=200)

    assert retried.id == first.id == preview.order_id
    assert changed.id != first.id
    assert db_session.query(PaperOrder).count() == 2
    assert first.proposal_fingerprint == retried.proposal_fingerprint
    assert first.proposal_fingerprint != changed.proposal_fingerprint


def test_prepare_retry_fails_closed_when_fingerprint_payload_does_not_match(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    service = _service(db_session, quote_provider, clock)
    order, _ = _prepare(service, cast(uuid.UUID, user.id))
    order.original_proposal = {**order.original_proposal, "quantity": 200}
    db_session.flush()

    with pytest.raises(PaperTradingError) as caught:
        _prepare(service, cast(uuid.UUID, user.id))
    assert caught.value.code == "proposal_idempotency_conflict"


@pytest.mark.parametrize("quantity", [True, 100.0, "100"])
def test_prepare_rejects_non_integer_quantity_without_fetching_quote(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
    quantity: object,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            _service(db_session, quote_provider, clock),
            cast(uuid.UUID, user.id),
            quantity=quantity,
        )
    assert caught.value.code == "invalid_order"
    assert quote_provider.calls == []


def test_preview_reloads_authoritative_state_and_does_not_persist_edits(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    service = _service(db_session, quote_provider, clock)
    order, _ = _prepare(service, cast(uuid.UUID, user.id))
    db_session.flush()
    before_count = db_session.query(PaperOrder).count()
    quote_provider.quote = _quote(last_price=Decimal("1499"))
    edited = OrderDraft(
        side="buy",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=200,
        order_type="limit",
        limit_price=Decimal("1490"),
    )

    preview = service.preview(
        user_id=cast(uuid.UUID, user.id), order_id=cast(uuid.UUID, order.id), draft=edited
    )

    assert preview.estimated_gross == Decimal("298000.00")
    assert preview.draft.quantity == 200
    assert quote_provider.calls == ["600519.SH", "600519.SH"]
    assert db_session.query(PaperOrder).count() == before_count
    db_session.refresh(order)
    assert order.quantity == 100
    assert order.limit_price == Decimal("1500.0000")


def test_buy_rejects_insufficient_cash_without_freezing(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    account = PaperAccountService(db_session).get_or_create(
        user_id=cast(uuid.UUID, user.id), initial_cash=Decimal("10000")
    )

    with pytest.raises(PaperTradingError) as caught:
        _prepare(_service(db_session, quote_provider, clock), cast(uuid.UUID, user.id))

    assert caught.value.code == "insufficient_cash"
    assert account.available_cash == Decimal("10000.00")
    assert account.frozen_cash == Decimal("0.00")
    assert db_session.query(PaperOrder).count() == 0


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"quantity": 101}, "invalid_lot_size"),
        ({"order_type": "market", "limit_price": Decimal("1500")}, "invalid_order"),
        ({"order_type": "limit", "limit_price": None}, "invalid_order"),
        ({"limit_price": Decimal("1500.001")}, "invalid_price_tick"),
        ({"limit_price": Decimal("1700")}, "price_out_of_bounds"),
        ({"name": "错误名称"}, "security_identity_mismatch"),
    ],
)
def test_prepare_validates_lot_order_price_and_authoritative_identity(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
    changes: dict[str, object],
    code: str,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            _service(db_session, quote_provider, clock),
            cast(uuid.UUID, user.id),
            **changes,
        )
    assert caught.value.code == code
    assert db_session.query(PaperOrder).count() == 0


@pytest.mark.parametrize(
    ("ts_code", "name", "previous_close", "valid", "invalid"),
    [
        ("688001.SH", "华兴源创", Decimal("100"), Decimal("120"), Decimal("120.01")),
        ("300001.SZ", "特锐德", Decimal("100"), Decimal("120"), Decimal("120.01")),
        ("600519.SH", "ST贵州", Decimal("100"), Decimal("105"), Decimal("105.01")),
    ],
)
def test_prepare_resolves_board_and_risk_warning_price_bounds(
    db_session: Session,
    user: User,
    clock: TradingClock,
    ts_code: str,
    name: str,
    previous_close: Decimal,
    valid: Decimal,
    invalid: Decimal,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    provider = FixedQuoteProvider(
        _quote(ts_code=ts_code, name=name, previous_close=previous_close, last_price=previous_close)
    )
    service = _service(db_session, provider, clock)
    order, _ = _prepare(
        service, cast(uuid.UUID, user.id), ts_code=ts_code, name=name, limit_price=valid
    )
    assert order.id is not None
    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            service,
            cast(uuid.UUID, user.id),
            ts_code=ts_code,
            name=name,
            limit_price=invalid,
            message_id="message-2",
        )
    assert caught.value.code == "price_out_of_bounds"


def test_market_preview_uses_visible_depth_and_fails_closed_when_insufficient(
    db_session: Session,
    user: User,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    provider = FixedQuoteProvider(_quote(ask_quantity=100))
    service = _service(db_session, provider, clock)
    _, preview = _prepare(
        service,
        cast(uuid.UUID, user.id),
        order_type="market",
        limit_price=None,
        quantity=500,
    )
    assert preview.estimated_gross == Decimal("752000.00")

    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            service,
            cast(uuid.UUID, user.id),
            order_type="market",
            limit_price=None,
            quantity=600,
            message_id="message-2",
        )
    assert caught.value.code == "insufficient_market_depth"


@pytest.mark.parametrize(
    ("provider", "now", "code"),
    [
        (
            FixedQuoteProvider(_quote(quoted_at=datetime(2026, 7, 20, 9, 59, tzinfo=SHANGHAI))),
            NOW,
            "stale_quote",
        ),
        (FixedQuoteProvider(_quote(suspended=True)), NOW, "suspended_security"),
    ],
)
def test_prepare_fails_closed_for_stale_or_suspended_quotes(
    db_session: Session,
    user: User,
    clock: TradingClock,
    provider: FixedQuoteProvider,
    now: datetime,
    code: str,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    with pytest.raises(PaperTradingError) as caught:
        _prepare(_service(db_session, provider, clock, now=now), cast(uuid.UUID, user.id))
    assert caught.value.code == code


def test_prepare_fails_closed_for_malformed_crossed_five_level_book(
    db_session: Session,
    user: User,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    quote = _quote().model_copy(
        update={
            "bids": tuple(
                QuoteLevel(price=Decimal("1600") - level, quantity=100) for level in range(5)
            )
        }
    )
    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            _service(db_session, FixedQuoteProvider(quote), clock),
            cast(uuid.UUID, user.id),
        )
    assert caught.value.code == "quote_unavailable"


def test_limit_preview_ignores_malformed_zero_quantity_tail_levels(
    db_session: Session,
    user: User,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    quote = _quote().model_copy(
        update={
            "bids": (
                QuoteLevel(price=Decimal("1500"), quantity=100),
                QuoteLevel(price=Decimal("1499"), quantity=100),
                QuoteLevel(price=Decimal("9999.001"), quantity=0),
                QuoteLevel(price=Decimal("9999.001"), quantity=0),
                QuoteLevel(price=Decimal("1.001"), quantity=0),
            ),
            "asks": (
                QuoteLevel(price=Decimal("1502"), quantity=100),
                QuoteLevel(price=Decimal("1503"), quantity=100),
                QuoteLevel(price=Decimal("1.001"), quantity=0),
                QuoteLevel(price=Decimal("1.001"), quantity=0),
                QuoteLevel(price=Decimal("9999.001"), quantity=0),
            ),
        }
    )

    order, preview = _prepare(
        _service(db_session, FixedQuoteProvider(quote), clock),
        cast(uuid.UUID, user.id),
    )

    assert order.status is OrderStatus.AWAITING_CONFIRMATION
    assert preview.estimated_gross == Decimal("150000.00")


def test_market_preview_with_empty_executable_side_reports_insufficient_depth(
    db_session: Session,
    user: User,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    quote = _quote().model_copy(
        update={"asks": tuple(QuoteLevel(price=Decimal("9999.001"), quantity=0) for _ in range(5))}
    )

    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            _service(db_session, FixedQuoteProvider(quote), clock),
            cast(uuid.UUID, user.id),
            order_type="market",
            limit_price=None,
        )
    assert caught.value.code == "insufficient_market_depth"


def test_prepare_rejects_crossed_executable_levels_even_with_zero_quantity_tails(
    db_session: Session,
    user: User,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    quote = _quote().model_copy(
        update={
            "bids": (
                QuoteLevel(price=Decimal("1503"), quantity=100),
                *(QuoteLevel(price=Decimal("1.001"), quantity=0) for _ in range(4)),
            ),
            "asks": (
                QuoteLevel(price=Decimal("1502"), quantity=100),
                *(QuoteLevel(price=Decimal("9999.001"), quantity=0) for _ in range(4)),
            ),
        }
    )

    with pytest.raises(PaperTradingError) as caught:
        _prepare(_service(db_session, FixedQuoteProvider(quote), clock), cast(uuid.UUID, user.id))
    assert caught.value.code == "quote_unavailable"


@pytest.mark.parametrize(
    "quote",
    [
        _quote().model_copy(
            update={
                "asks": (
                    QuoteLevel(price=Decimal("1502.001"), quantity=1000),
                    *_quote().asks[1:],
                )
            }
        ),
        _quote().model_copy(
            update={
                "asks": tuple(
                    QuoteLevel(price=Decimal("1651") + level, quantity=1000) for level in range(5)
                )
            }
        ),
    ],
    ids=["off tick", "outside daily bounds"],
)
def test_prepare_rejects_non_executable_quote_levels(
    db_session: Session,
    user: User,
    clock: TradingClock,
    quote: RealtimeQuote,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    with pytest.raises(PaperTradingError) as caught:
        _prepare(_service(db_session, FixedQuoteProvider(quote), clock), cast(uuid.UUID, user.id))
    assert caught.value.code == "quote_unavailable"


def _add_sellable_lot(
    session: Session,
    *,
    user: User,
    quantity: int,
    available_on: date,
    ts_code: str = "600519.SH",
    name: str = "贵州茅台",
    unit_cost: Decimal = Decimal("1400"),
) -> None:
    account = PaperAccountService(session).get_active(user_id=cast(uuid.UUID, user.id))
    business_suffix = uuid.uuid4().hex
    filled = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"historical-buy-{business_suffix}",
        source_session_id="historical-session",
        source_message_id=f"historical-{business_suffix}"[:64],
        proposal_fingerprint=business_suffix * 2,
        ts_code=ts_code,
        name=name,
        side="buy",
        order_type="limit",
        quantity=quantity,
        limit_price=unit_cost,
        filled_quantity=quantity,
        avg_fill_price=unit_cost,
        status="filled",
        original_proposal={"historical": True},
        confirmed_payload={"historical": True},
        user_edits={},
        quote_snapshot={"historical": True},
        rules_version="historical",
        expires_at=NOW,
        confirmed_at=NOW,
        completed_at=NOW,
    )
    session.add(filled)
    session.flush()
    fill = PaperFill(
        order_id=filled.id,
        fill_seq=1,
        quantity=quantity,
        price=unit_cost,
        gross_amount=unit_cost * quantity,
        commission=Decimal("5"),
        stamp_duty=Decimal("0"),
        transfer_fee=Decimal("1.4"),
        quote_timestamp=NOW,
        quote_source="fixed",
        executed_at=NOW,
        trade_id=uuid.uuid4(),
    )
    session.add(fill)
    session.flush()
    session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code=ts_code,
            name=name,
            source_fill_id=fill.id,
            original_quantity=quantity,
            remaining_quantity=quantity,
            frozen_quantity=0,
            unit_cost=unit_cost,
            available_on=available_on,
        )
    )
    session.flush()


def test_sell_preview_reports_only_t_plus_one_sellable_lots(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    _add_sellable_lot(db_session, user=user, quantity=200, available_on=date(2026, 7, 17))
    _add_sellable_lot(db_session, user=user, quantity=100, available_on=NOW.date())
    _add_sellable_lot(db_session, user=user, quantity=300, available_on=date(2026, 7, 21))
    service = _service(db_session, quote_provider, clock)

    _, preview = _prepare(
        service,
        cast(uuid.UUID, user.id),
        side="sell",
        quantity=300,
        limit_price=Decimal("1500"),
    )
    assert preview.sellable_quantity == 300
    assert preview.estimated_cash_required == Decimal("0.00")

    with pytest.raises(PaperTradingError) as caught:
        _prepare(
            service,
            cast(uuid.UUID, user.id),
            side="sell",
            quantity=400,
            limit_price=Decimal("1500"),
            message_id="message-2",
        )
    assert caught.value.code == "insufficient_sellable_quantity"


def test_preview_can_edit_buy_into_another_security_sell_and_normalizes_name(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    _add_sellable_lot(
        db_session,
        user=user,
        quantity=200,
        available_on=date(2026, 7, 17),
        ts_code="000001.SZ",
        name="平安银行",
        unit_cost=Decimal("10"),
    )
    service = _service(db_session, quote_provider, clock)
    order, _ = _prepare(service, cast(uuid.UUID, user.id))
    before = (
        db_session.query(PaperOrder).count(),
        db_session.query(PaperCashLedger).count(),
        order.side,
        order.ts_code,
        order.name,
        order.quantity,
        order.original_proposal,
        order.quote_snapshot,
        order.rules_version,
    )
    quote_provider.quote = _quote(
        ts_code="000001.SZ",
        name="平安银行",
        previous_close=Decimal("10"),
        last_price=Decimal("10"),
        price_step=Decimal("0.1"),
    )
    edited = OrderDraft(
        side="sell",
        ts_code="000001.SZ",
        name="模型传入的旧名称",
        quantity=200,
        order_type="limit",
        limit_price=Decimal("10"),
    )

    preview = service.preview(
        user_id=cast(uuid.UUID, user.id),
        order_id=cast(uuid.UUID, order.id),
        draft=edited,
    )

    assert preview.draft.side.value == "sell"
    assert preview.draft.ts_code == "000001.SZ"
    assert preview.draft.name == "平安银行"
    assert preview.quote.name == "平安银行"
    assert preview.sellable_quantity == 200
    assert preview.estimated_gross == Decimal("2000.00")
    assert preview.estimated_cash_required == Decimal("0.00")
    db_session.refresh(order)
    assert (
        db_session.query(PaperOrder).count(),
        db_session.query(PaperCashLedger).count(),
        order.side,
        order.ts_code,
        order.name,
        order.quantity,
        order.original_proposal,
        order.quote_snapshot,
        order.rules_version,
    ) == before


def test_preview_can_edit_sell_into_another_security_buy_without_activity(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    _add_sellable_lot(
        db_session,
        user=user,
        quantity=100,
        available_on=date(2026, 7, 17),
    )
    service = _service(db_session, quote_provider, clock)
    order, _ = _prepare(
        service,
        cast(uuid.UUID, user.id),
        side="sell",
        quantity=100,
    )
    before = (
        account.available_cash,
        account.frozen_cash,
        db_session.query(PaperOrder).count(),
        db_session.query(PaperCashLedger).count(),
    )
    quote_provider.quote = _quote(
        ts_code="000001.SZ",
        name="平安银行",
        previous_close=Decimal("10"),
        last_price=Decimal("10"),
        price_step=Decimal("0.1"),
    )
    edited = OrderDraft(
        side="buy",
        ts_code="000001.SZ",
        name="错误名称",
        quantity=100,
        order_type="limit",
        limit_price=Decimal("10"),
    )

    preview = service.preview(
        user_id=cast(uuid.UUID, user.id),
        order_id=cast(uuid.UUID, order.id),
        draft=edited,
    )

    assert preview.draft.side.value == "buy"
    assert preview.draft.name == "平安银行"
    assert preview.sellable_quantity == 0
    assert preview.estimated_gross == Decimal("1000.00")
    assert preview.estimated_cash_required == Decimal("1005.01")
    db_session.refresh(order)
    assert (
        account.available_cash,
        account.frozen_cash,
        db_session.query(PaperOrder).count(),
        db_session.query(PaperCashLedger).count(),
    ) == before
    assert order.side.value == "sell"
    assert order.ts_code == "600519.SH"


def test_preview_rejects_foreign_order_without_disclosing_it(
    db_session: Session,
    user: User,
    quote_provider: FixedQuoteProvider,
    clock: TradingClock,
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    service = _service(db_session, quote_provider, clock)
    order, _ = _prepare(service, cast(uuid.UUID, user.id))
    other = User(
        username=f"paper-other-{uuid.uuid4().hex}",
        email=f"paper-other-{uuid.uuid4().hex}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.flush()
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, other.id))
    draft = OrderDraft.model_validate(order.original_proposal)

    with pytest.raises(PaperTradingError) as caught:
        service.preview(
            user_id=cast(uuid.UUID, other.id),
            order_id=cast(uuid.UUID, order.id),
            draft=draft,
        )
    assert caught.value.code == "paper_order_not_found"


def _committed_account(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    with Session(engine) as session:
        suffix = uuid.uuid4().hex
        user = User(
            username=f"prepare-race-{suffix}",
            email=f"prepare-race-{suffix}@example.test",
            hashed_password="not-used",
        )
        session.add(user)
        session.flush()
        user_id = cast(uuid.UUID, user.id)
        account = PaperAccountService(session).get_or_create(user_id=user_id)
        account_id = cast(uuid.UUID, account.id)
        session.commit()
    return user_id, account_id


def test_slow_quote_fetch_does_not_lock_account_and_prepare_revalidates_after_fetch(
    pg_test_engine: Engine,
    clock: TradingClock,
) -> None:
    user_id, account_id = _committed_account(pg_test_engine)
    quote_started = threading.Event()
    allow_quote = threading.Event()
    edit_finished = threading.Event()
    outcomes: list[tuple[str, Decimal]] = []
    errors: list[BaseException] = []

    class BlockingProvider(FixedQuoteProvider):
        def get_sync(self, ts_code: str) -> RealtimeQuote:
            quote_started.set()
            if not allow_quote.wait(timeout=5):
                raise TimeoutError("quote release timed out")
            return super().get_sync(ts_code)

    def prepare() -> None:
        try:
            with Session(pg_test_engine) as session:
                _, preview = _prepare(_service(session, BlockingProvider(_quote()), clock), user_id)
                session.commit()
                outcomes.append(("prepared", preview.available_cash))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def edit() -> None:
        try:
            with Session(pg_test_engine) as session:
                account = PaperAccountService(session).edit_initial_cash_once(
                    user_id=user_id, initial_cash=Decimal("800000")
                )
                session.commit()
                outcomes.append(("edited", cast(Decimal, account.initial_cash)))
                edit_finished.set()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    prepare_thread = threading.Thread(target=prepare)
    edit_thread = threading.Thread(target=edit)
    prepare_thread.start()
    assert quote_started.wait(timeout=5)
    edit_thread.start()
    assert edit_finished.wait(timeout=5), "account edit was blocked by slow quote fetch"
    allow_quote.set()
    prepare_thread.join(timeout=10)
    edit_thread.join(timeout=10)

    assert errors == []
    assert sorted(outcomes) == [
        ("edited", Decimal("800000.00")),
        ("prepared", Decimal("800000.00")),
    ]
    with Session(pg_test_engine) as observer:
        account = observer.get(PaperAccount, account_id)
        assert account is not None
        assert account.initial_cash == Decimal("800000.00")
        assert (
            observer.scalar(
                select(func.count())
                .select_from(PaperOrder)
                .where(PaperOrder.account_id == account_id)
            )
            == 1
        )


def test_initial_cash_edit_then_prepare_reads_the_serialized_new_balance(
    pg_test_engine: Engine,
    clock: TradingClock,
) -> None:
    user_id, account_id = _committed_account(pg_test_engine)
    edit_holds_lock = threading.Event()
    allow_edit_commit = threading.Event()
    prepare_started = threading.Event()
    outcomes: list[tuple[str, Decimal]] = []
    errors: list[BaseException] = []

    def edit() -> None:
        try:
            with Session(pg_test_engine) as session:
                account = PaperAccountService(session).edit_initial_cash_once(
                    user_id=user_id, initial_cash=Decimal("800000")
                )
                edit_holds_lock.set()
                if not allow_edit_commit.wait(timeout=5):
                    raise TimeoutError("edit commit release timed out")
                session.commit()
                outcomes.append(("edited", cast(Decimal, account.initial_cash)))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def prepare() -> None:
        try:
            with Session(pg_test_engine) as session:
                prepare_started.set()
                _, preview = _prepare(
                    _service(session, FixedQuoteProvider(_quote()), clock), user_id
                )
                session.commit()
                outcomes.append(("prepared", preview.available_cash))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    edit_thread = threading.Thread(target=edit)
    prepare_thread = threading.Thread(target=prepare)
    edit_thread.start()
    assert edit_holds_lock.wait(timeout=5)
    prepare_thread.start()
    assert prepare_started.wait(timeout=5)
    allow_edit_commit.set()
    edit_thread.join(timeout=10)
    prepare_thread.join(timeout=10)

    assert errors == []
    assert sorted(outcomes) == [
        ("edited", Decimal("800000.00")),
        ("prepared", Decimal("800000.00")),
    ]
    with Session(pg_test_engine) as observer:
        account = PaperAccountService(observer).get_active(user_id=user_id)
        assert account.id == account_id
        assert account.initial_cash == Decimal("800000.00")
        assert (
            observer.scalar(
                select(func.count())
                .select_from(PaperOrder)
                .where(PaperOrder.account_id == account_id)
            )
            == 1
        )


def test_concurrent_prepare_retry_creates_one_proposal(
    pg_test_engine: Engine,
    clock: TradingClock,
) -> None:
    user_id, account_id = _committed_account(pg_test_engine)
    start = threading.Barrier(2)
    order_ids: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def prepare() -> None:
        try:
            with Session(pg_test_engine) as session:
                start.wait(timeout=5)
                order, _ = _prepare(_service(session, FixedQuoteProvider(_quote()), clock), user_id)
                order_ids.append(cast(uuid.UUID, order.id))
                session.commit()
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=prepare) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(order_ids) == 2
    assert order_ids[0] == order_ids[1]
    with Session(pg_test_engine) as observer:
        assert (
            observer.scalar(
                select(func.count())
                .select_from(PaperOrder)
                .where(PaperOrder.account_id == account_id)
            )
            == 1
        )


def test_sync_service_uses_provider_without_nested_event_loop_adapter() -> None:
    provider = TushareRealtimeQuoteProvider(fetch=lambda _: pytest.fail("not called"))
    assert callable(provider.get_sync)
