from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.paper_account import PaperAccount, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import PaperFill, PaperMatchPass
from app.models.position import Position
from app.models.trade import Trade
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
