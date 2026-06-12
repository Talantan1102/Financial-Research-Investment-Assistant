import datetime as dt

from app.services.position_snapshot_repo import PositionSnapshotRepo


def test_upsert_and_read_by_user(db_session):
    repo = PositionSnapshotRepo(db_session)
    d = dt.date(2026, 11, 14)
    repo.upsert(
        user_id=None,
        ts_code="600519.SH",
        snapshot_date=d,
        quantity=100,
        market_price=1650.0,
        market_value=165000.0,
        asset_class="stock",
    )
    db_session.flush()
    rows = repo.list_for_user_date(user_id=None, snapshot_date=d)
    assert len(rows) == 1
    assert rows[0].ts_code == "600519.SH"
    assert float(rows[0].market_value) == 165000.0
