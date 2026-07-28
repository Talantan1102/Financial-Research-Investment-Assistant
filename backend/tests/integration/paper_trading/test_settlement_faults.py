# mypy: disable-error-code="arg-type,unused-ignore"

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from app.models.investor_suitability import (
    EntitlementStatus,
    Market,
    MarketAccessRule,
    MarketEntitlement,
)
from app.models.paper_account import PaperAccount, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import (
    OrderStatus,
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar
from app.services.paper_trading.matcher import Execution
from app.services.paper_trading.settlement import PaperSettlementService
from app.services.trade_service import TradeService
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.paper_trading.test_account_properties import (
    NOW,
    _buy_order,
    _evidence,
    _user_account,
)
from tests.integration.paper_trading.test_order_confirm import (
    FixedQuoteProvider,
    _draft,
    _prepare,
    _quote,
)
from tests.integration.paper_trading.test_order_confirm import (
    _service as _order_service,
)


def _counts(session: Session) -> tuple[int, int, int, int, int, int]:
    return tuple(
        int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (PaperFill, PaperMatchPass, Trade, Position, PaperHoldingLot, PaperCashLedger)
    )  # type: ignore[return-value]


def _service(
    session: Session, execution: Execution, *, trade_service: TradeService | None = None
) -> PaperSettlementService:
    evidence = _evidence(execution, execution.quantity)
    return PaperSettlementService(
        session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: evidence,
        trade_service=trade_service,
    )


def _enable_main(session: Session, account: PaperAccount) -> None:
    rule = session.scalar(
        select(MarketAccessRule).where(
            MarketAccessRule.market == Market.MAIN,
            MarketAccessRule.rule_version == "test-main-v1",
        )
    )
    if rule is None:
        rule = MarketAccessRule(
            market=Market.MAIN,
            effective_from=NOW.date(),
            minimum_average_assets_20d=None,
            minimum_experience_months=None,
            required_disclosure_version="main-risk-v1",
            rule_version="test-main-v1",
        )
        session.add(rule)
        session.flush()
    session.add(
        MarketEntitlement(
            account_id=account.id,
            account_generation=account.generation,
            market=Market.MAIN,
            status=EntitlementStatus.ENABLED,
            can_buy=True,
            can_sell=True,
            can_subscribe=False,
            rule_version=rule.rule_version,
            enabled_at=NOW,
            restricted_at=None,
        )
    )
    session.flush()


def _assert_rolled_back(
    session: Session,
    account_id: object,
    before_counts: tuple[int, int, int, int, int, int],
    before_cash: tuple[Decimal, Decimal],
) -> None:
    session.expire_all()
    account = session.get(PaperAccount, account_id)
    assert account is not None
    assert _counts(session) == before_counts
    assert (account.available_cash, account.frozen_cash) == before_cash
    order = session.query(PaperOrder).filter_by(account_id=account.id).one()
    assert order.status is OrderStatus.OPEN
    assert order.filled_quantity == 0
    assert cast(Decimal, order.reserved_cash) > 0
    assert order.reserved_quantity == 0


def test_failure_before_fill_insert_leaves_no_partial_state(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    before_counts = _counts(db_session)
    before_cash = (account.available_cash, account.frozen_cash)
    service = PaperSettlementService(
        db_session,
        calendar=FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)}),
        now=lambda: NOW,
        evidence_provider=lambda **_: (_ for _ in ()).throw(RuntimeError("quote-fault")),
    )

    with pytest.raises(RuntimeError, match="quote-fault"), db_session.begin_nested():
        service.apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)

    _assert_rolled_back(db_session, account.id, before_counts, before_cash)


def test_failure_after_ledger_and_lot_updates_rolls_back_every_projection(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    before_counts = _counts(db_session)
    before_cash = (account.available_cash, account.frozen_cash)
    original = PaperSettlementService._settle_buy

    def explode(self: PaperSettlementService, **kwargs: object) -> Decimal:
        original(self, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("after-ledger")

    monkeypatch.setattr(PaperSettlementService, "_settle_buy", explode)
    with pytest.raises(RuntimeError, match="after-ledger"), db_session.begin_nested():
        _service(db_session, execution).apply(
            order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1
        )

    _assert_rolled_back(db_session, account.id, before_counts, before_cash)


def test_failure_before_trade_projection_rolls_back_fill_lot_and_cash(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    before_counts = _counts(db_session)
    before_cash = (account.available_cash, account.frozen_cash)
    trades = TradeService(db_session)
    trades.create = lambda **_: (_ for _ in ()).throw(RuntimeError("trade-fault"))  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="trade-fault"), db_session.begin_nested():
        _service(db_session, execution, trade_service=trades).apply(
            order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1
        )

    _assert_rolled_back(db_session, account.id, before_counts, before_cash)


def test_failure_during_position_projection_rolls_back_trade_and_all_prior_writes(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    before_counts = _counts(db_session)
    before_cash = (account.available_cash, account.frozen_cash)

    monkeypatch.setattr(
        TradeService,
        "_recompute_position",
        lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("position-fault")),
    )
    with pytest.raises(RuntimeError, match="position-fault"), db_session.begin_nested():
        _service(db_session, execution).apply(
            order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1
        )

    _assert_rolled_back(db_session, account.id, before_counts, before_cash)


def test_lost_post_commit_response_retries_to_existing_fill(db_session: Session) -> None:
    user, account = _user_account(db_session)
    order = _buy_order(db_session, user, account, 100)
    execution = Execution(price=Decimal("10.00"), quantity=100)
    service = _service(db_session, execution)
    first = service.apply(order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1)
    db_session.commit()
    committed_counts = _counts(db_session)

    second = service.apply(
        order_id=order.id, execution=execution, quote_timestamp=NOW, match_pass=1
    )

    assert second.id == first.id
    assert _counts(db_session) == committed_counts


def test_confirmation_failure_after_freeze_rolls_back_order_cash_and_reservations(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = uuid.uuid4().hex
    user = User(username=f"confirm-fault-{token}", email=f"{token}@test", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    user_id = user.id
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    _enable_main(db_session, account)
    service = _order_service(db_session, FixedQuoteProvider(_quote()))
    order = _prepare(service, user_id)
    db_session.flush()
    before_cash = (account.available_cash, account.frozen_cash)
    before_ledger = int(db_session.scalar(select(func.count()).select_from(PaperCashLedger)) or 0)
    original = PaperAccountService.append_ledger

    def freeze_then_fail(self: PaperAccountService, **kwargs: object):
        row = original(self, **kwargs)  # type: ignore[arg-type]
        if kwargs.get("kind") == "order_freeze":
            raise RuntimeError("after-confirm-freeze")
        return row

    monkeypatch.setattr(PaperAccountService, "append_ledger", freeze_then_fail)
    with pytest.raises(RuntimeError, match="after-confirm-freeze"), db_session.begin_nested():
        service.confirm(
            user_id=user_id,
            order_id=order.id,
            draft=_draft(name="贵州茅台"),
            client_request_id="fault-confirm",
        )

    db_session.expire_all()
    refreshed_order = db_session.get(type(order), order.id)
    refreshed_account = db_session.get(PaperAccount, account.id)
    assert refreshed_order is not None and refreshed_account is not None
    assert refreshed_order.status is OrderStatus.AWAITING_CONFIRMATION
    assert refreshed_order.client_request_id is None
    assert refreshed_order.filled_quantity == 0
    assert refreshed_order.reserved_cash == Decimal("0.00")
    assert refreshed_order.reserved_quantity == 0
    assert (refreshed_account.available_cash, refreshed_account.frozen_cash) == before_cash
    assert (
        int(db_session.scalar(select(func.count()).select_from(PaperCashLedger)) or 0)
        == before_ledger
    )
    assert int(db_session.scalar(select(func.count()).select_from(PaperLotReservation)) or 0) == 0
    assert int(db_session.scalar(select(func.count()).select_from(PaperHoldingLot)) or 0) == 0
