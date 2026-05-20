"""MonitoringSubject + load_active_subjects from Position."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.models.position import Position
from app.models.user import User
from app.services.monitoring.scope import MonitoringSubject, load_active_subjects
from pydantic import ValidationError
from sqlalchemy.orm import Session


def _make_user(session: Session, email: str = "") -> User:
    # User 模型字段:username/email/hashed_password(plan 写的 password_hash 不存在,且少 username)
    uid = uuid4().hex[:8]
    u = User(
        id=str(uuid4()),
        username=f"user-{uid}",
        email=email or f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    session.add(u)
    session.flush()
    return u


def _make_position(session: Session, user: User, ts_code: str, name: str, qty: int) -> Position:
    pos = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code=ts_code,
        name=name,
        quantity=qty,
        avg_cost=Decimal("100"),
        total_cost=Decimal("100") * qty,
        realized_pnl=Decimal("0"),
    )
    session.add(pos)
    session.flush()
    return pos


def test_load_active_subjects_returns_user_ts_pairs(db_session: Session) -> None:
    u1 = _make_user(db_session)
    _make_position(db_session, u1, "600519.SH", "贵州茅台", 100)
    _make_position(db_session, u1, "300750.SZ", "宁德时代", 50)
    db_session.commit()

    subjects = load_active_subjects(db_session)
    assert len(subjects) == 2
    pairs = {(s.user_id, s.ts_code) for s in subjects}
    assert (u1.id, "600519.SH") in pairs
    assert (u1.id, "300750.SZ") in pairs


def test_load_active_subjects_filters_zero_quantity(db_session: Session) -> None:
    u1 = _make_user(db_session)
    _make_position(db_session, u1, "600519.SH", "茅台", 100)
    _make_position(db_session, u1, "000001.SZ", "平安", 0)  # 已清仓
    db_session.commit()

    subjects = load_active_subjects(db_session)
    codes = {s.ts_code for s in subjects}
    assert codes == {"600519.SH"}


def test_load_active_subjects_cross_user(db_session: Session) -> None:
    u1 = _make_user(db_session, "u1@t")
    u2 = _make_user(db_session, "u2@t")
    _make_position(db_session, u1, "600519.SH", "茅台", 100)
    _make_position(db_session, u2, "600519.SH", "茅台", 200)
    db_session.commit()

    subjects = load_active_subjects(db_session)
    assert len(subjects) == 2
    pairs = {(s.user_id, s.ts_code) for s in subjects}
    assert {(u1.id, "600519.SH"), (u2.id, "600519.SH")} == pairs


def test_subject_pydantic_extra_forbid() -> None:
    """schema 冻 extra='forbid' 不接收意外字段。"""
    with pytest.raises(ValidationError):
        MonitoringSubject(user_id="u", ts_code="x", name="n", garbage="field")  # type: ignore[call-arg]
