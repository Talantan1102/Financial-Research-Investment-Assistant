"""PathBRunner — Path B end-of-session 兜底批主流程编排.

Spec § 4 Path B / § 11 末尾 #4 跨轮抽取.

依赖 (from Plan 1 / Plan 2A):
- app.memory.cross_turn_grouper.group_episodes / build_sliding_window (本 plan Task 2)
- app.memory.failure_matrix.record_extraction_failure / should_retry_extraction (本 plan Task 3)
- app.memory.extractor.LLMExtractor (Plan 2A) — extract_facts(turns, session_id, episode_ids)
- HierarchicalMemory.archival_memory_insert (Plan 2A) — 通过 archival_insert_fn DI 注入
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.memory.cross_turn_grouper import (
    build_sliding_window,
    group_episodes,
)
from app.memory.failure_matrix import (
    record_extraction_failure,
    should_retry_extraction,
)
from app.memory.models import ChatMemoryEdge, ChatMemoryEpisode

_logger = logging.getLogger(__name__)


@dataclass
class PathBRunResult:
    session_id: str
    trigger_reason: str
    episodes_scanned: int
    chunks: int
    facts_extracted: int
    edges_inserted: int
    failures: int
    skipped: int


class _LLMExtractorLike(Protocol):
    async def extract_facts(
        self,
        turns: list[dict[str, Any]],
        session_id: UUID,
        episode_ids: list[UUID],
    ) -> Any:
        """Returns either list[ExtractionOutput] (per § 17 A2 (4)) or
        dict {entities, edges} (legacy mock shape used in unit tests)."""


ArchivalInsertFn = Callable[..., Awaitable[ChatMemoryEdge | None]]
SessionFactory = Callable[[], Session]


def _trivial_skip_gate(ep: ChatMemoryEpisode) -> tuple[bool, str]:
    """Plan 5 not yet ship'd → trivial fallback.

    Only skip empty episodes; real skip-gate (Plan 5) does keyword + length
    heuristic. Until Plan 5 ships, default to "let LLM see everything"
    (per scope note: Plan 2B 软降级时不能过度跳过, 否则跨轮抽取被阻断).
    """
    txt = ep.user_message_text or ""
    text_str = str(txt)
    if len(text_str.strip()) == 0:
        return (True, "trivial-stub: empty text")
    return (False, "")


def _resolve_skip_gate() -> Callable[[ChatMemoryEpisode], tuple[bool, str]]:
    """Soft-import Plan 5 skip_gate.should_skip_extraction; fall back if absent.

    Plan 5 ships `app.memory.skip_gate.should_skip_extraction`. Until then,
    use the trivial fallback. The dynamic import keeps this Plan 2B file
    decoupled from a Plan 5 module that may not exist yet.
    """
    import importlib

    try:
        mod = importlib.import_module("app.memory.skip_gate")
    except ImportError:
        return _trivial_skip_gate
    fn = getattr(mod, "should_skip_extraction", None)
    if fn is None:
        return _trivial_skip_gate
    return cast(Callable[[ChatMemoryEpisode], tuple[bool, str]], fn)


# 策略 A 持仓边界(2026-06-08 对话流评估持仓仲裁族冒烟驱动):持仓事实(持有/卖出)
# 的唯一真相来源是持仓监控模块,口头持仓陈述不入记忆图,避免与模块形成双真相源。
# 记忆只留观点/偏好/研究。开启后过滤掉这些 rel_type 的边。
HOLDING_REL_TYPES = frozenset({"HOLDS", "SOLD"})


def filter_holding_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剔除持仓类边(策略 A),保留观点/偏好/研究类边。"""
    return [e for e in edges if e.get("rel_type") not in HOLDING_REL_TYPES]


def stamp_event_time(edge: dict[str, Any], event_dt: datetime) -> dict[str, Any]:
    """用对话发生日(episode created_at)当 valid_from,修 LLM 把 valid_from
    打成默认值的真信号(2026-06-08 对话流评估时间维度冒烟发现)。返回新 dict,不改入参。
    """
    return {**edge, "valid_from": event_dt}


class PathBRunner:
    """Path B 编排器 — Celery task 调用入口在 app.tasks.memory."""

    def __init__(
        self,
        session_factory: SessionFactory,
        llm_extractor: _LLMExtractorLike,
        archival_insert_fn: ArchivalInsertFn,
        exclude_holdings: bool = False,
        stamp_event_time_from_episode: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._extractor = llm_extractor
        self._archival_insert = archival_insert_fn
        # 策略 A:持仓陈述不入记忆图(默认关,保持现状;评估/启用持仓模块的部署开启)
        self._exclude_holdings = exclude_holdings
        # 事件时间:用 episode created_at 当 valid_from(默认关;修 LLM 打默认时间戳)
        self._stamp_event_time = stamp_event_time_from_episode

    async def run_for_session(
        self,
        session_id: UUID,
        trigger_reason: str,
    ) -> PathBRunResult:
        """主流程: 扫 → group → window → extract → insert → mark."""
        sess: Session = self._session_factory()
        try:
            episodes = self._scan_unextracted(sess, session_id)
            scanned = len(episodes)
            if scanned == 0:
                return PathBRunResult(
                    session_id=str(session_id),
                    trigger_reason=trigger_reason,
                    episodes_scanned=0,
                    chunks=0,
                    facts_extracted=0,
                    edges_inserted=0,
                    failures=0,
                    skipped=0,
                )

            # 失败矩阵 行 1: max-3 retry — 过滤已 alerted / 已达 max episode
            episodes = [e for e in episodes if should_retry_extraction(sess, _uuid(e.episode_id))]
            chunks = group_episodes(episodes)

            skip_gate = _resolve_skip_gate()

            facts_total = 0
            inserted_total = 0
            failures = 0
            skipped = 0

            for chunk in chunks:
                # chunk 内全 skip → 跳整 chunk
                gate_results = [skip_gate(ep) for ep in chunk.episodes]
                if all(gr[0] for gr in gate_results):
                    skipped += len(chunk.episodes)
                    now = datetime.now(tz=UTC)
                    for ep, (_skip, reason) in zip(chunk.episodes, gate_results, strict=True):
                        ep.extracted_at = now  # type: ignore[assignment]
                        ep.extracted_by = "eos_batch_skip_gate"  # type: ignore[assignment]
                        meta: dict[str, Any] = dict(ep.extraction_metadata or {})
                        meta["skipped_reason"] = reason
                        meta["trigger_reason"] = trigger_reason
                        ep.extraction_metadata = meta  # type: ignore[assignment]
                        flag_modified(ep, "extraction_metadata")
                        sess.add(ep)
                    sess.commit()
                    continue

                # build 5-turn window + LLM extract
                window = build_sliding_window(chunk, window=5)
                ep_ids = [_uuid(ep.episode_id) for ep in chunk.episodes]
                try:
                    extracted = await self._extractor.extract_facts(
                        turns=window, session_id=session_id, episode_ids=ep_ids
                    )
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    _logger.warning(
                        "extraction failed for chunk in session %s: %s",
                        session_id,
                        exc,
                    )
                    for ep in chunk.episodes:
                        record_extraction_failure(
                            sess,
                            _uuid(ep.episode_id),
                            failure_kind="invalid_json",
                            error_msg=str(exc),
                        )
                    sess.commit()
                    continue

                # 走 Plan 2A archival_memory_insert pipeline
                edges_payload = _coerce_edges(extracted)
                if self._exclude_holdings:
                    edges_payload = filter_holding_edges(edges_payload)  # 策略 A:持仓不入图
                facts_total += len(edges_payload)
                user_id_val: UUID = _uuid(chunk.episodes[0].user_id)
                inserted_in_chunk = 0
                insert_errors: list[dict[str, str]] = []
                for edge in edges_payload:
                    src_eid = edge.get("source_episode_id")
                    target_eid: UUID = (
                        UUID(src_eid) if src_eid else _uuid(chunk.episodes[-1].episode_id)
                    )
                    if self._stamp_event_time:
                        target_ep = next(
                            (e for e in chunk.episodes if _uuid(e.episode_id) == target_eid),
                            chunk.episodes[-1],
                        )
                        edge = stamp_event_time(edge, _coerce_dt(target_ep.created_at))
                    try:
                        await self._archival_insert(
                            user_id=user_id_val,
                            content=edge,
                            reasoning=edge.get("reasoning", ""),
                            importance=float(edge.get("importance", 0.5)),
                            evidence_quote=edge.get("evidence_quote")
                            or chunk.episodes[-1].user_message_text
                            or "",
                            episode_id=target_eid,
                        )
                        inserted_in_chunk += 1
                    except Exception as exc:  # noqa: BLE001 — one bad edge must not drop the rest
                        # C3: was a silent warning that hid the KeyError/AttributeError
                        # contract bugs. Log with traceback so real insert failures
                        # (Milvus/AGE/DB down) are diagnosable, and still record them.
                        _logger.error("archival_insert failed in path_b: %s", exc, exc_info=True)
                        insert_errors.append({"error": str(exc)[:300]})

                inserted_total += inserted_in_chunk

                # mark extracted (Step 8 — even if some inserts failed; failures
                # captured in metadata.insert_failures so re-extraction won't loop)
                now = datetime.now(tz=UTC)
                for ep in chunk.episodes:
                    ep.extracted_at = now  # type: ignore[assignment]
                    ep.extracted_by = "eos_batch"  # type: ignore[assignment]
                    meta = dict(ep.extraction_metadata or {})
                    meta["trigger_reason"] = trigger_reason
                    meta["edges_inserted"] = inserted_in_chunk
                    meta["facts_seen"] = len(edges_payload)
                    if insert_errors:
                        prev = list(meta.get("insert_failures") or [])
                        meta["insert_failures"] = prev + insert_errors
                    ep.extraction_metadata = meta  # type: ignore[assignment]
                    flag_modified(ep, "extraction_metadata")
                    sess.add(ep)
                sess.commit()

            return PathBRunResult(
                session_id=str(session_id),
                trigger_reason=trigger_reason,
                episodes_scanned=scanned,
                chunks=len(chunks),
                facts_extracted=facts_total,
                edges_inserted=inserted_total,
                failures=failures,
                skipped=skipped,
            )
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    @staticmethod
    def _scan_unextracted(session: Session, session_id: UUID) -> list[ChatMemoryEpisode]:
        rows = (
            session.query(ChatMemoryEpisode)
            .filter(
                ChatMemoryEpisode.session_id == session_id,
                ChatMemoryEpisode.extracted_at.is_(None),
            )
            .order_by(ChatMemoryEpisode.episode_index.asc())
            .all()
        )
        return rows


def _uuid(val: Any) -> UUID:
    """Coerce SQLAlchemy column value to UUID (supports already-UUID + str)."""
    if isinstance(val, UUID):
        return val
    return UUID(str(val))


# Well-known implicit graph-root entity. The extractor prompt fixes the user's
# label+type to "User" ("User: 固定 'User'") and does NOT re-list it in `entities`,
# so edges sourced at the user (e.g. User HOLDS Stock) carry no co-extracted entity
# to resolve the type from — default it here.
_USER_ENTITY = "User"


def _coerce_dt(val: Any) -> datetime:
    """Coerce an ISO-8601 string (or datetime) to a tz-aware datetime (UTC if naive)."""
    dt = val if isinstance(val, datetime) else datetime.fromisoformat(str(val))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _entity_type_map(entities: Any) -> dict[str, str]:
    """Build {entity_label: entity_type} from co-extracted entities (pydantic or dict)."""
    out: dict[str, str] = {}
    for ent in entities or []:
        if hasattr(ent, "entity_label"):
            out[ent.entity_label] = ent.entity_type
        elif isinstance(ent, dict) and "entity_label" in ent:
            out[ent["entity_label"]] = ent.get("entity_type", "")
    return out


def _coerce_edges(extracted: Any) -> list[dict[str, Any]]:
    """Accept both shapes for cross-turn extractor return:

    - dict {"entities": [...], "edges": [...]} (legacy mock / pre-§17 shape)
    - list[ExtractionOutput] (per shared contract § 17 A2 (4) final)

    Returns flat list of edge dicts in the EXACT shape archival_memory_insert
    reads as `content`: rel_type / source_entity_type / source_label /
    target_entity_type / target_label / valid_from(datetime) / valid_to / ...

    C3: ExtractedEdge only carries source_label/target_label and str valid_from;
    the *_entity_type keys come from the co-extracted entities (discarded by the
    old impl → KeyError) and valid_from must be a datetime (old str → AttributeError
    on .isoformat()). Both are injected/coerced here, at the boundary. Edges whose
    entity types can't be resolved or whose dates are unparseable are skipped+logged
    (fail-loud, not silently dropped into a half-written batch).
    """
    # Normalize to (entities, edges) groups regardless of input shape.
    groups: list[tuple[Any, Any]] = []
    if isinstance(extracted, dict):
        groups.append((extracted.get("entities"), extracted.get("edges")))
    elif isinstance(extracted, list):
        for item in extracted:
            ents = getattr(item, "entities", None)
            edgs = getattr(item, "edges", None)
            if isinstance(item, dict):
                ents = item.get("entities") if ents is None else ents
                edgs = item.get("edges") if edgs is None else edgs
            groups.append((ents, edgs))
    else:
        return []

    out: list[dict[str, Any]] = []
    for entities, edges in groups:
        type_map = _entity_type_map(entities)
        for edge in edges or []:
            if hasattr(edge, "model_dump"):
                ed: dict[str, Any] = edge.model_dump()
            elif isinstance(edge, dict):
                ed = dict(edge)
            else:
                continue

            src_label = ed.get("source_label")
            tgt_label = ed.get("target_label")
            src_type = ed.get("source_entity_type") or type_map.get(src_label or "")
            tgt_type = ed.get("target_entity_type") or type_map.get(tgt_label or "")
            # "User" is the implicit root entity (not re-listed in entities) — default its type.
            if not src_type and src_label == _USER_ENTITY:
                src_type = _USER_ENTITY
            if not tgt_type and tgt_label == _USER_ENTITY:
                tgt_type = _USER_ENTITY
            if not src_type or not tgt_type:
                _logger.error(
                    "path_b _coerce_edges: cannot resolve entity_type for edge "
                    "%s -> %s (src_type=%r tgt_type=%r) — skipping",
                    src_label,
                    tgt_label,
                    src_type,
                    tgt_type,
                )
                continue
            ed["source_entity_type"] = src_type
            ed["target_entity_type"] = tgt_type

            try:
                ed["valid_from"] = _coerce_dt(ed.get("valid_from"))
                if ed.get("valid_to") is not None:
                    ed["valid_to"] = _coerce_dt(ed.get("valid_to"))
            except (ValueError, TypeError) as exc:
                _logger.error(
                    "path_b _coerce_edges: unparseable valid_from/valid_to %r/%r: %s — skipping",
                    ed.get("valid_from"),
                    ed.get("valid_to"),
                    exc,
                )
                continue
            out.append(ed)
    return out
