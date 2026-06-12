"""Celery task: snapshot_portfolios — 收盘后为所有活跃持仓存一张每日快照.

Beat 计划: 16:35 工作日(与 daily_full_scan 16:30 错开 5 分钟让行情刷新先跑).
Task 拿 positions WHERE quantity > 0, 用 last_quote_price(若为空则 avg_cost)
算 market_value, 调 PositionSnapshotRepo.upsert 写入 position_snapshots 表.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.position import Position
from app.services.position_snapshot_repo import PositionSnapshotRepo
from app.tasks.celery_app import celery_app

_logger = logging.getLogger(__name__)


def _get_session() -> Session:
    """Hook point: tests patch this to inject the db_session fixture."""
    return SessionLocal()


def _run_snapshot() -> dict[str, Any]:
    """Core logic extracted so tests can call it with an injected session."""
    session = _get_session()
    today = datetime.date.today()
    repo = PositionSnapshotRepo(session)
    count = 0

    try:
        positions = (
            session.query(Position)
            .filter(Position.quantity > 0)
            .all()
        )

        for pos in positions:
            price = float(pos.last_quote_price) if pos.last_quote_price is not None else float(pos.avg_cost)
            market_value = pos.quantity * price

            repo.upsert(
                user_id=pos.user_id,
                ts_code=pos.ts_code,
                snapshot_date=today,
                quantity=pos.quantity,
                market_price=price,
                market_value=market_value,
                asset_class=pos.asset_class,
            )
            count += 1

        session.commit()
        _logger.info("snapshot_portfolios: wrote %d snapshot rows for %s", count, today)
        return {"count": count, "date": str(today)}

    except Exception as exc:
        session.rollback()
        _logger.error("snapshot_portfolios failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


@celery_app.task(
    name="app.tasks.portfolio_snapshot.snapshot_portfolios",
    soft_time_limit=120,
    time_limit=300,
)
def snapshot_portfolios() -> dict[str, Any]:
    """每日收盘后 16:35 触发,为所有 quantity > 0 的持仓存一张快照.

    # TODO beat: 接入 celery_beat_schedule.py — 新增如下条目:
    #
    #   "snapshot_portfolios_daily": {
    #       "task": "app.tasks.portfolio_snapshot.snapshot_portfolios",
    #       "schedule": crontab(minute=35, hour=16, day_of_week="1-5"),
    #   },
    #
    # 当前暂未修改 celery_beat_schedule.py 以避免干扰现有 beat 配置.
    """
    return _run_snapshot()
