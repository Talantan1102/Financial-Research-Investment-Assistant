"""sqlite schema + connection。M1 derived_snapshot;M2 加 capability_override;M3 加 decision_note。"""

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

CREATE TABLE IF NOT EXISTS flashcards (
  id TEXT PRIMARY KEY,             -- f"{cap_id}::{template_kind}"
  cap_id TEXT NOT NULL,
  template_kind TEXT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  srs_state TEXT NOT NULL,         -- JSON
  created_at TEXT NOT NULL,
  last_reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_flashcards_cap_id ON flashcards(cap_id);
CREATE INDEX IF NOT EXISTS idx_flashcards_next_review
  ON flashcards(json_extract(srs_state, '$.next_review_at'));

CREATE TABLE IF NOT EXISTS prefill_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cap_id TEXT NOT NULL,
  field_name TEXT NOT NULL,
  status TEXT NOT NULL,            -- 'success' | 'rejected_quote' | 'llm_error' | 'skipped'
  detail TEXT,
  ran_at TEXT NOT NULL
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
