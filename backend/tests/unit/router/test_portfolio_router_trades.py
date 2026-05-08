"""POST/DELETE/PATCH /portfolio/trades endpoint tests (with TestClient + sqlite override)。

Auth 模式跟 reports.py 同 — get_current_user_required(JWT)。
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from app.core.database import get_db
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.portfolio_router import router as portfolio_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from tests.unit._helpers import make_user


@pytest.fixture
def app_and_session() -> Generator[tuple[FastAPI, Session, User], None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Trade.__table__.create(engine)
    Position.__table__.create(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session_()
    user = make_user(session)
    session.commit()

    app = FastAPI()
    app.include_router(portfolio_router)

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user_required] = lambda: user

    yield app, session, user
    session.close()


def test_post_trades_creates_trade_and_position(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    app, session, user = app_and_session
    client = TestClient(app)
    resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "initial",
            "quantity": 200,
            "price": "1450.00",
            "trade_date": "2024-06-01",
            "note": "first",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ts_code"] == "600519.SH"
    assert body["quantity"] == 200

    pos = session.query(Position).filter_by(user_id=user.id).one()
    assert pos.quantity == 200


def test_delete_trade_within_24h_returns_204(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    app, session, user = app_and_session
    client = TestClient(app)
    create_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "initial",
            "quantity": 200,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    assert create_resp.status_code == 201
    trade_id = create_resp.json()["id"]

    del_resp = client.delete(f"/portfolio/trades/{trade_id}")
    assert del_resp.status_code == 204
    assert session.query(Trade).count() == 0


def test_delete_trade_after_24h_returns_409(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    app, session, user = app_and_session
    client = TestClient(app)
    create_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "initial",
            "quantity": 200,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    trade_id = create_resp.json()["id"]
    trade = session.query(Trade).filter_by(id=trade_id).one()
    trade.created_at = datetime.utcnow() - timedelta(hours=25)  # type: ignore[assignment]
    session.commit()

    del_resp = client.delete(f"/portfolio/trades/{trade_id}")
    assert del_resp.status_code == 409
    assert "24h" in del_resp.json()["detail"]


def test_patch_initial_trade_succeeds(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    app, session, user = app_and_session
    client = TestClient(app)
    create_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "initial",
            "quantity": 200,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    trade_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/portfolio/trades/{trade_id}",
        json={"price": "1455.00"},
    )
    assert patch_resp.status_code == 200
    from decimal import Decimal

    assert Decimal(patch_resp.json()["price"]) == Decimal("1455.00")


def test_patch_buy_trade_returns_409(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    app, session, user = app_and_session
    client = TestClient(app)
    client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "initial",
            "quantity": 200,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    buy_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "贵州茅台",
            "type": "buy",
            "quantity": 50,
            "price": "1500.00",
            "trade_date": "2026-01-15",
        },
    )
    buy_id = buy_resp.json()["id"]

    patch_resp = client.patch(
        f"/portfolio/trades/{buy_id}",
        json={"price": "1499.00"},
    )
    assert patch_resp.status_code == 409
    assert "不可改" in patch_resp.json()["detail"]


def test_delete_other_user_trade_returns_404(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    """Cross-user isolation: trade owned by another user should 404, not 500 or success."""
    app, session, user = app_and_session
    client = TestClient(app)
    # Create a trade owned by 'user'
    create_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "茅台",
            "type": "initial",
            "quantity": 100,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    trade_id = create_resp.json()["id"]

    # Override auth to a different user
    other_user = make_user(session)
    session.commit()
    app.dependency_overrides[get_current_user_required] = lambda: other_user

    del_resp = client.delete(f"/portfolio/trades/{trade_id}")
    assert del_resp.status_code == 404


def test_delete_nonexistent_trade_returns_404(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    """Nonexistent trade_id should 404, not 500."""
    app, _, _ = app_and_session
    client = TestClient(app)
    del_resp = client.delete("/portfolio/trades/nonexistent-id-xyz")
    assert del_resp.status_code == 404


def test_patch_other_user_trade_returns_404(
    app_and_session: tuple[FastAPI, Session, User],
) -> None:
    """Cross-user isolation on PATCH: trade owned by another user should 404."""
    app, session, user = app_and_session
    client = TestClient(app)
    # Create a trade owned by 'user'
    create_resp = client.post(
        "/portfolio/trades",
        json={
            "ts_code": "600519.SH",
            "name": "茅台",
            "type": "initial",
            "quantity": 100,
            "price": "1450.00",
            "trade_date": "2024-06-01",
        },
    )
    trade_id = create_resp.json()["id"]

    # Override auth to a different user
    other_user = make_user(session)
    session.commit()
    app.dependency_overrides[get_current_user_required] = lambda: other_user

    patch_resp = client.patch(
        f"/portfolio/trades/{trade_id}",
        json={"price": "1455.00"},
    )
    assert patch_resp.status_code == 404
