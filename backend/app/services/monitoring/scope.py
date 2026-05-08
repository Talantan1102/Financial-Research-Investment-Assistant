"""Monitoring subject schema + load helpers from Position."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.models.position import Position


class MonitoringSubject(BaseModel):
    """A (user_id, ts_code) pair to monitor, derived from non-empty positions."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    ts_code: str
    name: str


def load_active_subjects(session: Session) -> list[MonitoringSubject]:
    """Load all (user_id, ts_code) pairs with non-empty positions.

    Spec § 1 决策 2:scope = positions WHERE quantity > 0(去 monitoring_customers).
    """
    rows = (
        session.query(Position.user_id, Position.ts_code, Position.name)
        .filter(Position.quantity > 0)
        .all()
    )
    return [MonitoringSubject(user_id=str(r.user_id), ts_code=r.ts_code, name=r.name) for r in rows]
