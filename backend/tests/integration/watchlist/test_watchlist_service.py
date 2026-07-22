from sqlalchemy.orm import Session

from app.models.watchlist import WatchlistAudit
from app.services.watchlist_service import ChangeSource, WatchlistService
from tests.unit._helpers import make_user


def test_duplicate_add_is_idempotent_without_overwriting(db_session: Session) -> None:
    user = make_user(db_session)
    service = WatchlistService(db_session)
    source = ChangeSource(session_id="s1", tool_call_id="t1")
    first = service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note="长期看", source=source)
    second = service.add(user_id=user.id, ts_code="600519.SH", name="新名字", note="覆盖尝试", monitoring_enabled=True, source=source)
    assert second.created is False
    assert second.item.id == first.item.id
    assert second.item.note == "长期看"
    assert second.item.monitoring_enabled is False


def test_remove_writes_before_snapshot(db_session: Session) -> None:
    user = make_user(db_session)
    service = WatchlistService(db_session)
    source = ChangeSource(session_id="s1")
    service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note="长期看", source=source)
    service.remove(user_id=user.id, ts_code="600519.SH", source=source)
    audit = db_session.query(WatchlistAudit).filter_by(action="remove").one()
    assert audit.before_json["ts_code"] == "600519.SH"


def test_update_whitelist_and_empty_changes(db_session: Session) -> None:
    user = make_user(db_session)
    service = WatchlistService(db_session)
    item = service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", source=ChangeSource()).item
    assert service.update(user_id=user.id, ts_code="600519.SH", changes={}, source=ChangeSource()).id == item.id
    updated = service.update(user_id=user.id, ts_code="600519.SH", changes={"monitoring_enabled": True}, source=ChangeSource())
    assert updated.monitoring_enabled is True
