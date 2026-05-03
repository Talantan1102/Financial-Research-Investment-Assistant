"""TushareCache — sqlite-backed cache for tushare API responses.

Per-api TTL classification (financial永久 / anns 24h / daily 1h / default 1h).
Uses pickle to round-trip pd.DataFrame.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pickle
import sqlite3
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# TTL classification per spec § 3.3
_TTL_FINANCIAL_S = 365 * 24 * 3600  # 财务接口"永久" — 用 1 年代表
_TTL_ANNS_S = 24 * 3600
_TTL_DAILY_S = 3600
_TTL_DEFAULT_S = 3600

_FINANCIAL_APIS = frozenset(
    {"income", "balance_sheet", "cashflow", "fina_indicator", "stk_holdernumber"}
)
_ANNS_APIS = frozenset({"anns", "disclosure_date"})


def classify_ttl(api_name: str) -> int:
    """Return cache TTL in seconds for given api."""
    if api_name in _FINANCIAL_APIS:
        return _TTL_FINANCIAL_S
    if api_name in _ANNS_APIS:
        return _TTL_ANNS_S
    if api_name == "daily":
        return _TTL_DAILY_S
    return _TTL_DEFAULT_S


def _hash_params(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TushareCache:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init()

    def _init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tushare_cache (
                    api_name TEXT NOT NULL,
                    params_hash TEXT NOT NULL,
                    response_blob BLOB NOT NULL,
                    fetched_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (api_name, params_hash)
                )
                """
            )

    # ------------------------------------------------------------------ #
    # Sync helpers (run inside asyncio.to_thread)                          #
    # ------------------------------------------------------------------ #

    def _get_sync(self, api_name: str, params_hash: str, now: float) -> pd.DataFrame | None:
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "SELECT response_blob, expires_at FROM tushare_cache "
                "WHERE api_name = ? AND params_hash = ?",
                (api_name, params_hash),
            )
            row = cur.fetchone()
        if row is None:
            return None
        blob, expires_at = row
        if expires_at < now:
            return None
        try:
            df = pickle.loads(blob)  # noqa: S301
        except (pickle.UnpicklingError, EOFError, AttributeError, ValueError, TypeError) as exc:
            logger.warning(
                "TushareCache: corrupt blob for api=%s params_hash=%s — treating as cache miss (%s)",
                api_name,
                params_hash,
                exc,
            )
            return None
        if not isinstance(df, pd.DataFrame):
            logger.warning(
                "TushareCache: deserialized non-DataFrame for api=%s params_hash=%s (%s) — treating as cache miss",
                api_name,
                params_hash,
                type(df),
            )
            return None
        return df

    def _set_sync(
        self,
        api_name: str,
        params_hash: str,
        df: pd.DataFrame,
        now: float,
        ttl_s: float,
    ) -> None:
        # Serialize inside the thread so pickle.dumps (CPU-bound) doesn't block
        # the event loop — I-B carryover fix.
        blob = pickle.dumps(df)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tushare_cache "
                "(api_name, params_hash, response_blob, fetched_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (api_name, params_hash, blob, now, now + ttl_s),
            )

    # ------------------------------------------------------------------ #
    # Public async API                                                      #
    # ------------------------------------------------------------------ #

    async def get(self, api_name: str, params: dict) -> pd.DataFrame | None:
        async with self._lock:
            now = time.time()
            params_hash = _hash_params(params)
            return await asyncio.to_thread(self._get_sync, api_name, params_hash, now)

    async def set(self, api_name: str, params: dict, df: pd.DataFrame, ttl_s: float) -> None:
        async with self._lock:
            now = time.time()
            params_hash = _hash_params(params)
            await asyncio.to_thread(self._set_sync, api_name, params_hash, df, now, ttl_s)
