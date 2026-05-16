"""Celery app configuration — broker / queues / autodiscover.

Spec § 2.1 进程结构 / § 4.1 队列分配 / § 5 错误处理。
"""

from __future__ import annotations

import os

from celery import Celery
from kombu import Queue

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")

celery_app = Celery(
    "monitoring",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.monitoring",
        "app.tasks.memory",
        "app.tasks.chat_runner",
        "app.tasks.chat_stale_scanner",  # Plan 3 Task 6
    ],
)

celery_app.conf.update(
    # Spec § 5.2:acks_late + max_tasks_per_child 防泄漏 + prefetch=1 不丢
    task_acks_late=True,
    worker_max_tasks_per_child=100,
    worker_prefetch_multiplier=1,
    # Spec § 4.1:queues + C.5 Plan 2B/5 共建 memory_llm
    task_queues=(
        Queue("default", routing_key="default"),
        Queue("llm", routing_key="llm"),
        Queue("memory_llm", routing_key="memory_llm"),
    ),
    task_default_queue="default",
    task_default_routing_key="default",
    # Routing:llm 标记 task → llm 队列(per-task 装饰器也可,但全局映射更清晰)
    task_routes={
        "app.tasks.monitoring.generate_detail_card": {"queue": "llm"},
        # C.5 Plan 2B memory tasks
        "app.tasks.memory.extract_session_episodes_async": {"queue": "memory_llm"},
        "app.tasks.memory.reconcile_pending_milvus": {"queue": "memory_llm"},
        # C.5 Plan 5 memory tasks
        "app.tasks.memory.extract_episode_async": {"queue": "memory_llm"},
        "app.tasks.memory.extract_session_batch_async": {"queue": "memory_llm"},
        "app.tasks.memory.posterior_calibration_weekly": {"queue": "memory_llm"},
    },
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 测试 eager 开关
    task_always_eager=os.environ.get("CELERY_TASK_ALWAYS_EAGER") == "1",
    task_eager_propagates=os.environ.get("CELERY_TASK_EAGER_PROPAGATES") == "1",
)

# Wire beat schedule (imported here to avoid circular)
from app.tasks.celery_beat_schedule import beat_schedule  # noqa: E402

celery_app.conf.beat_schedule = beat_schedule
