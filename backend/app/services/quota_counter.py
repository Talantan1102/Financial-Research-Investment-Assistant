"""QuotaCounter — SQLite-persisted monthly call counter.

Stores one row per increment; queries SUM where timestamp falls in current calendar month.
Multiple counters share the same SQLite file via the `name` column for isolation.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_quota_log (
    name TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_quota_name_ts ON search_quota_log(name, ts);
"""


def _month_start_ts(now_utc: datetime | None = None) -> int:
    now = now_utc or datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(month_start.timestamp())


class QuotaCounter:
    def __init__(self, *, db_path: Path, name: str, monthly_limit: int) -> None:
        if monthly_limit < 0:
            raise ValueError("monthly_limit must be non-negative")
        self._db_path = db_path
        self._name = name
        self._monthly_limit = monthly_limit
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def used_this_month(self) -> int:
        start_ts = _month_start_ts()
        with sqlite3.connect(str(self._db_path)) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM search_quota_log WHERE name = ? AND ts >= ?",
                (self._name, start_ts),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def remaining(self) -> int:
        return max(0, self._monthly_limit - self.used_this_month())

    def would_exceed(self) -> bool:
        return self.used_this_month() >= self._monthly_limit

    def increment(self) -> None:
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute(
                "INSERT INTO search_quota_log (name, ts) VALUES (?, ?)",
                (self._name, int(time.time())),
            )
            conn.commit()
