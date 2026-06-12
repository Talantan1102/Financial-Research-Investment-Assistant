"""Integration test — Position.asset_class persists to PG and reads back correctly.

Uses db_session fixture (real PG, savepoint rollback isolation).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.position import Position
from app.models.trade import Trade, TradeType
from app.models.user import User
from app.services.position_service import PositionService
from app.services.trade_service import TradeService


def _make_user(session: Session) -> User:
    """Helper: insert a minimal User row and flush."""
    user = User(
        id=uuid.uuid4(),
        username=f"testuser_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed_pw",
    )
    session.add(user)
    session.flush()
    return user


def test_position_asset_class_default_stock_persists(db_session: Session) -> None:
    """Position created via TradeService (no explicit asset_class) defaults to 'stock' in DB."""
    user = _make_user(db_session)
    svc = TradeService(db_session)

    svc.create(
        user_id=str(user.id),
        ts_code="600519.SH",
        name="贵州茅台",
        ttype=TradeType.INITIAL,
        quantity=100,
        price=Decimal("1450.00"),
        trade_date=date(2024, 6, 1),
    )
    db_session.flush()

    pos_svc = PositionService(db_session)
    pos = pos_svc.get(user_id=str(user.id), ts_code="600519.SH")
    assert pos is not None
    assert pos.asset_class == "stock"


def test_position_asset_class_fund_otc_persists(db_session: Session) -> None:
    """Position created and then asset_class updated to fund_otc persists correctly."""
    user = _make_user(db_session)
    svc = TradeService(db_session)

    svc.create(
        user_id=str(user.id),
        ts_code="110011.OF",
        name="某基金",
        ttype=TradeType.INITIAL,
        quantity=1000,
        price=Decimal("1.00"),
        trade_date=date(2024, 6, 1),
    )
    db_session.flush()

    pos_svc = PositionService(db_session)
    pos = pos_svc.get(user_id=str(user.id), ts_code="110011.OF")
    assert pos is not None

    # Simulate what the onboarding router does: set asset_class after creation
    pos.asset_class = "fund_otc"  # type: ignore[assignment]
    db_session.flush()

    # Re-fetch to confirm DB round-trip
    db_session.expire(pos)
    pos_reloaded = pos_svc.get(user_id=str(user.id), ts_code="110011.OF")
    assert pos_reloaded is not None
    assert pos_reloaded.asset_class == "fund_otc"


def test_position_asset_class_all_valid_values(db_session: Session) -> None:
    """Position accepts all valid asset_class values: stock/fund_etf/fund_otc/bond/gold/cash."""
    user = _make_user(db_session)
    svc = TradeService(db_session)
    pos_svc = PositionService(db_session)

    valid_classes = ["stock", "fund_etf", "fund_otc", "bond", "gold", "cash"]
    # Use unique ts_code for each (max 10 chars for Trade.ts_code column)
    codes = ["T001.SH", "T002.SH", "T003.SH", "T004.SH", "T005.SH", "T006.SH"]
    for ts_code, ac in zip(codes, valid_classes):
        svc.create(
            user_id=str(user.id),
            ts_code=ts_code,
            name=f"测试{ac}",
            ttype=TradeType.INITIAL,
            quantity=10,
            price=Decimal("10.00"),
            trade_date=date(2024, 6, 1),
        )
        db_session.flush()
        pos = pos_svc.get(user_id=str(user.id), ts_code=ts_code)
        assert pos is not None
        pos.asset_class = ac  # type: ignore[assignment]
        db_session.flush()

    # Verify all survived
    for ts_code, ac in zip(codes, valid_classes):
        pos = pos_svc.get(user_id=str(user.id), ts_code=ts_code)
        assert pos is not None
        assert pos.asset_class == ac, f"ts_code={ts_code} expected {ac}, got {pos.asset_class}"
