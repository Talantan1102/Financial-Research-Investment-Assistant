from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from app.app_main import app
from app.core.database import get_db
from app.models.user import User
from app.models.watchlist import WatchlistAudit
from app.router.auth_router import get_current_user_required
from app.schemas.watchlist import WatchlistUpdate
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def users(db_session: Session) -> dict[str, User]:
    suffix = uuid.uuid4().hex[:12]
    users = {
        name: User(
            username=f"watchlist-api-{name}-{suffix}",
            email=f"watchlist-api-{name}-{suffix}@example.test",
            hashed_password="not-used",
        )
        for name in ("alice", "bob")
    }
    db_session.add_all(users.values())
    db_session.flush()
    return users


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
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_watchlist_requires_authentication(db_session: Session) -> None:
    async with _client(db_session, None) as client:
        response = await client.get("/api/v0/watchlist")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_watchlist_crud_defaults_off_and_is_user_scoped(
    db_session: Session,
    users: dict[str, User],
) -> None:
    async with _client(db_session, users["alice"]) as client:
        created = await client.post(
            "/api/v0/watchlist",
            json={"ts_code": "600519.SH", "name": "贵州茅台", "note": "观察"},
        )
        duplicate = await client.post(
            "/api/v0/watchlist",
            json={
                "ts_code": "600519.SH",
                "name": "不应覆盖",
                "note": "不应覆盖",
                "monitoring_enabled": True,
            },
        )
        listed = await client.get("/api/v0/watchlist")
        updated = await client.patch(
            "/api/v0/watchlist/600519.SH",
            json={"monitoring_enabled": True},
        )

    assert created.status_code == 201
    assert created.json()["monitoring_enabled"] is False
    assert duplicate.status_code == 200
    assert duplicate.json()["name"] == "贵州茅台"
    assert duplicate.json()["note"] == "观察"
    assert duplicate.json()["monitoring_enabled"] is False
    assert listed.json() == [created.json()]
    assert updated.status_code == 200
    assert updated.json()["monitoring_enabled"] is True

    async with _client(db_session, users["bob"]) as client:
        assert (await client.get("/api/v0/watchlist")).json() == []
        hidden_update = await client.patch(
            "/api/v0/watchlist/600519.SH",
            json={"note": "越权"},
        )
        hidden_remove = await client.delete("/api/v0/watchlist/600519.SH")

    assert hidden_update.status_code == 404
    assert hidden_remove.status_code == 200
    assert hidden_remove.json() == {"removed": False}


@pytest.mark.asyncio
async def test_endpoint_idempotency_has_exact_audit_count(
    db_session: Session,
    users: dict[str, User],
) -> None:
    async with _client(db_session, users["alice"]) as client:
        await client.post(
            "/api/v0/watchlist",
            json={"ts_code": "000001.SZ", "name": "平安银行"},
        )
        await client.patch(
            "/api/v0/watchlist/000001.SZ",
            json={"monitoring_enabled": False},
        )
        first_delete = await client.delete("/api/v0/watchlist/000001.SZ")
        second_delete = await client.delete("/api/v0/watchlist/000001.SZ")

    assert first_delete.json() == {"removed": True}
    assert second_delete.json() == {"removed": False}
    count = db_session.scalar(select(func.count()).select_from(WatchlistAudit))
    assert count == 2


@pytest.mark.parametrize(
    "payload",
    [{"name": None}, {"monitoring_enabled": None}],
)
def test_update_rejects_null_for_non_nullable_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        WatchlistUpdate.model_validate(payload)
