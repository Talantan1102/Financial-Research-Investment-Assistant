"""Celery beat schedule — crontab fields verification."""

from __future__ import annotations

from celery.schedules import crontab


def test_beat_schedule_dict_loads():
    from app.tasks.celery_beat_schedule import beat_schedule

    assert "detection_cycle_30min" in beat_schedule
    assert "daily_full_scan" in beat_schedule
    assert "cleanup_old" in beat_schedule


def test_detection_cycle_crontab_trading_hours_only():
    from app.tasks.celery_beat_schedule import beat_schedule

    cron = beat_schedule["detection_cycle_30min"]["schedule"]
    assert isinstance(cron, crontab)
    # 验 9-15 hour (盘内时段) + 1-5 day_of_week(工作日) + */30 minute
    assert cron.day_of_week == {1, 2, 3, 4, 5}
    assert cron.hour == {9, 10, 11, 12, 13, 14, 15}
    assert cron.minute == {0, 30}


def test_daily_full_scan_crontab_1630_workdays():
    from app.tasks.celery_beat_schedule import beat_schedule

    cron = beat_schedule["daily_full_scan"]["schedule"]
    assert cron.minute == {30}
    assert cron.hour == {16}
    assert cron.day_of_week == {1, 2, 3, 4, 5}


def test_cleanup_old_crontab_0200_daily():
    from app.tasks.celery_beat_schedule import beat_schedule

    cron = beat_schedule["cleanup_old"]["schedule"]
    assert cron.minute == {0}
    assert cron.hour == {2}


def test_celery_beat_schedule_attached_to_app():
    from app.tasks.celery_app import celery_app
    from app.tasks.celery_beat_schedule import beat_schedule

    # celery_app.conf.beat_schedule 应该 == beat_schedule
    assert dict(celery_app.conf.beat_schedule or {}) == beat_schedule
