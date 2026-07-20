"""Celery beat schedule for monitoring and memory maintenance."""

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
        "schedule": crontab(minute=0, hour=2),
    },
    "reconcile_pending_milvus": {
        "task": "app.tasks.memory.reconcile_pending_milvus",
        "schedule": crontab(minute="*/5"),
    },
    "posterior_calibration_weekly": {
        "task": "app.tasks.memory.posterior_calibration_weekly",
        "schedule": crontab(hour=3, minute=0, day_of_week=1),
        "options": {"queue": "memory_llm"},
    },
}
