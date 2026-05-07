from pathlib import Path

from dashboard.state.db import open_db
from dashboard.state.repositories import SnapshotRepo


def test_snapshot_save_get(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = SnapshotRepo(conn)
    assert repo.get_latest() is None
    repo.save("2026-05-07T00:00:00Z", {"total": 62, "total_lit": 35})
    latest = repo.get_latest()
    assert latest is not None
    assert latest["total"] == 62
    assert latest["refreshed_at"] == "2026-05-07T00:00:00Z"


def test_snapshot_overwrite(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = SnapshotRepo(conn)
    repo.save("t1", {"total": 60})
    repo.save("t2", {"total": 62})
    latest = repo.get_latest()
    assert latest is not None
    assert latest["total"] == 62
    cur = conn.execute("SELECT COUNT(*) AS n FROM derived_snapshot")
    assert cur.fetchone()["n"] == 1  # 全量替换语义
