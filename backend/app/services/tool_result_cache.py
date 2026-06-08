"""ToolResultCache — per-tool TTL cache with user namespace.

Spec § 4.6 + § 6.4.  Solves B3 (staleness) + C1 (multi-turn coordination) +
G2 (user_id namespace prevents cross-user data leak).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_result_cache import ToolResultCacheRow

DEFAULT_TTL_BY_TOOL: dict[str, int] = {
    "get_stock_quote": 300,  # 5 min
    "get_financials": 86_400,  # 1 day
    "get_news": 3_600,  # 1 hour
    "web_search": 1_800,  # 30 min
    "kb_search": 86_400,  # 1 day
    "compare_stocks": 300,
}


class CacheHit(StrEnum):
    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"


class ToolResultCache:
    """PG-backed cache of tool execution results."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def cache_key(user_id: str, tool_name: str, args: dict[str, Any]) -> str:
        normalized = json.dumps(args, sort_keys=True)
        h = hashlib.sha256(normalized.encode()).hexdigest()[:32]
        return f"{user_id}::{tool_name}::{h}"

    async def get_or_compute(
        self,
        *,
        user_id: str,
        tool_name: str,
        args: dict[str, Any],
        compute_fn: Callable[[], Awaitable[dict[str, Any]]],
        ttl_seconds: int | None = None,
    ) -> tuple[dict[str, Any], CacheHit]:
        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_BY_TOOL.get(tool_name, 300)
        key = self.cache_key(user_id, tool_name, args)
        # expires_at 列是 DateTime(timezone=True),psycopg 读回 tz-aware;now 必须同为
        # tz-aware,否则 row.expires_at > now 抛 "can't compare offset-naive and
        # offset-aware datetimes"(旧 chat 图用 _NoOpCache 桩,从未触发;chatloop 首次真用)。
        now = datetime.now(UTC)

        async with self._session_factory() as sess:
            row = (
                await sess.execute(
                    select(ToolResultCacheRow).where(ToolResultCacheRow.cache_key == key)
                )
            ).scalar_one_or_none()

            if row and row.expires_at > now:
                return dict(row.result), CacheHit.HIT

            status = CacheHit.EXPIRED if row else CacheHit.MISS
            new_result = await compute_fn()
            await self._upsert(
                sess,
                key,
                user_id,
                tool_name,
                args,
                new_result,
                expires_at=now + timedelta(seconds=ttl),
            )
            await sess.commit()
            return new_result, status

    async def get_raw(self, cache_key: str) -> str | None:
        """Return the cached tool result for `cache_key` as a JSON string, or None.

        read_cached_result (chatloop control tool) reads the full original tool
        output by its cache_key — distinct from get_or_compute (which keys on
        user/tool/args and recomputes on miss/expiry). Here the cache_key is the
        already-known ref the model received in a downgrade placeholder, so we read
        by primary key directly. Expired rows still return their content: the model
        explicitly asked for this ref, and the content is the truthful last value
        (staleness is the model's concern, not ours here).

        Returns the `result` JSON column serialized with ensure_ascii=False so the
        text fed back through the tool message matches the original (CJK readable).
        """
        async with self._session_factory() as sess:
            row = (
                await sess.execute(
                    select(ToolResultCacheRow).where(ToolResultCacheRow.cache_key == cache_key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return json.dumps(row.result, ensure_ascii=False, sort_keys=True)

    async def _upsert(
        self,
        sess: AsyncSession,
        key: str,
        user_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        expires_at: datetime,
    ) -> None:
        stmt = (
            pg_insert(ToolResultCacheRow)
            .values(
                cache_key=key,
                user_id=user_id,
                tool_name=tool_name,
                args=args,
                result=result,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=["cache_key"],
                set_={"result": result, "expires_at": expires_at, "args": args},
            )
        )
        await sess.execute(stmt)
