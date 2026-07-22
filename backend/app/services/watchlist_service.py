"""Audited, transaction-scoped CRUD for user watchlists."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.models.watchlist import WatchlistAudit, WatchlistItem


class ChangeSource(BaseModel):
    session_id: str | None = None
    tool_call_id: str | None = None


class AddResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    item: WatchlistItem
    created: bool


def _snapshot(item: WatchlistItem) -> dict[str, object]:
    return {
        "id": str(item.id), "user_id": str(item.user_id), "ts_code": item.ts_code,
        "name": item.name, "note": item.note, "monitoring_enabled": bool(item.monitoring_enabled),
    }


class WatchlistService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, *, user_id: UUID) -> list[WatchlistItem]:
        return list(self._session.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user_id).order_by(WatchlistItem.ts_code)).all())

    def add(self, *, user_id: UUID, ts_code: str, name: str, note: str | None = None, monitoring_enabled: bool = False, source: ChangeSource) -> AddResult:
        existing = self._session.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user_id, WatchlistItem.ts_code == ts_code))
        if existing is not None:
            return AddResult(item=existing, created=False)
        item = WatchlistItem(user_id=user_id, ts_code=ts_code, name=name, note=note, monitoring_enabled=monitoring_enabled)
        self._session.add(item)
        self._session.flush()
        self._audit(item=item, action="add", before=None, after=_snapshot(item), source=source)
        self._session.flush()
        return AddResult(item=item, created=True)

    def update(self, *, user_id: UUID, ts_code: str, changes: dict[str, object], source: ChangeSource) -> WatchlistItem:
        item = self._find(user_id=user_id, ts_code=ts_code)
        unknown = set(changes) - {"name", "note", "monitoring_enabled"}
        if unknown:
            raise ValueError(f"unsupported watchlist fields: {sorted(unknown)}")
        if not changes:
            return item
        before = _snapshot(item)
        for key, value in changes.items():
            setattr(item, key, value)
        self._session.flush()
        self._audit(item=item, action="update", before=before, after=_snapshot(item), source=source)
        self._session.flush()
        return item

    def remove(self, *, user_id: UUID, ts_code: str, source: ChangeSource) -> None:
        item = self._find(user_id=user_id, ts_code=ts_code)
        before = _snapshot(item)
        self._audit(item=item, action="remove", before=before, after=None, source=source)
        self._session.delete(item)
        self._session.flush()

    def _find(self, *, user_id: UUID, ts_code: str) -> WatchlistItem:
        item = self._session.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user_id, WatchlistItem.ts_code == ts_code))
        if item is None:
            raise NoResultFound("watchlist item not found")
        return item

    def _audit(self, *, item: WatchlistItem, action: str, before: dict[str, object] | None, after: dict[str, object] | None, source: ChangeSource) -> None:
        self._session.add(WatchlistAudit(item_id=item.id, user_id=item.user_id, action=action, before_json=before, after_json=after, source_session_id=source.session_id, source_tool_call_id=source.tool_call_id))
