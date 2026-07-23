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
    "paper_open_queued_morning": {
        "task": "app.tasks.paper_trading.open_queued_orders",
        "schedule": crontab(minute=30, hour=9, day_of_week="1-5"),
    },
    "paper_open_queued_afternoon": {
        "task": "app.tasks.paper_trading.open_queued_orders",
        "schedule": crontab(minute=0, hour=13, day_of_week="1-5"),
    },
    "paper_expire_day_orders": {
        "task": "app.tasks.paper_trading.expire_day_orders",
        "schedule": crontab(minute=1, hour=15, day_of_week="1-5"),
    },
    "paper_expire_overdue_orders": {
        "task": "app.tasks.paper_trading.expire_day_orders",
        "schedule": crontab(minute="*/10"),
    },
    "paper_release_t1_lots": {
        "task": "app.tasks.paper_trading.release_t1_lots",
        "schedule": crontab(minute=20, hour=9, day_of_week="1-5"),
    },
    "paper_scan_open_orders": {
        "task": "app.tasks.paper_trading.open_queued_orders",
        "schedule": crontab(minute="*", hour="9-14", day_of_week="1-5"),
    },
    "paper_reconcile_accounts": {
        "task": "app.tasks.paper_trading.reconcile_paper_accounts",
        "schedule": crontab(minute="*/5"),
    },
}
