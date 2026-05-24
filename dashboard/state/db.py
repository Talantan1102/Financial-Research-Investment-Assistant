"""sqlite schema + connection。
v2:derived_snapshot / capability_override / decision_note / deep_cards (4 表)。
(flashcards / prefill_log 已在 Plan 1 退役)"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  refreshed_at TEXT NOT NULL,
  payload TEXT NOT NULL  -- JSON
);

CREATE TABLE IF NOT EXISTS capability_override (
  capability_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  set_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_note (
  decision_id TEXT PRIMARY KEY,
  note TEXT NOT NULL DEFAULT '',
  set_at TEXT NOT NULL
);

-- v2 schema: Harness Board Review Mode (spec § 6.1)
-- 实施时为简化 Pydantic roundtrip 改为单 JSON column,sqlite < 1M 数据性能足够
CREATE TABLE IF NOT EXISTS deep_cards (
  cap_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,           -- 全 DeepCard 序列化 JSON
  last_edited_at TEXT NOT NULL
);

"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
