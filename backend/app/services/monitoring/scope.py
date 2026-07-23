"""Monitoring subject schema + load helpers from Position."""

from __future__ import annotations

from typing import cast

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
    sources: tuple[str, ...] = ()


def load_active_subjects(session: Session) -> list[MonitoringSubject]:
    """Load all (user_id, ts_code) pairs with non-empty positions.

    Spec § 1 决策 2:scope = positions WHERE quantity > 0(去 monitoring_customers).
    """
    position_rows = (
        session.query(Position.user_id, Position.ts_code, Position.name)
        .filter(Position.quantity > 0)
        .all()
    )
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for row in position_rows:
        key = (str(row.user_id), row.ts_code)
        merged[key] = {
            "user_id": key[0],
            "ts_code": row.ts_code,
            "name": row.name,
            "sources": {"position"},
        }

    watchlist_rows = (
        session.query(
            WatchlistItem.user_id,
            WatchlistItem.ts_code,
            WatchlistItem.name,
        )
        .filter(WatchlistItem.monitoring_enabled.is_(True))
        .all()
    )
    for row in watchlist_rows:
        key = (str(row.user_id), row.ts_code)
        if key in merged:
            sources = merged[key]["sources"]
            assert isinstance(sources, set)
            sources.add("watchlist")
        else:
            merged[key] = {
                "user_id": key[0],
                "ts_code": row.ts_code,
                "name": row.name,
                "sources": {"watchlist"},
            }

    return [
        MonitoringSubject(
            user_id=str(values["user_id"]),
            ts_code=str(values["ts_code"]),
            name=str(values["name"]),
            sources=tuple(sorted(cast(set[str], values["sources"]))),
        )
        for values in merged.values()
    ]
