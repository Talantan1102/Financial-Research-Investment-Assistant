from __future__ import annotations

import uuid

from app.models.user import User
from app.models.watchlist import WatchlistAudit
from app.services.watchlist_service import ChangeSource, WatchlistService
from sqlalchemy import select
from sqlalchemy.orm import Session


def _user(session: Session) -> User:
    suffix = uuid.uuid4().hex
    user = User(
        username=f"watchlist-service-{suffix}",
        email=f"watchlist-service-{suffix}@example.test",
        hashed_password="not-used",
    )
    session.add(user)
    session.flush()
    return user


def _audits(session: Session) -> list[WatchlistAudit]:
    return list(
        session.scalars(
            select(WatchlistAudit).order_by(WatchlistAudit.created_at, WatchlistAudit.id)
        )
    )


def test_crud_writes_exact_before_and_after_audits(db_session: Session) -> None:
    user = _user(db_session)
    service = WatchlistService(db_session)
    source = ChangeSource(session_id="session-1", tool_call_id="call-1")

    added = service.add(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        note="长期观察",
        source=source,
    )
    assert added.created is True
    assert added.item.monitoring_enabled is False

    updated = service.update(
        user_id=user.id,
        ts_code="600519.SH",
        changes={"note": "等待回调", "monitoring_enabled": True},
        source=source,
    )
    assert updated.note == "等待回调"
    assert updated.monitoring_enabled is True

    removed = service.remove(
        user_id=user.id,
        ts_code="600519.SH",
        source=source,
    )
    assert removed.removed is True

    audits = _audits(db_session)
    assert [audit.action for audit in audits] == ["add", "update", "remove"]
    assert audits[0].before_json is None
    assert audits[0].after_json["monitoring_enabled"] is False
    assert audits[1].before_json["note"] == "长期观察"
    assert audits[1].after_json["note"] == "等待回调"
    assert audits[2].before_json["ts_code"] == "600519.SH"
    assert audits[2].after_json is None
    assert all(audit.session_id == "session-1" for audit in audits)
    assert all(audit.tool_call_id == "call-1" for audit in audits)


def test_duplicate_add_does_not_overwrite_or_append_audit(
    db_session: Session,
) -> None:
    user = _user(db_session)
    service = WatchlistService(db_session)
    source = ChangeSource()
    first = service.add(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        note="保留",
        source=source,
    )

    duplicate = service.add(
        user_id=user.id,
        ts_code="600519.SH",
        name="覆盖名字",
        note="覆盖备注",
        monitoring_enabled=True,
        source=source,
    )

    assert duplicate.created is False
    assert duplicate.item.id == first.item.id
    assert duplicate.item.name == "贵州茅台"
    assert duplicate.item.note == "保留"
    assert duplicate.item.monitoring_enabled is False
    assert [audit.action for audit in _audits(db_session)] == ["add"]


def test_same_update_is_idempotent_and_remove_missing_is_success(
    db_session: Session,
) -> None:
    user = _user(db_session)
    service = WatchlistService(db_session)
    source = ChangeSource()
    service.add(
        user_id=user.id,
        ts_code="600519.SH",
        name="贵州茅台",
        note=None,
        source=source,
    )

    unchanged = service.update(
        user_id=user.id,
        ts_code="600519.SH",
        changes={"name": "贵州茅台", "note": None, "monitoring_enabled": False},
        source=source,
    )
    assert unchanged.name == "贵州茅台"
    assert [audit.action for audit in _audits(db_session)] == ["add"]

    first_remove = service.remove(
        user_id=user.id,
        ts_code="600519.SH",
        source=source,
    )
    second_remove = service.remove(
        user_id=user.id,
        ts_code="600519.SH",
        source=source,
    )
    assert first_remove.removed is True
    assert second_remove.removed is False
    assert [audit.action for audit in _audits(db_session)] == ["add", "remove"]


def test_service_never_reads_or_changes_another_users_item(
    db_session: Session,
) -> None:
    owner = _user(db_session)
    other = _user(db_session)
    service = WatchlistService(db_session)
    service.add(
        user_id=owner.id,
        ts_code="600519.SH",
        name="贵州茅台",
        note="owner",
        source=ChangeSource(),
    )

    assert service.list(user_id=other.id) == []
    assert service.update(
        user_id=other.id,
        ts_code="600519.SH",
        changes={"note": "other"},
        source=ChangeSource(),
    ) is None
    assert service.remove(
        user_id=other.id,
        ts_code="600519.SH",
        source=ChangeSource(),
    ).removed is False
