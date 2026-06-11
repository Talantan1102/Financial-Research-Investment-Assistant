"""C.5 memory Celery tasks — Path B async + Milvus reconcile + Plan 5 cost opt + posterior calibration.

Spec § 4 Path B / § 4 末尾失败处理矩阵 / § 11 末尾 #3 + #4.

Per shared contract § 17 A1, Plan 2B 创建本文件 + 2 task stub
(extract_session_episodes_async / reconcile_pending_milvus); Plan 5 Edit
本文件加 task body for 3 个新 task: extract_episode_async /
extract_session_batch_async / posterior_calibration_weekly.

Per shared contract § 17 A2 (1), task name uses short form
`reconcile_pending_milvus` (not `reconcile_pending_milvus_inserts`) so beat
schedule routing stays simple.

Wiring strategy:
- `_build_path_b_runner()` / `_build_calibration_*()` 是 unit-test patch point.
  Production wiring 在 task body 内 lazy import 重 dep (HierarchicalMemory /
  PathBRunner / SessionLocal / Milvus client) — Celery worker / beat 启动不
  hard-import 这些 (避免 import chain 在 boot 期 fail).
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

_VALID_TRIGGER_REASONS = frozenset(
    {"session_closed", "idle_30min", "new_session_started", "post_turn"}
)


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
    from app.memory.llm_service_adapter import MemoryLLMClientAdapter
    from app.memory.path_b_runner import PathBRunner
    from app.services.embedding_factory import build_embedding_service_from_env
    from app.services.openai_client import build_llm_service_from_env

    llm = build_llm_service_from_env()
    embed = build_embedding_service_from_env()
    # 2026-06-05 对话流评估冒烟发现 #3:LLMExtractor 期望 async
    # chat(prompt, system, ...) -> str 协议,直接塞 LLMService 会在真实 LLM 下
    # TypeError 全灭(被 failure_matrix 吞成 retry 耗尽)——必须过适配器。
    extractor = LLMExtractor(llm_client=MemoryLLMClientAdapter(llm, tier="fast"))

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


def _run_milvus_reconciliation() -> Any:
    """Hook 点 — 测试 patch('app.tasks.memory._run_milvus_reconciliation').

    Production wiring (lazy import):
    - SessionLocal: app.core.database.SessionLocal
    - embed_fn: build qwen embed via build_embedding_service_from_env().embed
    - milvus_client: pymilvus MilvusClient pointing at MILVUS_HOST/PORT
    """
    import os

    from pymilvus import MilvusClient

    from app.core.database import SessionLocal
    from app.memory.reconciliation import reconcile_pending_milvus_inserts
    from app.services.embedding_factory import build_embedding_service_from_env

    embed_service = build_embedding_service_from_env()

    async def _embed_one(text_input: str) -> list[float]:
        vecs = await embed_service.embed([text_input])
        return vecs[0] if vecs else []

    host = os.environ.get("MILVUS_HOST", "127.0.0.1")
    port = int(os.environ.get("MILVUS_PORT", "19530"))
    milvus_client = MilvusClient(uri=f"http://{host}:{port}")

    return reconcile_pending_milvus_inserts(
        session_factory=SessionLocal,
        embed_fn=_embed_one,
        milvus_client=milvus_client,
    )


@celery_app.task(
    name="app.tasks.memory.reconcile_pending_milvus",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    acks_late=True,
)
def reconcile_pending_milvus() -> dict[str, Any]:
    """Beat 每 5 分钟跑,扫 pending_milvus_inserts retry embed + insert."""
    result = _run_milvus_reconciliation()
    out = {
        "processed": result.processed,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "alerted": result.alerted,
    }
    _logger.info(
        "milvus reconciliation finished: processed=%d succeeded=%d failed=%d alerted=%d",
        result.processed,
        result.succeeded,
        result.failed,
        result.alerted,
    )
    return out


# ===========================================================================
# Plan 5 — Cost optimization async tasks + posterior calibration
# ===========================================================================


def _run_extract_episode(episode_id: str) -> dict[str, Any]:
    """Hook 点 — 测试 patch('app.tasks.memory._run_extract_episode').

    Plan 5 范围: task wiring + retry policy.
    Plan 8 dogfood 收束: 真实 body 接 PathBRunner.run_for_session(单 episode 模式)
    或 LLMExtractor + skip_gate 走 path A. Plan 5 阶段 placeholder.
    """
    _logger.info("extract_episode placeholder — Plan 8 dogfood 接 body, episode_id=%s", episode_id)
    return {"episode_id": episode_id, "status": "placeholder"}


def _run_extract_session_batch(session_id: str) -> dict[str, Any]:
    """Hook 点 — 测试 patch('app.tasks.memory._run_extract_session_batch').

    End-of-session batch — 调 BatchExtractor.extract_batch.
    Plan 5 范围: task wiring; Plan 8 dogfood 接 BatchExtractor + archival_insert 真路径.
    """
    _logger.info("extract_session_batch placeholder, session_id=%s", session_id)
    return {"session_id": session_id, "status": "placeholder"}


def _build_calibration_reader() -> Any:
    """Hook 点 — Plan 3 ship retrieval_logs/feedback 表已就绪.

    真 SQL reader 走 thin adapter on chat_memory_retrieval_logs +
    chat_memory_retrieval_feedback (契约 § 17 A4). Plan 8 dogfood 收束接真 SQL;
    Plan 5 阶段返回空 reader (跑成功无 update).
    """
    from collections.abc import Iterable
    from datetime import datetime

    from app.memory.posterior_calibration import EdgeCalibrationInput

    class _EmptyReader:
        def fetch_edge_metrics(
            self, since: datetime, until: datetime
        ) -> Iterable[EdgeCalibrationInput]:
            return iter([])

    return _EmptyReader()


def _build_calibration_updater() -> Any:
    """Hook 点 — 真 updater 走 SQLAlchemy session.update edge.importance.

    Plan 5 阶段 noop (无 reader 输入即无 update). Plan 8 dogfood 接 SessionLocal.
    """

    class _NoopUpdater:
        def update_importance(self, edge_id: UUID, new_importance: float) -> None:
            _logger.info(
                "calibration update placeholder edge_id=%s new=%.2f", edge_id, new_importance
            )

    return _NoopUpdater()


def _write_calibration_audit(run: Any) -> None:
    """Hook 点 — 写 chat_memory_calibration_runs audit row.

    Plan 5 阶段 placeholder log; Plan 8 dogfood 接 SessionLocal:
        session = SessionLocal(); session.add(run); session.commit(); session.close().
    """
    _logger.info(
        "calibration audit: run_id=%s scanned=%d promoted_high=%d promoted_med=%d "
        "override_low=%d status=%s",
        run.run_id,
        run.scanned_edges,
        run.promoted_to_high,
        run.demoted_to_medium,
        run.overridden_to_low,
        run.status,
    )


def _run_posterior_calibration_weekly() -> dict[str, Any]:
    """spec § 11 末尾 #3: 周 job 反向调 importance + 写 audit 表.

    Plan 5 task body: 调 run_weekly_calibration + 写 ChatMemoryCalibrationRun audit.
    """
    from app.memory.posterior_calibration import run_weekly_calibration
    from app.models.memory_calibration import ChatMemoryCalibrationRun

    reader = _build_calibration_reader()
    updater = _build_calibration_updater()

    result = run_weekly_calibration(reader=reader, updater=updater)

    audit = ChatMemoryCalibrationRun(
        run_id=result.run_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        scanned_edges=result.scanned_edges,
        promoted_to_high=result.promoted_to_high,
        demoted_to_medium=result.demoted_to_medium,
        overridden_to_low=result.overridden_to_low,
        status="success",
    )
    _write_calibration_audit(audit)

    return {
        "scanned_edges": result.scanned_edges,
        "promoted_to_high": result.promoted_to_high,
        "promoted_to_medium": result.demoted_to_medium,
        "overridden_to_low": result.overridden_to_low,
        "status": "success",
    }


@celery_app.task(
    name="app.tasks.memory.extract_episode_async",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    rate_limit="20/m",
    acks_late=True,
)
def extract_episode_async(episode_id: str) -> dict[str, Any]:
    """单 episode 异步抽取(spec § 4 优化 #4 / 失败矩阵 max 3)."""
    return _run_extract_episode(episode_id)


@celery_app.task(
    name="app.tasks.memory.extract_session_batch_async",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    rate_limit="10/m",
    acks_late=True,
)
def extract_session_batch_async(session_id: str) -> dict[str, Any]:
    """End-of-session 5-episode batch 抽取(spec § 4 优化 #2)."""
    return _run_extract_session_batch(session_id)


@celery_app.task(
    name="app.tasks.memory.posterior_calibration_weekly",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=1,
    acks_late=True,
)
def posterior_calibration_weekly() -> dict[str, Any]:
    """周 job — 三档反向调(spec § 11 末尾 #3)."""
    return _run_posterior_calibration_weekly()
