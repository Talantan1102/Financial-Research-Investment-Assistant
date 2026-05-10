"""Celery beat schedule — spec § 4.2 + C.5 Plan 2B 末尾失败矩阵 行 5.

定时任务:
- detection_cycle_30min:盘内时段(周一到周五 9:30-15:30 每 30 分钟)
- daily_full_scan:16:30 工作日收盘后兜底
- cleanup_old:凌晨 2 点清 retention
- reconcile_pending_milvus: 每 5 分钟扫 pending_milvus_inserts retry (C.5 Plan 2B)
"""

from __future__ import annotations

from celery.schedules import crontab

beat_schedule = {
    "detection_cycle_30min": {
        "task": "app.tasks.monitoring.detection_cycle",
        "schedule": crontab(minute="*/30", hour="9-15", day_of_week="1-5"),
    },
    "daily_full_scan": {
        "task": "app.tasks.monitoring.daily_full_scan",
        "schedule": crontab(minute=30, hour=16, day_of_week="1-5"),
    },
    "cleanup_old": {
        "task": "app.tasks.monitoring.cleanup_old",
        "schedule": crontab(minute=0, hour=2),  # 每天 02:00
    },
    # C.5 Plan 2B: Milvus pending reconciliation (spec § 4 末尾矩阵 行 5)
    "reconcile_pending_milvus": {
        "task": "app.tasks.memory.reconcile_pending_milvus",
        "schedule": crontab(minute="*/5"),
    },
    # C.5 Plan 5: posterior calibration weekly (spec § 11 末尾 #3)
    # 周一 03:00 Asia/Shanghai (celery_app enable_utc=False, timezone="Asia/Shanghai")
    "posterior_calibration_weekly": {
        "task": "app.tasks.memory.posterior_calibration_weekly",
        "schedule": crontab(hour=3, minute=0, day_of_week=1),
        "options": {"queue": "memory_llm"},
    },
}
