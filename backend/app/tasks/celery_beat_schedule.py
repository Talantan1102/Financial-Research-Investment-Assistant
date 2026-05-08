"""Celery beat schedule — spec § 4.2.

3 个定时任务:
- detection_cycle_30min:盘内时段(周一到周五 9:30-15:30 每 30 分钟)
- daily_full_scan:16:30 工作日收盘后兜底
- cleanup_old:凌晨 2 点清 retention
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
}
