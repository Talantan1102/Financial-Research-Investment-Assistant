"""L1 integration test — GET /portfolio/overview + /portfolio/overview/trend.

Pattern:
- Build a minimal FastAPI app with portfolio_router.
- Override get_db with db_session (real PG + savepoint rollback).
- Override get_current_user_required with a real seeded User row.
- Seed positions via TradeService so Position.user_id is satisfied.
- TUSHARE_MODE=mock via monkeypatch (fallback to integration conftest LLM_MODE=mock).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.models.position import Position
from app.models.position_snapshot import PositionSnapshot
from app.router.auth_router import get_current_user_required
from app.router.portfolio_router import router as portfolio_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(session: Session) -> User:
    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        username=f"ov_test_{uid[:8]}",
        email=f"ov_{uid[:8]}@test.example",
        hashed_password="hashed_pw",
    )
    session.add(user)
    session.flush()
    return user


def _seed_positions(session: Session, user: User) -> None:
    """Seed two Position rows so build_overview returns non-empty data."""
    session.add_all(
        [
            Position(
                id=str(uuid.uuid4()),
                user_id=user.id,
                ts_code="600519.SH",
                name="贵州茅台",
                quantity=100,
                avg_cost=Decimal("1500.00"),
                total_cost=Decimal("150000.00"),
                last_quote_price=Decimal("1650.00"),
                asset_class="stock",
            ),
            Position(
                id=str(uuid.uuid4()),
                user_id=user.id,
                ts_code="110011.OF",
                name="测试基金",
                quantity=10000,
                avg_cost=Decimal("2.500"),
                total_cost=Decimal("25000.00"),
                last_quote_price=Decimal("2.475"),
                asset_class="fund_otc",
            ),
        ]
    )
    session.flush()


def _seed_snapshots(session: Session, user: User) -> None:
    """Seed two daily snapshots so compute_twr and benchmark have data."""
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    for snap_date, price in [(yesterday, 1600.0), (today, 1650.0)]:
        session.add(
            PositionSnapshot(
                id=str(uuid.uuid4()),
                user_id=user.id,
                ts_code="600519.SH",
                snapshot_date=snap_date,
                quantity=100,
                market_price=price,
                market_value=100 * price,
                asset_class="stock",
            )
        )
    session.flush()


@pytest.fixture
def client_with_user(db_session: Session, monkeypatch) -> tuple[TestClient, User]:
    """Minimal FastAPI app with portfolio router, auth override, seeded data."""
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "mock")

    user = _make_user(db_session)
    _seed_positions(db_session, user)
    _seed_snapshots(db_session, user)

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    def _override_auth() -> User:
        return user

    app = FastAPI()
    app.include_router(portfolio_router)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user_required] = _override_auth

    return TestClient(app), user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_overview_endpoint_shape(client_with_user: tuple[TestClient, User]) -> None:
    """GET /portfolio/overview 返回 attribution / structure / narrative / total_value."""
    client, _ = client_with_user
    r = client.get("/portfolio/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "attribution" in body
    assert "structure" in body
    assert "narrative" in body
    assert "total_value" in body
    assert "today_pct" in body
    assert "ytd_pct" in body
    assert isinstance(body["narrative"], str)
    assert len(body["narrative"]) > 0


def test_trend_endpoint_accepts_range(client_with_user: tuple[TestClient, User]) -> None:
    """GET /portfolio/overview/trend?range=3m 返回正确 schema."""
    client, _ = client_with_user
    r = client.get("/portfolio/overview/trend", params={"range": "3m"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"dates", "portfolio", "benchmark", "cumulative", "range"}
    assert body["range"] == "3m"
    assert isinstance(body["dates"], list)
    assert isinstance(body["portfolio"], list)
    assert isinstance(body["benchmark"], list)
    assert isinstance(body["cumulative"], float)


def test_trend_default_range(client_with_user: tuple[TestClient, User]) -> None:
    """GET /portfolio/overview/trend (default range=1m) 正常返回。"""
    client, _ = client_with_user
    r = client.get("/portfolio/overview/trend")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["range"] == "1m"


def test_trend_benchmark_filled(client_with_user: tuple[TestClient, User]) -> None:
    """GET /portfolio/overview/trend benchmark 字段非空(mock tushare 有确定性数据)。"""
    client, _ = client_with_user
    r = client.get("/portfolio/overview/trend", params={"range": "1m"})
    assert r.status_code == 200, r.text
    body = r.json()
    # mock get_index_daily 返回两行数据 → benchmark list 至少 1 个元素
    assert len(body["benchmark"]) >= 1, "benchmark 应由 get_index_daily mock 数据填充"


def test_overview_unauthenticated(db_session: Session) -> None:
    """不带 auth 覆盖时应返回 401。"""
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app = FastAPI()
    app.include_router(portfolio_router)
    app.dependency_overrides[get_db] = _override_get_db
    # 不覆盖 get_current_user_required → 走真实 JWT 校验 → 无 token → 401
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/portfolio/overview")
    assert r.status_code == 401, r.text
