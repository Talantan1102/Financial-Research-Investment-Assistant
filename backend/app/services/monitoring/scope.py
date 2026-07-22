"""Monitoring subject schema + load helpers from Position."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.models.position import Position
from app.models.watchlist import WatchlistItem


class MonitoringSubject(BaseModel):
    """A (user_id, ts_code) pair to monitor, derived from non-empty positions."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    ts_code: str
    name: str
    sources: set[str] = set()


def load_active_subjects(session: Session) -> list[MonitoringSubject]:
    """Load all (user_id, ts_code) pairs with non-empty positions.

    Spec § 1 决策 2:scope = positions WHERE quantity > 0(去 monitoring_customers).
    """
    rows = (
        session.query(Position.user_id, Position.ts_code, Position.name)
        .filter(Position.quantity > 0, Position.paper_account_id.is_(None))
        .all()
    )
    merged: dict[tuple[str, str], MonitoringSubject] = {
        (str(r.user_id), r.ts_code): MonitoringSubject(user_id=str(r.user_id), ts_code=r.ts_code, name=r.name, sources={"position"})
        for r in rows
    }
    watch_rows = session.query(WatchlistItem.user_id, WatchlistItem.ts_code, WatchlistItem.name).filter(WatchlistItem.monitoring_enabled.is_(True)).all()
    for r in watch_rows:
        key = (str(r.user_id), r.ts_code)
        if key in merged:
            merged[key].sources.add("watchlist")
        else:
            merged[key] = MonitoringSubject(user_id=key[0], ts_code=r.ts_code, name=r.name, sources={"watchlist"})
    return list(merged.values())
