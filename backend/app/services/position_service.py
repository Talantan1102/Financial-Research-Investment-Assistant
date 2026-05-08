"""PositionService — Position 读 API + 监控引擎写 quote 入口(决策 3)。

Read 路径:dashboard / 详情卡。
Write 路径:仅 update_quote(监控引擎调用),其他 Position 字段写入由 TradeService 拥有。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.position import Position


class PositionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: str) -> list[Position]:
        return (
            self._session.query(Position)
            .filter_by(user_id=user_id)
            .order_by(Position.ts_code.asc())
            .all()
        )

    def get(self, user_id: str, ts_code: str) -> Position | None:
        return (
            self._session.query(Position).filter_by(user_id=user_id, ts_code=ts_code).one_or_none()
        )

    def update_quote(
        self,
        *,
        user_id: str,
        ts_code: str,
        price: Decimal,
        at: datetime,
    ) -> None:
        pos = self.get(user_id=user_id, ts_code=ts_code)
        if pos is None:
            raise LookupError(f"no Position for user_id={user_id} ts_code={ts_code}")
        pos.last_quote_price = price  # type: ignore[assignment]
        pos.last_quote_at = at  # type: ignore[assignment]
        self._session.flush()
