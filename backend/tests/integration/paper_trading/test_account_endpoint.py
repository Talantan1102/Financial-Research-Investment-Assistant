from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from app.app_main import app
from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
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


@pytest.mark.asyncio
async def test_account_requires_authentication(db_session: Session) -> None:
    async with _client(db_session, None) as client:
        response = await client.get("/api/v0/paper-trading/account")

    assert response.status_code == 401


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
    }

    async with _client(db_session, users["bob"]) as client:
        bob_response = await client.get("/api/v0/paper-trading/account")
    assert bob_response.status_code == 200
    assert bob_response.json()["id"] != response.json()["id"]


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
        ("GET", "/api/v0/paper-trading/orders"),
        ("GET", "/api/v0/paper-trading/orders/{order_id}"),
        ("POST", "/api/v0/paper-trading/orders/preview"),
    }
