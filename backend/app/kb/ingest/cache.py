"""ChunkEmbedCache — sqlite,chunk_text+model+dim → vector 缓存."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class ChunkEmbedCache:
    """sqlite 持久化的 embedding 缓存.

    Schema:
      embeddings (
          cache_key TEXT PRIMARY KEY,
          vector_json TEXT NOT NULL,
          model_name TEXT NOT NULL,
          dimension INTEGER NOT NULL,
          created_at TEXT NOT NULL
      )

    cache_key = sha256(chunk_text + model_name + str(dimension))
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self.stats = {"hits": 0, "misses": 0}

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    cache_key TEXT PRIMARY KEY,
                    vector_json TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _key(text: str, model: str, dim: int) -> str:
        return hashlib.sha256(f"{text}|||{model}|||{dim}".encode()).hexdigest()

    async def get(self, text: str, model_name: str, dimension: int) -> list[float] | None:
        key = self._key(text, model_name, dimension)
        row = await asyncio.to_thread(self._get_sync, key)
        if row is None:
            self.stats["misses"] += 1
            return None
        self.stats["hits"] += 1
        result: list[float] = json.loads(row)
        return result

    def _get_sync(self, key: str) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            r = conn.execute(
                "SELECT vector_json FROM embeddings WHERE cache_key = ?", (key,)
            ).fetchone()
        return r[0] if r else None

    async def set(self, text: str, model_name: str, dimension: int, vector: list[float]) -> None:
        key = self._key(text, model_name, dimension)
        await asyncio.to_thread(self._set_sync, key, json.dumps(vector), model_name, dimension)

    def _set_sync(self, key: str, vector_json: str, model: str, dim: int) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO embeddings
                   (cache_key, vector_json, model_name, dimension, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, vector_json, model, dim, now),
            )
            conn.commit()


def default_cache_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / ".embedding_cache.sqlite"
