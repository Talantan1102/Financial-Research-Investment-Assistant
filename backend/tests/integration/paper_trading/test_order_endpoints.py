from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import app.router.paper_trading_router as paper_router
import pandas as pd
import pytest
from app.core.database import get_db
from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperFill, PaperOrder
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.paper_trading_router import get_paper_order_service, router
from app.schemas.paper_trading import OrderDraft
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import MarketPhase, QuoteLevel, RealtimeQuote
from app.services.trade_calendar import build_calendar_df
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

NOW = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)


class FixedQuoteProvider:
    def __init__(self, *, quoted_at: datetime = NOW) -> None:
        self.quoted_at = quoted_at

    async def get(self, ts_code: str) -> RealtimeQuote:
        return self.get_sync(ts_code)

    def get_sync(self, ts_code: str) -> RealtimeQuote:
        return RealtimeQuote(
            ts_code=ts_code,
            name="贵州茅台",
            quoted_at=self.quoted_at,
            previous_close=Decimal("1500.00"),
            last_price=Decimal("1501.00"),
            bids=tuple(
                QuoteLevel(price=Decimal("1500.00") - Decimal(level) / 100, quantity=1000)
                for level in range(5)
            ),
            asks=tuple(
                QuoteLevel(price=Decimal("1501.00") + Decimal(level) / 100, quantity=1000)
                for level in range(5)
            ),
            source="endpoint-test",
            suspended=False,
        )


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-order-api-{suffix}",
        email=f"paper-order-api-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture(autouse=True)
def _stub_paper_match_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Span:
        span_id = "test-paper-span"

    monkeypatch.setattr(paper_router, "_record_order_span", lambda **_kwargs: _Span())
    monkeypatch.setattr(paper_router, "dispatch_match_order", lambda _order_id, **_kwargs: True)


def _service(session: Session, *, quoted_at: datetime = NOW) -> PaperOrderService:
    return PaperOrderService(
        session,
        quote_provider=FixedQuoteProvider(quoted_at=quoted_at),
        clock=TradingClock(FixedTradingCalendar({date(2026, 7, 20), date(2026, 7, 21)})),
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: NOW,
    )


def _app(session: Session, user: User, *, service: PaperOrderService | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    def override_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user_required] = lambda: user
    app.dependency_overrides[get_paper_order_service] = lambda: service or _service(session)
    return app


def _prepared(session: Session, user: User) -> tuple[PaperAccount, PaperOrder]:
    account = PaperAccountService(session).get_or_create(user_id=cast(uuid.UUID, user.id))
    order, _ = _service(session).prepare_order(
        user_id=cast(uuid.UUID, user.id),
        session_id="api-session",
        message_id=f"api-message-{uuid.uuid4()}",
        side="buy",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
        order_type="limit",
        limit_price=Decimal("1501.00"),
    )
    session.commit()
    return account, order


def _draft(quantity: int = 100) -> dict[str, object]:
    return {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": quantity,
        "order_type": "limit",
        "limit_price": "1501.0000",
    }


def _filled_lot(session: Session, user: User, account: PaperAccount) -> None:
    order = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"filled-{uuid.uuid4()}",
        source_session_id="api-filled",
        source_message_id="api-filled",
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code="600519.SH",
        name="贵州茅台",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=200,
        limit_price=Decimal("10.0000"),
        filled_quantity=200,
        avg_fill_price=Decimal("10.0000"),
        status=OrderStatus.FILLED,
        original_proposal={"quantity": 200},
        confirmed_payload={"quantity": 200},
        user_edits={},
        quote_snapshot={"last_price": "10.0000"},
        rules_version="cn-a-20260706",
        expires_at=NOW + timedelta(minutes=5),
        confirmed_at=NOW,
        completed_at=NOW,
    )
    session.add(order)
    session.flush()
    fill = PaperFill(
        order_id=order.id,
        fill_seq=1,
        quantity=200,
        price=Decimal("10.0000"),
        gross_amount=Decimal("2000.0000"),
        commission=Decimal("5.0000"),
        stamp_duty=Decimal("0.0000"),
        transfer_fee=Decimal("0.0200"),
        quote_timestamp=NOW,
        quote_source="endpoint-test",
        executed_at=NOW,
        trade_id=uuid.uuid4(),
    )
    session.add(fill)
    session.flush()
    session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code="600519.SH",
            name="贵州茅台",
            source_fill_id=fill.id,
            original_quantity=200,
            remaining_quantity=200,
            frozen_quantity=100,
            unit_cost=Decimal("10.0251"),
            available_on=date(2020, 1, 1),
        )
    )
    session.commit()


def test_complete_paper_trading_endpoint_table_is_exposed() -> None:
    routes = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert routes == {
        ("GET", "/api/v0/paper-trading/account"),
        ("PATCH", "/api/v0/paper-trading/account/initial-cash"),
        ("POST", "/api/v0/paper-trading/account/reset-preview"),
        ("POST", "/api/v0/paper-trading/account/reset-confirm"),
        ("GET", "/api/v0/paper-trading/orders"),
        ("GET", "/api/v0/paper-trading/orders/{order_id}"),
        ("GET", "/api/v0/paper-trading/holdings"),
        ("GET", "/api/v0/paper-trading/fills"),
        ("GET", "/api/v0/paper-trading/cash-ledger"),
        ("POST", "/api/v0/paper-trading/orders/{order_id}/preview"),
        ("POST", "/api/v0/paper-trading/orders/{order_id}/confirm"),
        ("POST", "/api/v0/paper-trading/orders/{order_id}/cancel-preview"),
        ("POST", "/api/v0/paper-trading/orders/{order_id}/cancel-confirm"),
    }


def test_reads_default_to_active_generation_and_allow_owned_history(
    db_session: Session, user: User
) -> None:
    old_account, old_order = _prepared(db_session, user)
    new_account = _service(db_session).reset_account_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000.00"),
        session_id="api-reset",
        confirmation_id="api-reset",
    )
    db_session.commit()
    client = TestClient(_app(db_session, user))

    assert client.get("/api/v0/paper-trading/orders").json() == []
    history = client.get(f"/api/v0/paper-trading/orders?generation={old_account.generation}")
    assert history.status_code == 200
    assert [row["id"] for row in history.json()] == [str(old_order.id)]
    assert history.json()[0]["limit_price"] == "1501.0000"
    assert client.get(f"/api/v0/paper-trading/orders/{old_order.id}").status_code == 404
    assert (
        client.get(
            f"/api/v0/paper-trading/orders/{old_order.id}?generation={old_account.generation}"
        ).status_code
        == 200
    )
    historical_account = client.get(
        f"/api/v0/paper-trading/account?generation={old_account.generation}"
    )
    assert historical_account.status_code == 200
    assert historical_account.json()["status"] == "archived"
    assert new_account.generation == 2


def test_read_collections_are_generation_scoped_and_serialize_money(
    db_session: Session, user: User
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    db_session.commit()
    client = TestClient(_app(db_session, user))

    assert client.get("/api/v0/paper-trading/holdings").json() == []
    assert client.get("/api/v0/paper-trading/fills").json() == []
    ledger = client.get("/api/v0/paper-trading/cash-ledger")
    assert ledger.status_code == 200
    assert ledger.json()[0]["generation"] == account.generation
    assert ledger.json()[0]["amount"] == "1000000.00"
    assert datetime.fromisoformat(ledger.json()[0]["created_at"]).utcoffset() is not None


def test_holdings_aggregate_total_frozen_and_sellable_quantities(
    db_session: Session, user: User
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    _filled_lot(db_session, user, account)

    response = TestClient(_app(db_session, user)).get("/api/v0/paper-trading/holdings")

    assert response.status_code == 200
    assert response.json() == [
        {
            "generation": 1,
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "quantity": 200,
            "frozen_quantity": 100,
            "sellable_quantity": 100,
            "average_cost": "10.0251",
        }
    ]


@pytest.mark.parametrize(
    "path,payload",
    [
        ("preview", {"draft": _draft()}),
        ("confirm", {"draft": _draft(), "client_request_id": "confirm-other"}),
        ("cancel-preview", None),
        ("cancel-confirm", {"confirmation_id": "cancel-other"}),
    ],
)
def test_other_users_and_missing_orders_are_hidden_as_404(
    db_session: Session, user: User, path: str, payload: dict[str, object] | None
) -> None:
    _, order = _prepared(db_session, user)
    other = User(
        username=f"other-{uuid.uuid4().hex}",
        email=f"other-{uuid.uuid4().hex}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.commit()
    client = TestClient(_app(db_session, other))

    response = client.post(f"/api/v0/paper-trading/orders/{order.id}/{path}", json=payload)
    missing = client.get(f"/api/v0/paper-trading/orders/{uuid.uuid4()}")

    assert response.status_code == 404
    assert missing.status_code == 404


def test_preview_confirm_and_retry_preserve_draft_edits(db_session: Session, user: User) -> None:
    _, order = _prepared(db_session, user)
    client = TestClient(_app(db_session, user))
    payload = {"draft": _draft(200)}

    preview = client.post(f"/api/v0/paper-trading/orders/{order.id}/preview", json=payload)
    first = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={**payload, "client_request_id": "api-confirm-1"},
    )
    retry = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={**payload, "client_request_id": "api-confirm-1"},
    )

    assert preview.status_code == 200
    assert preview.json()["draft"]["quantity"] == 200
    assert first.status_code == retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"] == str(order.id)
    assert first.json()["quantity"] == 200
    assert first.json()["status"] == "open"
    assert first.json()["reserved_cash"] == preview.json()["estimated_cash_required"]


def test_confirm_dispatches_matching_only_after_commit(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, order = _prepared(db_session, user)
    dispatched: list[tuple[uuid.UUID, bool]] = []
    monkeypatch.setattr(
        paper_router,
        "dispatch_match_order",
        lambda order_id, **_kwargs: (
            dispatched.append((order_id, db_session.in_transaction())) or True
        ),
    )

    response = TestClient(_app(db_session, user)).post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={"draft": _draft(), "client_request_id": "dispatch-after-commit"},
    )

    assert response.status_code == 200
    assert dispatched == [(order.id, False)]


def test_confirm_span_is_parent_of_dispatched_worker_trace(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, order = _prepared(db_session, user)
    emitted: list[dict[str, object]] = []
    dispatched: list[tuple[uuid.UUID, str | None]] = []

    class _Span:
        span_id = "rest-confirm-span"

    monkeypatch.setattr(
        paper_router,
        "_record_order_span",
        lambda **kwargs: emitted.append(kwargs) or _Span(),
    )
    monkeypatch.setattr(
        paper_router,
        "dispatch_match_order",
        lambda order_id, *, trace_parent_id=None: (
            dispatched.append((order_id, trace_parent_id)) or True
        ),
    )

    response = TestClient(_app(db_session, user)).post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={"draft": _draft(), "client_request_id": "trace-parent-confirm"},
    )
    retry = TestClient(_app(db_session, user)).post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={"draft": _draft(), "client_request_id": "trace-parent-confirm"},
    )

    assert response.status_code == retry.status_code == 200
    assert [row["name"] for row in emitted] == ["confirm", "confirm"]
    assert emitted[0]["attrs"] == {
        "idempotent_replay": False,
        "outcome": "success",
        "status": "open",
    }
    assert emitted[1]["attrs"] == {
        "idempotent_replay": True,
        "outcome": "success",
        "status": "open",
    }
    assert dispatched == [
        (order.id, "rest-confirm-span"),
        (order.id, "rest-confirm-span"),
    ]


def test_confirm_remains_successful_when_dispatch_fails_for_later_scan(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, order = _prepared(db_session, user)
    monkeypatch.setattr(paper_router, "dispatch_match_order", lambda _order_id, **_kwargs: False)

    response = TestClient(_app(db_session, user)).post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={"draft": _draft(), "client_request_id": "dispatch-recovery"},
    )

    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(PaperOrder, order.id).status is OrderStatus.OPEN


def test_cancel_preview_and_confirm_are_explicit_and_idempotent(
    db_session: Session, user: User
) -> None:
    _, order = _prepared(db_session, user)
    client = TestClient(_app(db_session, user))
    confirmed = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/confirm",
        json={"draft": _draft(), "client_request_id": "api-confirm-cancel"},
    )
    assert confirmed.status_code == 200

    preview = client.post(f"/api/v0/paper-trading/orders/{order.id}/cancel-preview")
    first = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/cancel-confirm",
        json={"confirmation_id": "api-cancel"},
    )
    retry = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/cancel-confirm",
        json={"confirmation_id": "api-cancel"},
    )

    assert preview.status_code == 200
    assert preview.json()["remaining_quantity"] == 100
    assert first.status_code == retry.status_code == 200
    assert first.json()["status"] == retry.json()["status"] == "cancelled"


def test_reset_preview_and_confirm_are_explicit_and_idempotent(
    db_session: Session, user: User
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    db_session.commit()
    client = TestClient(_app(db_session, user))
    preview = client.post(
        "/api/v0/paper-trading/account/reset-preview", json={"initial_cash": "700000.00"}
    )
    payload = {
        "initial_cash": "700000.00",
        "session_id": "api-reset-session",
        "confirmation_id": "api-reset-confirmation",
    }
    first = client.post("/api/v0/paper-trading/account/reset-confirm", json=payload)
    retry = client.post("/api/v0/paper-trading/account/reset-confirm", json=payload)

    assert preview.status_code == 200
    assert preview.json()["account_id"] == str(account.id)
    assert first.status_code == retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"]
    assert first.json()["generation"] == 2
    assert first.json()["initial_cash"] == "700000.00"


def test_business_errors_are_409_with_stable_detail_and_rollback(
    db_session: Session, user: User
) -> None:
    _, order = _prepared(db_session, user)
    stale_service = _service(db_session, quoted_at=NOW - timedelta(minutes=5))
    client = TestClient(_app(db_session, user, service=stale_service))

    response = client.post(
        f"/api/v0/paper-trading/orders/{order.id}/preview", json={"draft": _draft()}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "stale_quote", "message": "实时行情已过期"}
    db_session.expire_all()
    assert db_session.get(PaperOrder, order.id).status is OrderStatus.AWAITING_CONFIRMATION


@pytest.mark.parametrize(
    "path,payload",
    [
        ("account/reset-preview", {"initial_cash": "1.001"}),
        ("account/reset-confirm", {"initial_cash": "1", "session_id": "s"}),
        (
            f"orders/{uuid.uuid4()}/confirm",
            {"draft": {**_draft(), "extra": True}, "client_request_id": "x"},
        ),
    ],
)
def test_write_payloads_are_strict(
    db_session: Session, user: User, path: str, payload: dict[str, object]
) -> None:
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    db_session.commit()

    response = TestClient(_app(db_session, user)).post(
        f"/api/v0/paper-trading/{path}", json=payload
    )

    assert response.status_code == 422


def test_rest_dependency_uses_exchange_calendar_for_holiday_and_open_day(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fetch(start: str, end: str) -> pd.DataFrame:
        return build_calendar_df(start, end)

    monkeypatch.setattr(paper_router, "_fetch_trading_calendar", fetch)
    service = get_paper_order_service(db_session)
    holiday = datetime(2026, 10, 1, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert service.clock.phase(holiday) is MarketPhase.CLOSED
    assert (
        service.clock.phase(datetime(2026, 10, 9, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
        is MarketPhase.MORNING
    )

    holiday_service = PaperOrderService(
        db_session,
        quote_provider=FixedQuoteProvider(quoted_at=holiday),
        clock=service.clock,
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: holiday,
    )
    PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    order, _ = holiday_service.prepare_order(
        user_id=cast(uuid.UUID, user.id),
        session_id="holiday-session",
        message_id="holiday-message",
        side="buy",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
        order_type="limit",
        limit_price=Decimal("1501.00"),
    )
    confirmed = holiday_service.confirm(
        user_id=cast(uuid.UUID, user.id),
        order_id=cast(uuid.UUID, order.id),
        draft=OrderDraft.model_validate(_draft()),
        client_request_id="holiday-confirm",
    )

    assert confirmed.status is OrderStatus.QUEUED


def test_rest_calendar_bridge_reuses_project_tushare_factory_and_closes_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    closed = False

    class FakeTushareService:
        async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame:
            calls.append((start, end))
            return pd.DataFrame([{"cal_date": start, "is_open": 1}])

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(paper_router, "build_tushare_service", FakeTushareService)

    frame = paper_router._fetch_trading_calendar("20260720", "20260721")

    assert frame.to_dict("records") == [{"cal_date": "20260720", "is_open": 1}]
    assert calls == [("20260720", "20260721")]
    assert closed
