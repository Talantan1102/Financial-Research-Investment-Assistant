from __future__ import annotations

import importlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.app_main import app
from app.core.database import get_db
from app.models.paper_account import PaperAccountResetAudit, PaperCashLedger, PaperHoldingLot
from app.models.paper_order import (
    PaperFill,
    PaperLotReservation,
    PaperMatchPass,
    PaperOrder,
)
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import FixedTradingCalendar, TradingClock
from app.services.paper_trading.order_service import PaperOrderService
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 20, 10, 0, 5, tzinfo=SHANGHAI)


class FixedQuoteProvider:
    def get_sync(self, ts_code: str) -> RealtimeQuote:
        name = "贵州茅台" if ts_code == "600519.SH" else "平安银行"
        return RealtimeQuote(
            ts_code=ts_code,
            name=name,
            quoted_at=NOW,
            previous_close=Decimal("1500"),
            last_price=Decimal("1501"),
            bids=tuple(
                QuoteLevel(price=Decimal(1500 - level), quantity=1000)
                for level in range(5)
            ),
            asks=tuple(
                QuoteLevel(price=Decimal(1502 + level), quantity=1000)
                for level in range(5)
            ),
            source="fixed",
            suspended=False,
        )


@pytest.fixture
def users(db_session: Session) -> dict[str, User]:
    suffix = uuid.uuid4().hex[:12]
    rows = {
        name: User(
            username=f"paper-orders-{name}-{suffix}",
            email=f"paper-orders-{name}-{suffix}@example.test",
            hashed_password="not-used",
        )
        for name in ("alice", "bob")
    }
    db_session.add_all(rows.values())
    db_session.flush()
    return rows


def _service(db_session: Session) -> PaperOrderService:
    return PaperOrderService(
        db_session,
        quote_provider=FixedQuoteProvider(),
        clock=TradingClock(FixedTradingCalendar({NOW.date(), date(2026, 7, 21)})),
        rulebook=RuleBook.from_builtin_fixture(),
        now=lambda: NOW,
    )


def _seed_order(
    db_session: Session,
    user: User,
    *,
    ts_code: str,
    name: str,
) -> PaperOrder:
    user_id = cast(uuid.UUID, user.id)
    PaperAccountService(db_session).get_or_create(user_id=user_id)
    order, _preview = _service(db_session).prepare_order(
        user_id=user_id,
        session_id=f"seed-{uuid.uuid4().hex}",
        message_id=uuid.uuid4().hex,
        side="buy",
        ts_code=ts_code,
        name=name,
        quantity=100,
        order_type="limit",
        limit_price=Decimal("1500"),
    )
    return order


@asynccontextmanager
async def _client(
    db_session: Session,
    user: User | None,
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_db() -> AsyncIterator[Session]:
        yield db_session

    if user is None:

        async def override_auth() -> User:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    else:

        async def override_auth() -> User:
            return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user_required] = override_auth
    try:
        module = importlib.import_module("app.router.paper_trading_router")
        app.dependency_overrides[module.get_paper_order_service] = lambda: _service(db_session)
    except ModuleNotFoundError:
        pass
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_orders_require_authentication(db_session: Session) -> None:
    async with _client(db_session, None) as client:
        response = await client.get("/api/v0/paper-trading/orders")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_orders_is_tenant_scoped_filtered_and_paginated(
    db_session: Session,
    users: dict[str, User],
) -> None:
    first = _seed_order(db_session, users["alice"], ts_code="600519.SH", name="贵州茅台")
    second = _seed_order(db_session, users["alice"], ts_code="000001.SZ", name="平安银行")
    _seed_order(db_session, users["bob"], ts_code="600519.SH", name="贵州茅台")

    async with _client(db_session, users["alice"]) as client:
        response = await client.get(
            "/api/v0/paper-trading/orders",
            params={
                "status": "awaiting_confirmation",
                "ts_code": "600519.SH",
                "limit": 1,
                "offset": 0,
            },
        )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(first.id)]
    assert str(second.id) not in response.text


@pytest.mark.asyncio
async def test_list_orders_can_isolate_the_current_account_generation(
    db_session: Session,
    users: dict[str, User],
) -> None:
    old_order = _seed_order(
        db_session,
        users["alice"],
        ts_code="600519.SH",
        name="贵州茅台",
    )
    current_account = PaperAccountService(db_session).reset_confirmed(
        user_id=cast(uuid.UUID, users["alice"].id),
        initial_cash=Decimal("1000000"),
        source_session_id=f"reset-{uuid.uuid4().hex}",
        confirmation_id=uuid.uuid4().hex,
    )
    current_order = _seed_order(
        db_session,
        users["alice"],
        ts_code="000001.SZ",
        name="平安银行",
    )

    async with _client(db_session, users["alice"]) as client:
        response = await client.get(
            "/api/v0/paper-trading/orders",
            params={"account_generation": current_account.generation},
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(current_order.id)]
    assert str(old_order.id) not in response.text


@pytest.mark.asyncio
async def test_get_order_hides_other_users_and_unknown_ids(
    db_session: Session,
    users: dict[str, User],
) -> None:
    own = _seed_order(db_session, users["alice"], ts_code="600519.SH", name="贵州茅台")
    foreign = _seed_order(db_session, users["bob"], ts_code="000001.SZ", name="平安银行")

    async with _client(db_session, users["alice"]) as client:
        own_response = await client.get(f"/api/v0/paper-trading/orders/{own.id}")
        foreign_response = await client.get(f"/api/v0/paper-trading/orders/{foreign.id}")
        missing_response = await client.get(
            f"/api/v0/paper-trading/orders/{uuid.uuid4()}"
        )

    assert own_response.status_code == 200
    assert own_response.json()["id"] == str(own.id)
    assert foreign_response.status_code == 404
    assert missing_response.status_code == 404
    assert foreign_response.json() == missing_response.json()


def _row_counts(db_session: Session) -> dict[str, int]:
    models = (
        PaperOrder,
        PaperFill,
        PaperLotReservation,
        PaperMatchPass,
        PaperHoldingLot,
        PaperCashLedger,
        PaperAccountResetAudit,
        Trade,
        Position,
    )
    return {
        model.__tablename__: int(db_session.scalar(select(func.count()).select_from(model)) or 0)
        for model in models
    }


@pytest.mark.asyncio
async def test_preview_is_deterministic_and_has_no_trading_side_effects(
    db_session: Session,
    users: dict[str, User],
) -> None:
    PaperAccountService(db_session).get_or_create(
        user_id=cast(uuid.UUID, users["alice"].id)
    )
    before = _row_counts(db_session)
    payload = {
        "draft": {
            "side": "buy",
            "ts_code": "600519.SH",
            "name": "用户输入名称",
            "quantity": 100,
            "order_type": "limit",
            "limit_price": "1500.0000",
        }
    }

    async with _client(db_session, users["alice"]) as client:
        first = await client.post("/api/v0/paper-trading/orders/preview", json=payload)
        second = await client.post("/api/v0/paper-trading/orders/preview", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert "order_id" not in first.json()
    assert first.json()["draft"]["name"] == "贵州茅台"
    assert first.json()["estimated_gross"] == "150000.00"
    assert first.json()["estimated_cash_required"] == "150046.50"
    assert _row_counts(db_session) == before


@pytest.mark.asyncio
async def test_preview_maps_domain_error_to_safe_4xx(
    db_session: Session,
    users: dict[str, User],
) -> None:
    PaperAccountService(db_session).get_or_create(
        user_id=cast(uuid.UUID, users["alice"].id)
    )
    before = _row_counts(db_session)
    payload = {
        "draft": {
            "side": "buy",
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "quantity": 100,
            "order_type": "limit",
            "limit_price": "1600.0001",
        }
    }

    async with _client(db_session, users["alice"]) as client:
        response = await client.post("/api/v0/paper-trading/orders/preview", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_price_tick",
        "message": "订单参数不符合交易规则",
    }
    assert _row_counts(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("draft_update", "error_code"),
    [
        ({"ts_code": "MALFORMED"}, "invalid_order"),
        ({"name": "超" * 65}, "invalid_order"),
    ],
)
async def test_preview_rejects_malformed_identity_without_side_effects(
    db_session: Session,
    users: dict[str, User],
    draft_update: dict[str, object],
    error_code: str,
) -> None:
    PaperAccountService(db_session).get_or_create(
        user_id=cast(uuid.UUID, users["alice"].id)
    )
    before = _row_counts(db_session)
    draft: dict[str, object] = {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": "1500.0000",
    }
    draft.update(draft_update)

    async with _client(db_session, users["alice"]) as client:
        response = await client.post(
            "/api/v0/paper-trading/orders/preview",
            json={"draft": draft},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": error_code,
        "message": "订单参数不符合交易规则",
    }
    assert _row_counts(db_session) == before
