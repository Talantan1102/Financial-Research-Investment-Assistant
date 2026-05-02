"""IngestState — sqlite 文件,(doc_id, content_hash) 增量去重."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class IngestState:
    """sqlite 持久化的 ingest 状态.

    Schema:
      ingested_docs (
          doc_id TEXT PRIMARY KEY,
          content_hash TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          chunk_count INTEGER NOT NULL
      )
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingested_docs (
                    doc_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    async def is_ingested(self, *, doc_id: str, content_hash: str) -> bool:
        return await asyncio.to_thread(self._is_ingested_sync, doc_id, content_hash)

    def _is_ingested_sync(self, doc_id: str, content_hash: str) -> bool:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT content_hash FROM ingested_docs WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
        return row is not None and row[0] == content_hash

    async def mark_ingested(self, *, doc_id: str, content_hash: str, chunk_count: int) -> None:
        await asyncio.to_thread(self._mark_ingested_sync, doc_id, content_hash, chunk_count)

    def _mark_ingested_sync(self, doc_id: str, content_hash: str, chunk_count: int) -> None:
        # ⚠️ Python 3.12+ datetime.utcnow() deprecated — 用 timezone-aware now
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ingested_docs
                   (doc_id, content_hash, ingested_at, chunk_count) VALUES (?, ?, ?, ?)""",
                (doc_id, content_hash, now, chunk_count),
            )
            conn.commit()

    async def clear_doc(self, doc_id: str) -> None:
        await asyncio.to_thread(self._clear_sync, doc_id)

    def _clear_sync(self, doc_id: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM ingested_docs WHERE doc_id = ?", (doc_id,))
            conn.commit()


def default_state_path() -> Path:
    """从 backend/app/kb/ingest/state.py 上溯到 backend/data/.ingest_state.sqlite."""
    return Path(__file__).resolve().parents[3] / "data" / ".ingest_state.sqlite"
