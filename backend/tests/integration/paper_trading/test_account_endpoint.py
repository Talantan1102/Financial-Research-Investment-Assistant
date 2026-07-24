from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.app_main import app
from app.core.database import get_db
from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperOrder,
)
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.services.paper_trading.account_service import PaperAccountService
from fastapi import HTTPException, status
from sqlalchemy.orm import Session


@pytest.fixture
def users(db_session: Session) -> dict[str, User]:
    suffix = uuid.uuid4().hex[:12]
    rows = {
        name: User(
            username=f"paper-api-{name}-{suffix}",
            email=f"paper-api-{name}-{suffix}@example.test",
            hashed_password="not-used",
        )
        for name in ("alice", "bob")
    }
    db_session.add_all(rows.values())
    db_session.flush()
    return rows


@asynccontextmanager
async def _client(db_session: Session, user: User | None) -> AsyncIterator[httpx.AsyncClient]:
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
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _holding_lot(
    db_session: Session,
    *,
    user: User,
    account: PaperAccount,
    ts_code: str,
    name: str,
    quantity: int,
    frozen_quantity: int = 0,
    available_on: date | None = None,
) -> PaperHoldingLot:
    now = datetime.now(UTC)
    order = PaperOrder(
        account_id=account.id,
        account_generation=account.generation,
        user_id=user.id,
        client_request_id=f"request-{uuid.uuid4()}",
        source_session_id="session-1",
        source_message_id="message-1",
        proposal_fingerprint=uuid.uuid4().hex * 2,
        ts_code=ts_code,
        name=name,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=Decimal("1528.1250"),
        filled_quantity=quantity,
        avg_fill_price=Decimal("1528.1250"),
        status=OrderStatus.FILLED,
        original_proposal={"quantity": quantity},
        confirmed_payload={"quantity": quantity},
        user_edits={},
        quote_snapshot={"latest_price": "1528.1250", "timestamp": now.isoformat()},
        rules_version="cn-a-20260706",
        expires_at=now + timedelta(minutes=5),
        confirmed_at=now,
        completed_at=now,
    )
    db_session.add(order)
    db_session.flush()
    gross = Decimal("1528.1250") * quantity
    fill = PaperFill(
        order_id=order.id,
        fill_seq=1,
        quantity=quantity,
        price=Decimal("1528.1250"),
        gross_amount=gross,
        commission=Decimal("5.00"),
        stamp_duty=Decimal("0.00"),
        transfer_fee=Decimal("0.00"),
        quote_timestamp=now,
        quote_source="fixed-test-quote",
        executed_at=now,
        trade_id=uuid.uuid4(),
    )
    db_session.add(fill)
    db_session.flush()
    lot = PaperHoldingLot(
        account_id=account.id,
        generation=account.generation,
        ts_code=ts_code,
        name=name,
        source_fill_id=fill.id,
        original_quantity=quantity,
        remaining_quantity=quantity,
        frozen_quantity=frozen_quantity,
        unit_cost=Decimal("1528.1250"),
        available_on=available_on
        or datetime.now(ZoneInfo("Asia/Shanghai")).date(),
    )
    db_session.add(lot)
    db_session.flush()
    return lot


@pytest.mark.asyncio
async def test_account_requires_authentication(db_session: Session) -> None:
    async with _client(db_session, None) as client:
        response = await client.get("/api/v0/paper-trading/account")
        holdings_response = await client.get("/api/v0/paper-trading/holdings")

    assert response.status_code == 401
    assert holdings_response.status_code == 401


@pytest.mark.asyncio
async def test_account_get_or_creates_default_account_for_current_user(
    db_session: Session,
    users: dict[str, User],
) -> None:
    async with _client(db_session, users["alice"]) as client:
        response = await client.get("/api/v0/paper-trading/account")

    assert response.status_code == 200
    assert response.json() == {
        "id": response.json()["id"],
        "generation": 1,
        "initial_cash": "1000000.00",
        "available_cash": "1000000.00",
        "frozen_cash": "0.00",
        "status": "active",
        "source_run_id": None,
        "source_tool_call_id": None,
    }

    async with _client(db_session, users["bob"]) as client:
        bob_response = await client.get("/api/v0/paper-trading/account")
    assert bob_response.status_code == 200
    assert bob_response.json()["id"] != response.json()["id"]


@pytest.mark.asyncio
async def test_holdings_returns_only_current_paper_account_generation(
    db_session: Session,
    users: dict[str, User],
) -> None:
    alice_account = PaperAccountService(db_session).get_or_create(
        user_id=users["alice"].id
    )
    bob_account = PaperAccountService(db_session).get_or_create(user_id=users["bob"].id)
    _holding_lot(
        db_session,
        user=users["alice"],
        account=alice_account,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=200,
        frozen_quantity=20,
        available_on=datetime.now(ZoneInfo("Asia/Shanghai")).date()
        + timedelta(days=1),
    )
    _holding_lot(
        db_session,
        user=users["bob"],
        account=bob_account,
        ts_code="000001.SZ",
        name="平安银行",
        quantity=100,
    )

    async with _client(db_session, users["alice"]) as client:
        response = await client.get("/api/v0/paper-trading/holdings")

    assert response.status_code == 200
    assert response.json() == [
        {
            "generation": alice_account.generation,
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "quantity": 200,
            "frozen_quantity": 20,
            "sellable_quantity": 0,
            "average_cost": "1528.1250",
        }
    ]


@pytest.mark.asyncio
async def test_holdings_can_read_an_explicit_user_owned_generation(
    db_session: Session,
    users: dict[str, User],
) -> None:
    alice_account = PaperAccountService(db_session).get_or_create(
        user_id=users["alice"].id
    )
    bob_account = PaperAccountService(db_session).get_or_create(user_id=users["bob"].id)
    old_generation = alice_account.generation
    _holding_lot(
        db_session,
        user=users["alice"],
        account=alice_account,
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
    )
    _holding_lot(
        db_session,
        user=users["bob"],
        account=bob_account,
        ts_code="000001.SZ",
        name="平安银行",
        quantity=999,
    )
    current_account = PaperAccountService(db_session).reset_confirmed(
        user_id=users["alice"].id,
        initial_cash=Decimal("500000"),
        source_session_id=f"reset-{uuid.uuid4().hex}",
        confirmation_id=uuid.uuid4().hex,
    )
    _holding_lot(
        db_session,
        user=users["alice"],
        account=current_account,
        ts_code="000002.SZ",
        name="万科A",
        quantity=200,
    )

    async with _client(db_session, users["alice"]) as client:
        historical = await client.get(
            "/api/v0/paper-trading/holdings",
            params={"account_generation": old_generation},
        )
        current = await client.get(
            "/api/v0/paper-trading/holdings",
            params={"account_generation": current_account.generation},
        )

    assert historical.status_code == 200
    assert [row["ts_code"] for row in historical.json()] == ["600519.SH"]
    assert current.status_code == 200
    assert [row["ts_code"] for row in current.json()] == ["000002.SZ"]
    assert "000001.SZ" not in historical.text
    assert "000001.SZ" not in current.text


def test_app_registers_only_read_and_preview_paper_trading_operations() -> None:
    operations = {
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/api/v0/paper-trading")
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == {
        ("GET", "/api/v0/paper-trading/account"),
        ("GET", "/api/v0/paper-trading/holdings"),
        ("GET", "/api/v0/paper-trading/orders"),
        ("GET", "/api/v0/paper-trading/orders/{order_id}"),
        ("POST", "/api/v0/paper-trading/orders/preview"),
    }
