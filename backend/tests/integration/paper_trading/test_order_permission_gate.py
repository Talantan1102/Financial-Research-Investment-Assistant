from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from app.models.investor_suitability import (
    EntitlementStatus,
    Market,
    MarketAccessRule,
    MarketEntitlement,
)
from app.models.paper_account import PaperAccount
from app.models.paper_order import OrderSide
from app.models.user import User
from app.schemas.paper_trading import OrderDraft
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from sqlalchemy.orm import Session

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 20, 10, 0, tzinfo=SHANGHAI)


class FixedQuoteProvider:
    def get_sync(self, ts_code: str) -> RealtimeQuote:
        return RealtimeQuote(
            ts_code=ts_code,
            name="贵州茅台",
            quoted_at=NOW,
            previous_close=Decimal("1500"),
            last_price=Decimal("1501"),
            bids=tuple(
                QuoteLevel(price=Decimal("1500") - level, quantity=1000) for level in range(5)
            ),
            asks=tuple(
                QuoteLevel(price=Decimal("1502") + level, quantity=1000) for level in range(5)
            ),
            source="fixed",
            suspended=False,
        )


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"permission-gate-{suffix}", email=f"{suffix}@example.test", hashed_password="x"
    )
    db_session.add(row)
    db_session.flush()
    return row


def _service(session: Session, **changes: object) -> PaperOrderService:
    return PaperOrderService(
        session,
        quote_provider=FixedQuoteProvider(),
        clock=TradingClock(FixedTradingCalendar({NOW.date(), date(2026, 7, 21)})),
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: NOW,
        **changes,
    )


def _draft(*, side: OrderSide = OrderSide.BUY) -> OrderDraft:
    return OrderDraft(
        side=side,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
        order_type="limit",
        limit_price=Decimal("1500"),
    )


def _enable_main(
    session: Session, account: PaperAccount, *, can_buy: bool = True, can_sell: bool = True
) -> None:
    rule = MarketAccessRule(
        market=Market.MAIN,
        effective_from=NOW.date(),
        minimum_average_assets_20d=None,
        minimum_experience_months=None,
        required_disclosure_version="main-risk-v1",
        rule_version="a-share-20260727",
    )
    entitlement = MarketEntitlement(
        account_id=account.id,
        account_generation=account.generation,
        market=Market.MAIN,
        status=EntitlementStatus.ENABLED,
        can_buy=can_buy,
        can_sell=can_sell,
        can_subscribe=False,
        rule_version=rule.rule_version,
        enabled_at=NOW,
        restricted_at=None,
    )
    session.add_all((rule, entitlement))
    session.flush()


def test_preview_draft_fails_closed_when_market_entitlement_is_missing(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)

    with pytest.raises(PaperTradingError) as raised:
        _service(db_session).preview_draft(user_id=user_id, draft=_draft())

    assert raised.value.code == "market_permission_required"


def test_preview_uses_buy_and_sell_entitlement_capabilities(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    _enable_main(db_session, account, can_buy=False, can_sell=True)
    service = _service(db_session)

    with pytest.raises(PaperTradingError) as buy:
        service.preview_draft(user_id=user_id, draft=_draft(side=OrderSide.BUY))
    with pytest.raises(PaperTradingError) as sell:
        service.preview_draft(user_id=user_id, draft=_draft(side=OrderSide.SELL))

    assert buy.value.code == "market_permission_required"
    assert sell.value.code == "insufficient_sellable_quantity"


def test_confirmation_rechecks_permission_while_current_account_is_locked(
    db_session: Session, user: User
) -> None:
    user_id = cast(uuid.UUID, user.id)
    account = PaperAccountService(db_session).get_or_create(user_id=user_id)
    _enable_main(db_session, account)
    service = _service(db_session)
    order, _ = service.prepare_order(
        user_id=user_id,
        session_id="permission-gate",
        message_id="proposal-1",
        **_draft().model_dump(),
    )
    entitlement = db_session.query(MarketEntitlement).one()
    entitlement.can_buy = False
    entitlement.status = EntitlementStatus.RESTRICTED
    entitlement.restricted_at = NOW
    db_session.flush()

    with pytest.raises(PaperTradingError) as raised:
        service.confirm(
            user_id=user_id,
            order_id=cast(uuid.UUID, order.id),
            draft=_draft(),
            client_request_id="permission-gate-confirm",
        )

    assert raised.value.code == "market_permission_required"


def test_permission_reader_failure_fails_closed(db_session: Session, user: User) -> None:
    class FailingReader:
        def is_permitted(self, **_: object) -> bool:
            raise RuntimeError("database read failed")

    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)

    with pytest.raises(PaperTradingError) as raised:
        _service(db_session, entitlement_reader=FailingReader()).preview_draft(
            user_id=user_id, draft=_draft()
        )

    assert raised.value.code == "market_permission_required"
