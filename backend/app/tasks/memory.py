"""Plan 2B Celery memory tasks — Path B async + Milvus reconcile.

Spec § 4 Path B / § 4 末尾失败处理矩阵 / § 11 末尾 #4 跨轮抽取.

Plan 5 后续会在同文件加 batch_extractor / posterior_calibration 等 task,
本 plan 仅落 2 个范围内 task (per shared contract § 17 A1).

Per shared contract § 17 A2 (1), task name uses short form
`reconcile_pending_milvus` (not `reconcile_pending_milvus_inserts`) so beat
schedule routing stays simple.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tasks.celery_app import celery_app

_logger = logging.getLogger(__name__)


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

    trigger_reason 三档:'session_closed' / 'idle_30min' / 'new_session_started'.

    Task 5 填实 (本 Task 1 留 NotImplementedError stub).
    """
    raise NotImplementedError("filled by Task 5")


@celery_app.task(
    name="app.tasks.memory.reconcile_pending_milvus",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
    acks_late=True,
)
def reconcile_pending_milvus() -> dict[str, Any]:
    """Beat 每 5 分钟跑,扫 pending_milvus_inserts retry embed + insert.

    Task 6 填实 (本 Task 1 留 NotImplementedError stub).
    """
    raise NotImplementedError("filled by Task 6")
