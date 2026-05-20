"""GET /portfolio/positions + POST /portfolio/onboarding 测试。"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.portfolio_router import router as portfolio_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.unit._helpers import make_user


@pytest.fixture
def client_and_session(
    db_session: Session,
) -> tuple[TestClient, Session, User]:
    user = make_user(db_session)
    db_session.commit()

    app = FastAPI()
    app.include_router(portfolio_router)

    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user_required] = lambda: user

    return TestClient(app), db_session, user


def test_get_positions_empty_returns_empty_list(
    client_and_session: tuple[TestClient, Session, User],
) -> None:
    client, _, _ = client_and_session
    resp = client.get("/portfolio/positions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_onboarding_creates_initial_trades_and_positions(
    client_and_session: tuple[TestClient, Session, User],
) -> None:
    client, session, user = client_and_session
    payload = {
        "trades": [
            {
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "type": "initial",
                "quantity": 200,
                "price": "1450.00",
                "trade_date": "2024-06-01",
                "note": "白酒龙头",
            },
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "type": "initial",
                "quantity": 1000,
                "price": "12.00",
                "trade_date": "2024-06-01",
            },
        ]
    }
    resp = client.post("/portfolio/onboarding", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["trades"]) == 2
    assert len(body["positions"]) == 2

    list_resp = client.get("/portfolio/positions")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 2
    codes = {p["ts_code"] for p in items}
    assert codes == {"600519.SH", "000001.SZ"}


def test_post_onboarding_rejects_non_initial_trade_type(
    client_and_session: tuple[TestClient, Session, User],
) -> None:
    client, _, _ = client_and_session
    resp = client.post(
        "/portfolio/onboarding",
        json={
            "trades": [
                {
                    "ts_code": "600519.SH",
                    "name": "贵州茅台",
                    "type": "buy",
                    "quantity": 50,
                    "price": "1500.00",
                    "trade_date": "2026-01-15",
                }
            ]
        },
    )
    assert resp.status_code == 422
    assert "initial" in resp.text.lower()


def test_post_onboarding_rejects_empty_trades(
    client_and_session: tuple[TestClient, Session, User],
) -> None:
    client, _, _ = client_and_session
    resp = client.post("/portfolio/onboarding", json={"trades": []})
    assert resp.status_code == 422
