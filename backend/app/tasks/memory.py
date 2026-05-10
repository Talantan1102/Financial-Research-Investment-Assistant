"""Plan 2B Celery memory tasks — Path B async + Milvus reconcile.

Spec § 4 Path B / § 4 末尾失败处理矩阵 / § 11 末尾 #4 跨轮抽取.

Plan 5 后续会在同文件加 batch_extractor / posterior_calibration 等 task,
本 plan 仅落 2 个范围内 task (per shared contract § 17 A1).

Per shared contract § 17 A2 (1), task name uses short form
`reconcile_pending_milvus` (not `reconcile_pending_milvus_inserts`) so beat
schedule routing stays simple.

Wiring (Task 5 + 6):
- `_build_path_b_runner()` is the unit-test patch point. Production wiring
  reads HierarchicalMemory + LLMExtractor + SessionLocal at call time so the
  Celery worker doesn't import them at module load (avoid heavy import chain
  in beat/worker boot).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from app.memory.path_b_runner import PathBRunner

_logger = logging.getLogger(__name__)

_VALID_TRIGGER_REASONS = frozenset({"session_closed", "idle_30min", "new_session_started"})


def _build_path_b_runner() -> PathBRunner:
    """Hook 点 — 测试 patch('app.tasks.memory._build_path_b_runner').

    Production wiring (lazy import to keep Celery boot light):
    - SessionLocal: app.core.database.SessionLocal
    - LLMExtractor: app.memory.extractor.LLMExtractor + LLMService from env
    - archival_insert_fn: HierarchicalMemory.archival_memory_insert (Plan 2A)

    实施期 fallback: HierarchicalMemory wiring 留 Plan 1 / Plan 8 dogfood 收束。
    本 task body 默认走"组装 fresh per task" 路径; lifespan singleton 接入是 Plan 8 work.
    """
    from app.core.database import SessionLocal
    from app.memory.extractor import LLMExtractor
    from app.memory.hierarchical import HierarchicalMemory
    from app.memory.path_b_runner import PathBRunner
    from app.services.embedding_factory import build_embedding_service_from_env
    from app.services.openai_client import build_llm_service_from_env

    llm = build_llm_service_from_env()
    embed = build_embedding_service_from_env()
    extractor = LLMExtractor(llm_client=llm)

    # archival_insert_fn 走真 hierarchical (Plan 2A 8 step pipeline).
    # NOTE: AGE / Milvus client wiring 留 lifespan singleton; 本 path 简化为
    # None / 默认值 — 真 production wiring 在 Plan 8 dogfood 收束.
    hierarchical = HierarchicalMemory(
        pg_session_factory=SessionLocal,
        age_executor=None,
        milvus_client=None,
        embed_service=embed,
        llm_extractor=extractor,
        llm_judge=None,
    )
    return PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=extractor,
        archival_insert_fn=hierarchical.archival_memory_insert,
    )


@celery_app.task(
    name="app.tasks.memory.extract_session_episodes_async",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    rate_limit="20/m",
    acks_late=True,
)
def extract_session_episodes_async(session_id: str, trigger_reason: str) -> dict[str, Any]:
    """Path B end-of-session 兜底批 trigger.

    trigger_reason 三档:
    - 'session_closed': WebSocket / chat 路由收到 close
    - 'idle_30min': idle watchdog beat 探测
    - 'new_session_started': 同 user 起新 session, 旧 session 触发批
    """
    if trigger_reason not in _VALID_TRIGGER_REASONS:
        raise ValueError(
            f"unknown trigger_reason {trigger_reason!r}, "
            f"expected one of {sorted(_VALID_TRIGGER_REASONS)}"
        )
    runner = _build_path_b_runner()
    result = asyncio.run(
        runner.run_for_session(session_id=UUID(session_id), trigger_reason=trigger_reason)
    )
    _logger.info(
        "path_b runner finished session=%s reason=%s scanned=%d facts=%d inserted=%d failures=%d",
        session_id,
        trigger_reason,
        result.episodes_scanned,
        result.facts_extracted,
        result.edges_inserted,
        result.failures,
    )
    return asdict(result)


@celery_app.task(
    name="app.tasks.memory.reconcile_pending_milvus",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    acks_late=True,
)
def reconcile_pending_milvus() -> dict[str, Any]:
    """Beat 每 5 分钟跑,扫 pending_milvus_inserts retry embed + insert.

    Task 6 填实 (本 stub 阶段保留 NotImplementedError 直到 Task 6 改写).
    """
    raise NotImplementedError("filled by Task 6")
