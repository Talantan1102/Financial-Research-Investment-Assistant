"""Monitoring Celery tasks — detection_cycle / generate_detail_card / daily_full_scan / cleanup_old.

Spec § 4.1 task 清单, § 4.5 detection_cycle 主流程, § 5 错误处理.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
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
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule
from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule
from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.tushare_service import TushareService

_logger = logging.getLogger(__name__)


def _get_session() -> Session:
    """Hook 点:测试覆盖通过 patch('app.tasks.monitoring._get_session', ...)."""
    return SessionLocal()


def _build_detector() -> SignalDetector:
    """Hook 点:测试覆盖通过 patch."""
    return SignalDetector(
        rules=[
            AnnouncementRule(),
            PriceAnomalyRule(),
            CashFlowRule(),
            FinancialRatioRule(),
            ShareholderCountRule(),
        ]
    )


def _build_tushare() -> TushareService:
    """Hook 点:测试 patch。SignalRule.evaluate 需要真实 tushare 数据源。"""
    from app.services.tushare_factory import build_tushare_service

    return build_tushare_service()


def _build_bocha() -> BochaService:
    """Hook 点:测试 patch。announcement rule 走 Bocha web search。"""
    from app.services.bocha_factory import build_bocha_service_from_env

    return build_bocha_service_from_env()


def _build_llm() -> LLMService:
    """Hook 点:测试 patch。announcement rule 用 LLM 判断公告语义。"""
    from app.services.openai_client import build_llm_service_from_env

    return build_llm_service_from_env()


def _build_writer():
    """Hook 点:测试 patch。

    TODO(Task 17): 真实 Writer.alert_writer(alert_id) 协议尚未在 app.agents.writer
    Writer 类上定型(目前只有 _run_alert_writer(state) 接受 ResearchState)。
    生产 wiring 需要薄 adapter:从 alert_id 加载 ResearchState → 调用
    Writer._run_alert_writer → 抽出 {"json", "markdown"}。
    单元测试通过 patch("app.tasks.monitoring._build_writer") 注入 mock,
    所以 Task 10 的 task body 已可独立验证。
    """
    from app.agents.writer import Writer  # lazy import — production wiring TBD

    return Writer()


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
            subjects = [s for s in subjects if str(s.user_id) == str(user_filter)]

        # 按 ts_code 去重(同股跨 user 共享 SignalDetector 调用)
        unique_codes: dict[str, MonitoringSubject] = {}
        for s in subjects:
            unique_codes.setdefault(s.ts_code, s)

        # 并发跑 SignalDetector(per ts_code,semaphore cap=5;每个 detector 内
        # 5 个 rule 也并发)。C1: detect 需要 (subject, tushare, bocha, llm,
        # thresholds) 五个参数 — 之前只传 1 个,每次都 TypeError。
        tushare = _build_tushare()
        bocha = _build_bocha()
        llm = _build_llm()
        sem = asyncio.Semaphore(5)

        async def _scan(sample_subject: MonitoringSubject) -> tuple[SignalLevel, list]:
            async with sem:
                return await detector.detect(
                    sample_subject, tushare, bocha, llm, DEFAULT_THRESHOLDS
                )

        codes = list(unique_codes.keys())
        raw_results = await asyncio.gather(
            *(_scan(unique_codes[c]) for c in codes), return_exceptions=True
        )
        results_by_code: dict[str, tuple[SignalLevel, list]] = {}
        for code, res in zip(codes, raw_results):
            if isinstance(res, BaseException):
                # Fail-loud (hard rule 4): 不写 GREEN sentinel(那正是把整个监控
                # 黑洞伪装成干净扫描的 bug)。记带 traceback 的错误并跳过该 code;
                # 其 subject 在下面循环里被跳过,下一轮 cycle 自然重扫。
                _logger.error("detect failed for %s: %s", code, res, exc_info=res)
                continue
            results_by_code[code] = res

        if codes and not results_by_code:
            # 所有 code 全失败 → 系统性故障,绝不能标 success 静默吞掉。
            raise RuntimeError(
                f"detection_cycle: all {len(codes)} ts_codes failed detection "
                "(see logged tracebacks) — refusing to mark cycle as success"
            )

        # 展开到 (user_id, ts_code) 维度,写 runs / signals / alerts
        per_user_runs: dict[str, str] = {}  # user_id → run_id

        from app.tasks.monitoring import generate_detail_card  # local import for testability

        alert_ids_to_enqueue: list[str] = []
        for subject in subjects:
            if subject.ts_code not in results_by_code:
                continue  # detect failed for this code (logged above) — skip, no silent GREEN
            level, signals = results_by_code[subject.ts_code]

            # 每 user 一行 run(同 cycle_id 内复用)
            if subject.user_id not in per_user_runs:
                run = run_repo.create(
                    user_id=subject.user_id,
                    cycle_id=cycle_id,
                    trigger_type="manual" if user_filter else "cron",
                    started_at=datetime.utcnow(),
                )
                per_user_runs[subject.user_id] = run.id
            run_id = per_user_runs[subject.user_id]

            # 写 signals
            for sig in signals:
                sig_repo.create(
                    run_id=run_id,
                    user_id=subject.user_id,
                    ts_code=subject.ts_code,
                    rule_name=sig.rule_name,
                    level=sig.level.value,
                    detected_value=str(sig.detected_value)
                    if sig.detected_value is not None
                    else None,
                    threshold=str(sig.threshold) if sig.threshold is not None else None,
                    explanation=sig.explanation,
                    raw_data_ref=sig.raw_data_ref,
                )

            # 标红 → 写 alert;enqueue 推迟到 commit 之后(C28)
            if level in (SignalLevel.YELLOW, SignalLevel.RED):
                alert = alert_repo.create(
                    run_id=run_id,
                    user_id=subject.user_id,
                    ts_code=subject.ts_code,
                    alert_level=level.value,
                    report_json={},
                )  # create() 已 flush → alert.id 可用,无需额外 flush
                alert_ids_to_enqueue.append(alert.id)

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
        # C28: 只在 commit 成功后才 enqueue,避免"任务已排队但 alert 行被 rollback
        # 删掉"的孤儿任务(那种任务到达 worker 后 get(alert_id) 返 None 静默 no-op)。
        for alert_id in alert_ids_to_enqueue:
            generate_detail_card.delay(alert_id)
        return {
            "cycle_id": cycle_id,
            "subjects": len(subjects),
            "alerts_enqueued": len(alert_ids_to_enqueue),
        }

    except Exception as exc:
        session.rollback()
        _logger.error("detection_cycle failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()


@celery_app.task(
    name="app.tasks.monitoring.generate_detail_card",
    autoretry_for=(Exception,),  # 简化:任何异常 retry,真生产可窄到 LLMError
    retry_backoff=True,
    max_retries=2,
    rate_limit="5/m",
    acks_late=True,
)
def generate_detail_card(alert_id: str) -> dict[str, Any]:
    """Spec § 5.1:autoretry max=2 + acks_late + state machine."""
    return asyncio.run(_run_generate_detail_card(alert_id))


async def _run_generate_detail_card(alert_id: str) -> dict[str, Any]:
    session = _get_session()
    alert_repo = MonitoringAlertRepo(session)

    try:
        # C28 idempotency: acks_late 重投递 / commit-后-rollback 孤儿任务可能让同一
        # alert_id 被处理多次。已 READY 的不重跑昂贵的 LLM writer,也不覆盖结果。
        existing = alert_repo.get(alert_id)
        if existing is None:
            return {"alert_id": alert_id, "status": "not_found"}
        if existing.detail_status == DetailStatus.READY:
            return {"alert_id": alert_id, "status": "already_ready"}

        writer = _build_writer()
        result = await writer.alert_writer(alert_id)  # returns {"json": ..., "markdown": ...}
        existing.error_message = None
        alert_repo.update_detail(
            alert_id,
            status=DetailStatus.READY,
            report_json=result["json"],
            report_markdown=result["markdown"],
        )
        session.commit()
        return {"alert_id": alert_id, "status": "ready"}
    except Exception as exc:
        # 记 failed(每次 retry 都写一次,最终值就是失败值)
        session.expire_all()
        current = alert_repo.get(alert_id)
        if current is not None and current.detail_status != DetailStatus.READY:
            alert_repo.update_detail(
                alert_id,
                status=DetailStatus.FAILED,
                error_message=str(exc)[:2000],
            )
        session.commit()
        raise  # autoretry kicks in
    finally:
        session.close()


@celery_app.task(name="app.tasks.monitoring.daily_full_scan")
def daily_full_scan() -> dict[str, Any]:
    """16:30 工作日收盘后兜底全量 — 异步派发 detection_cycle 到 worker。

    C59: 之前用 detection_cycle.apply()(同步在本 worker 内跑,阻塞到 300s soft
    limit),且 return 'queued' 是谎言。改成 .delay() 真正入队,返回真实 task_id。
    """
    task = detection_cycle.delay()
    return {"status": "dispatched", "task_id": task.id}


@celery_app.task(name="app.tasks.monitoring.cleanup_old")
def cleanup_old(days: int = 7) -> dict[str, Any]:
    """清 N 天前的 monitoring_runs(级联删 signals/alerts/notifications)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    session = _get_session()
    try:
        from app.models.monitoring import MonitoringRun

        deleted = (
            session.query(MonitoringRun)
            .filter(MonitoringRun.started_at < cutoff)
            .delete(synchronize_session=False)
        )
        session.commit()
        return {"deleted_runs": deleted}
    finally:
        session.close()
