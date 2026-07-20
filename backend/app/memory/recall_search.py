"""Tier 3 recall — semantic search over RunMessage history.

Lightweight implementation: in-memory cosine over qwen-embedded user messages
capped at last 5000 messages per user (created_at desc).

Performance escalation (dedicated Milvus collection) deferred until > 5000
messages/user becomes a real bottleneck. Current scale (个人 portfolio,
single-digit users) sits comfortably under cap. Contracts § 11 矩阵留口子.

Plan 4 ship — implements stub raise NotImplementedError that Plan 1 left in
HierarchicalMemory.recall_memory_search.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_MAX_USER_MESSAGES_SCAN = 5000


class _EmbedServiceLike(Protocol):
    """Minimal subset of EmbeddingService.embed needed by RecallSearcher.

    EmbeddingService Protocol (app.services.embedding_service) takes
    list[str] and returns list[list[float]]. We pass [query] + texts in one
    batch when economical, otherwise separate batches.
    """

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RecallSearcher:
    """Tier 3 chat history semantic search.

    Args (DI):
        session_factory: () -> sync SQLAlchemy Session (same shape as
            HierarchicalMemory's pg_session_factory).
        embed_service: EmbeddingService Protocol implementation (qwen v3 prod /
            mock in tests).
    """

    def __init__(self, session_factory: Any, embed_service: _EmbedServiceLike) -> None:
        self._sf = session_factory
        self._embed = embed_service

    async def search(
        self,
        user_id: UUID,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Return top-k most semantically similar chat messages for given user.

        Returns list of dicts with keys:
            message_id, session_id, role, content, created_at (iso str), similarity.

        Empty query / no messages → []. User isolation enforced via JOIN on
        RunSession.created_by_user_id (messages intentionally carry no user id).
        """
        if not query or not query.strip():
            return []

        session = self._sf()
        try:
            rows = self._fetch_user_messages(session, user_id)
        finally:
            session.close()

        if not rows:
            return []

        texts = [(r["content"] or "") for r in rows]
        # Embed query + all messages in a single call for efficiency where
        # possible. Plan 5 prompt cache + per-user EmbedCache will optimize
        # repeat scans; Plan 4 keeps it minimal.
        all_embeds = await self._embed.embed([query, *texts])
        if not all_embeds or len(all_embeds) != len(texts) + 1:
            logger.warning(
                "recall_search: embed returned %d vectors, expected %d",
                len(all_embeds) if all_embeds else 0,
                len(texts) + 1,
            )
            return []
        query_vec = all_embeds[0]
        doc_vecs = all_embeds[1:]

        scored: list[tuple[float, dict[str, Any]]] = []
        for vec, msg in zip(doc_vecs, rows, strict=True):
            sim = _cosine(query_vec, vec)
            scored.append((sim, msg))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = scored[:k]
        out: list[dict[str, Any]] = []
        for sim, msg in top:
            created = msg.get("created_at")
            out.append(
                {
                    "message_id": str(msg["id"]),
                    "session_id": str(msg["session_id"]),
                    "role": msg["role"],
                    "content": msg["content"],
                    "created_at": (created.isoformat() if created is not None else None),
                    "similarity": float(sim),
                }
            )
        return out

    @staticmethod
    def _fetch_user_messages(session: Session, user_id: UUID) -> list[dict[str, Any]]:
        """Fetch up to _MAX_USER_MESSAGES_SCAN messages for user, newest first.

        Uses raw SQL with explicit column list to avoid coupling to ORM
        ORM schema drift (test PG may have older schema than backend models).
        """
        sql = text(
            """
            SELECT rm.id AS id,
                   rm.session_id AS session_id,
                   rm.role AS role,
                   rm.content AS content,
                   rm.created_at AS created_at
            FROM run_messages rm
            JOIN run_sessions rs ON rm.session_id = rs.id
            WHERE rs.created_by_user_id = :uid
            ORDER BY rm.created_at DESC
            LIMIT :lim
            """
        )
        result = session.execute(sql, {"uid": str(user_id), "lim": _MAX_USER_MESSAGES_SCAN})
        rows = [dict(row._mapping) for row in result.fetchall()]
        return rows


def _cosine(a: list[float], b: list[float]) -> float:
    """Pure cosine similarity. Returns 0 when either vector has zero norm."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
