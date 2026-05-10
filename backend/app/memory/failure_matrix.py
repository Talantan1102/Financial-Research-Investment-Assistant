"""Failure matrix — spec § 4 末尾 LLM extraction max-3 retry + alert.

强约束:不新建表,只用 chat_memory_episodes.extraction_metadata JSONB 字段累积
(契约 § 4 行 423-425).

Schema (JSONB):
{
  "retry_count": int,
  "failure_history": [
    {"at": iso8601, "failure_kind": "invalid_json"|"llm_timeout"|...,  "error_msg": str},
    ...
  ],
  "alerted_at": iso8601 | null
}
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.memory.models import ChatMemoryEpisode

_logger = logging.getLogger(__name__)

MAX_EXTRACTION_RETRIES = 3


def record_extraction_failure(
    session: Session,
    episode_id: UUID,
    failure_kind: str,
    error_msg: str,
) -> None:
    """累计写一次失败 entry 到 episode.extraction_metadata.

    不 commit — 调用方负责 commit/rollback.
    """
    ep = session.get(ChatMemoryEpisode, episode_id)
    if ep is None:
        _logger.warning("record_extraction_failure: episode %s not found", episode_id)
        return
    meta: dict[str, Any] = dict(ep.extraction_metadata or {})
    history = list(meta.get("failure_history") or [])
    history.append(
        {
            "at": datetime.now(tz=UTC).isoformat(),
            "failure_kind": failure_kind,
            "error_msg": error_msg[:500],
        }
    )
    meta["failure_history"] = history
    meta["retry_count"] = int(meta.get("retry_count") or 0) + 1
    ep.extraction_metadata = meta  # type: ignore[assignment]
    flag_modified(ep, "extraction_metadata")
    session.add(ep)


def should_retry_extraction(session: Session, episode_id: UUID) -> bool:
    """达到 MAX_EXTRACTION_RETRIES 或已 alerted 后返回 False.

    extracted_at 已设置 (已抽过) → False.
    """
    ep = session.get(ChatMemoryEpisode, episode_id)
    if ep is None:
        return False
    if ep.extracted_at is not None:
        return False  # 已抽过, 不需 retry
    meta = dict(ep.extraction_metadata or {})
    if meta.get("alerted_at"):
        return False
    return int(meta.get("retry_count") or 0) < MAX_EXTRACTION_RETRIES


def mark_episode_extraction_alerted(session: Session, episode_id: UUID) -> None:
    """达到 max retry 后调用 — 标 alerted_at, log error 给运维."""
    ep = session.get(ChatMemoryEpisode, episode_id)
    if ep is None:
        return
    meta: dict[str, Any] = dict(ep.extraction_metadata or {})
    meta["alerted_at"] = datetime.now(tz=UTC).isoformat()
    ep.extraction_metadata = meta  # type: ignore[assignment]
    flag_modified(ep, "extraction_metadata")
    session.add(ep)
    _logger.error(
        "memory extraction repeatedly failed for episode %s — manual triage; metadata: %s",
        episode_id,
        meta,
    )
