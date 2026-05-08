"""Monitoring Celery tasks — detection_cycle / generate_detail_card / daily_full_scan / cleanup_old.

Spec § 4.1 task 清单, § 4.5 detection_cycle 主流程, § 5 错误处理.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.monitoring import DetailStatus
from app.models.position import Position
from app.services.monitoring.repositories import (
    MonitoringAlertRepo,
    MonitoringRunRepo,
    MonitoringSignalRepo,
)
from app.services.monitoring.scope import MonitoringSubject, load_active_subjects
from app.services.monitoring.signal_detector import SignalDetector
from app.services.monitoring.signal_rules.announcement import AnnouncementRule
from app.services.monitoring.signal_rules.base import SignalLevel
from app.services.monitoring.signal_rules.cash_flow import CashFlowRule
from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule
from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule
from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule
from app.tasks.celery_app import celery_app

_logger = logging.getLogger(__name__)


def _get_session() -> Session:
    """Hook 点:测试覆盖通过 patch('app.tasks.monitoring._get_session', ...)."""
    return SessionLocal()


def _build_detector() -> SignalDetector:
    """Hook 点:测试覆盖通过 patch."""
    return SignalDetector(rules=[
        AnnouncementRule(),
        PriceAnomalyRule(),
        CashFlowRule(),
        FinancialRatioRule(),
        ShareholderCountRule(),
    ])


def _resolve_quote_from_signals(signals: list[Any]) -> Decimal | None:
    """从 SignalDetector 结果提取当日 close(price_anomaly rule 持有)."""
    for sig in signals:
        if sig.rule_name == "price_anomaly" and sig.raw_data_ref:
            close = sig.raw_data_ref.get("close")
            if close is not None:
                return Decimal(str(close))
    return None


@celery_app.task(
    name="app.tasks.monitoring.detection_cycle",
    soft_time_limit=300,
    time_limit=600,
)
def detection_cycle(user_filter: str | None = None) -> dict[str, Any]:
    """Detection cycle — scope = positions WHERE quantity > 0.

    Spec § 4.5:
    - 拉所有 (user_id, ts_code) 持仓
    - 按 ts_code 去重跑 SignalDetector(跨 user 共享 LLM cost)
    - 标红 enqueue generate_detail_card
    - 顺手刷新 Position.last_quote_price/at

    Args:
        user_filter: 可选 user_id 过滤(/monitoring/refresh 手动触发用)
    """
    return asyncio.run(_run_detection_cycle(user_filter))


async def _run_detection_cycle(user_filter: str | None = None) -> dict[str, Any]:
    cycle_id = str(uuid4())
    session = _get_session()
    detector = _build_detector()

    run_repo = MonitoringRunRepo(session)
    sig_repo = MonitoringSignalRepo(session)
    alert_repo = MonitoringAlertRepo(session)

    try:
        subjects = load_active_subjects(session)
        if user_filter:
            subjects = [s for s in subjects if s.user_id == user_filter]

        # 按 ts_code 去重(同股跨 user 共享 SignalDetector 调用)
        unique_codes: dict[str, MonitoringSubject] = {}
        for s in subjects:
            unique_codes.setdefault(s.ts_code, s)

        # 并发跑 SignalDetector(per ts_code,5 个 rule 并发在 detector 内)
        sem = asyncio.Semaphore(5)

        async def _scan(ts_code: str, sample_subject: MonitoringSubject):
            async with sem:
                return await detector.detect(sample_subject)

        tasks = [_scan(c, sub) for c, sub in unique_codes.items()]
        results_by_code: dict[str, tuple[SignalLevel, list]] = {}
        for code, fut in zip(unique_codes.keys(), tasks):
            try:
                level, signals = await fut
                results_by_code[code] = (level, signals)
            except Exception as exc:
                _logger.error("detect failed for %s: %s", code, exc)
                results_by_code[code] = (SignalLevel.GREEN, [])

        # 展开到 (user_id, ts_code) 维度,写 runs / signals / alerts
        per_user_runs: dict[str, str] = {}  # user_id → run_id

        from app.tasks.monitoring import generate_detail_card  # local import for testability

        for subject in subjects:
            level, signals = results_by_code[subject.ts_code]

            # 每 user 一行 run(同 cycle_id 内复用)
            if subject.user_id not in per_user_runs:
                run = run_repo.create(
                    user_id=subject.user_id, cycle_id=cycle_id,
                    trigger_type="manual" if user_filter else "cron",
                    started_at=datetime.utcnow(),
                )
                per_user_runs[subject.user_id] = run.id
            run_id = per_user_runs[subject.user_id]

            # 写 signals
            for sig in signals:
                sig_repo.create(
                    run_id=run_id, user_id=subject.user_id, ts_code=subject.ts_code,
                    rule_name=sig.rule_name, level=sig.level.value,
                    detected_value=str(sig.detected_value) if sig.detected_value is not None else None,
                    threshold=str(sig.threshold) if sig.threshold is not None else None,
                    explanation=sig.explanation,
                    raw_data_ref=sig.raw_data_ref,
                )

            # 标红 → 写 alert + enqueue generate_detail_card
            if level in (SignalLevel.YELLOW, SignalLevel.RED):
                alert = alert_repo.create(
                    run_id=run_id, user_id=subject.user_id, ts_code=subject.ts_code,
                    alert_level=level.value, report_json={},
                )
                session.flush()
                generate_detail_card.delay(alert.id)

            # 顺手刷新 Position.last_quote_price/at(spec § 4.5 + portfolio decision 3)
            quote = _resolve_quote_from_signals(signals)
            if quote is not None:
                pos = (
                    session.query(Position)
                    .filter_by(user_id=subject.user_id, ts_code=subject.ts_code)
                    .first()
                )
                if pos is not None:
                    pos.last_quote_price = quote
                    pos.last_quote_at = datetime.utcnow()

        # 标记所有 run 完成
        for run_id in per_user_runs.values():
            run_repo.mark_finished(run_id, status="success")

        session.commit()
        return {"cycle_id": cycle_id, "subjects": len(subjects), "alerts_enqueued": "see logs"}

    except Exception as exc:
        session.rollback()
        _logger.error("detection_cycle failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


# Placeholder — real implementation lands in Task 10.
# Defined now so that detection_cycle can import + .delay() it without ImportError.
@celery_app.task(
    name="app.tasks.monitoring.generate_detail_card",
    bind=True,
)
def generate_detail_card(self, alert_id: str) -> dict[str, Any]:  # pragma: no cover
    """Generate detail card for a flagged alert. Implemented in Task 10."""
    raise NotImplementedError("generate_detail_card lands in Task 10")
