import datetime
import uuid

from sqlalchemy.orm import Session

from app.models.position_snapshot import PositionSnapshot


class PositionSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(
        self,
        *,
        user_id: uuid.UUID | None,
        ts_code: str,
        snapshot_date: datetime.date,
        quantity: int,
        market_price: float,
        market_value: float,
        asset_class: str = "stock",
    ) -> None:
        row = (
            self._s.query(PositionSnapshot)
            .filter_by(user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date)
            .one_or_none()
        )
        if row is None:
            row = PositionSnapshot(
                id=str(uuid.uuid4()), user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date
            )
            self._s.add(row)
        row.quantity = quantity
        row.market_price = market_price
        row.market_value = market_value
        row.asset_class = asset_class

    def list_for_user_date(
        self, *, user_id: uuid.UUID | None, snapshot_date: datetime.date
    ) -> list[PositionSnapshot]:
        return (
            self._s.query(PositionSnapshot)
            .filter_by(user_id=user_id, snapshot_date=snapshot_date)
            .all()
        )

    def list_range(
        self,
        *,
        user_id: uuid.UUID | None,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[PositionSnapshot]:
        return (
            self._s.query(PositionSnapshot)
            .filter(
                PositionSnapshot.user_id == user_id,
                PositionSnapshot.snapshot_date >= start_date,
                PositionSnapshot.snapshot_date <= end_date,
            )
            .order_by(PositionSnapshot.snapshot_date)
            .all()
        )
