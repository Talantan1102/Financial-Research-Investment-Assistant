import uuid
import datetime
from sqlalchemy.orm import Session
from app.models.position_snapshot import PositionSnapshot


class PositionSnapshotRepo:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert(self, *, user_id, ts_code, snapshot_date, quantity, market_price, market_value, asset_class="stock") -> None:
        row = (self._s.query(PositionSnapshot)
               .filter_by(user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date).one_or_none())
        if row is None:
            row = PositionSnapshot(id=str(uuid.uuid4()), user_id=user_id, ts_code=ts_code, snapshot_date=snapshot_date)
            self._s.add(row)
        row.quantity = quantity
        row.market_price = market_price
        row.market_value = market_value
        row.asset_class = asset_class

    def list_for_user_date(self, *, user_id, snapshot_date):
        return (self._s.query(PositionSnapshot)
                .filter_by(user_id=user_id, snapshot_date=snapshot_date).all())

    def list_range(self, *, user_id, start_date, end_date):
        return (self._s.query(PositionSnapshot)
                .filter(PositionSnapshot.user_id == user_id,
                        PositionSnapshot.snapshot_date >= start_date,
                        PositionSnapshot.snapshot_date <= end_date)
                .order_by(PositionSnapshot.snapshot_date).all())
