"""detection_cycle Celery task — eager mode + mock SignalDetector."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.models.monitoring import (
    DetailStatus,
    MonitoringAlert,
    MonitoringRun,
    MonitoringSignal,
)
from app.models.position import Position
from app.models.user import User
from app.services.monitoring.signal_rules.base import SignalLevel, SignalResult
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def celery_eager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("CELERY_TASK_EAGER_PROPAGATES", "1")


@pytest.fixture(autouse=True)
def _stub_service_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    """detect() 现需要 tushare/bocha/llm 三个真实依赖。单测里 stub 掉这三个 builder,
    避免真连数据源(detector 本身在各 test 里被 _build_detector patch 替换)。"""
    monkeypatch.setattr("app.tasks.monitoring._build_tushare", lambda: MagicMock())
    monkeypatch.setattr("app.tasks.monitoring._build_bocha", lambda: MagicMock())
    monkeypatch.setattr("app.tasks.monitoring._build_llm", lambda: MagicMock())


def _make_user(session: Session, *, user_id: str | None = None) -> User:
    uid = uuid4().hex[:8]
    u = User(
        id=user_id or str(uuid4()),
        username=f"user-{uid}",
        email=f"u-{uid}@t",
        hashed_password="x",
        is_active=True,
    )
    session.add(u)
    session.flush()
    return u


def _make_position(session: Session, user: User, ts_code: str) -> Position:
    p = Position(
        id=str(uuid4()),
        user_id=user.id,
        ts_code=ts_code,
        name=f"name-{ts_code}",
        quantity=100,
        avg_cost=Decimal("100"),
        total_cost=Decimal("10000"),
        realized_pnl=Decimal("0"),
    )
    session.add(p)
    session.flush()
    return p


def test_detection_cycle_creates_run_per_user(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """每个有持仓的 user 在该 cycle 内一行 monitoring_run."""
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    # Mock SignalDetector 全 GREEN
    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.GREEN,
            [SignalResult(rule_name="x", level=SignalLevel.GREEN, explanation="ok")],
        )
    )

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    runs = db_session.query(MonitoringRun).filter_by(user_id=user.id).all()
    assert len(runs) >= 1


@pytest.mark.parametrize("as_uuid", [False, True])
def test_detection_cycle_user_filter_accepts_string_and_uuid(
    db_session: Session, as_uuid: bool
) -> None:
    """手动扫描的 user_filter 无论来自 JSON 字符串或内部 UUID 都只匹配本人。"""
    selected_uuid = uuid4()
    selected = _make_user(db_session, user_id=str(selected_uuid))
    other = _make_user(db_session)
    _make_position(db_session, selected, "600519.SH")
    _make_position(db_session, other, "000001.SZ")
    db_session.commit()

    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(return_value=(SignalLevel.GREEN, []))
    user_filter = selected_uuid if as_uuid else selected.id

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        result = detection_cycle.apply(kwargs={"user_filter": user_filter}).get()

    assert result["subjects"] == 1
    runs = db_session.query(MonitoringRun).all()
    assert {str(run.user_id) for run in runs} == {selected.id}


def test_detection_cycle_yellow_creates_alert_with_pending_status(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.YELLOW,
            [SignalResult(rule_name="price_anomaly", level=SignalLevel.YELLOW, explanation="-6%")],
        )
    )

    enqueued = []

    def _fake_delay(alert_id: str, **kwargs) -> None:
        enqueued.append(alert_id)

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
        patch("app.tasks.monitoring.generate_detail_card.delay", side_effect=_fake_delay),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    alerts = db_session.query(MonitoringAlert).filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert alerts[0].alert_level == "yellow"
    assert alerts[0].detail_status == DetailStatus.PENDING
    assert len(enqueued) == 1  # generate_detail_card enqueued for the alert


def test_detection_cycle_dedupes_ts_code_across_users(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同 ts_code 跨 user 共享 SignalDetector 一次调用(spec § 4.5 去重节省 cost)."""
    u1 = _make_user(db_session)
    u2 = _make_user(db_session)
    _make_position(db_session, u1, "600519.SH")
    _make_position(db_session, u2, "600519.SH")
    db_session.commit()

    detect_calls = []
    mock_detector = MagicMock()

    async def _detect_spy(subject, *args, **kwargs):
        detect_calls.append(subject.ts_code)
        return (SignalLevel.GREEN, [])

    mock_detector.detect = _detect_spy

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    assert detect_calls.count("600519.SH") == 1  # 去重


def test_detection_cycle_updates_position_last_quote(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spec § 4.5 顺手刷新 Position.last_quote_price/at."""
    user = _make_user(db_session)
    pos = _make_position(db_session, user, "600519.SH")
    pos_id = pos.id  # capture before impl session.close() detaches the instance
    db_session.commit()

    mock_detector = MagicMock()
    mock_detector.detect = AsyncMock(
        return_value=(
            SignalLevel.GREEN,
            [
                SignalResult(
                    rule_name="price_anomaly",
                    level=SignalLevel.GREEN,
                    explanation="ok",
                    raw_data_ref={"close": 1500.0},  # quote snapshot
                )
            ],
        )
    )

    with (
        patch("app.tasks.monitoring._build_detector", return_value=mock_detector),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    refreshed = db_session.query(Position).filter_by(id=pos_id).one()
    assert refreshed.last_quote_price == Decimal("1500.0")
    assert refreshed.last_quote_at is not None


class _StrictDetector:
    """detect 的真实 5 参签名 — 守护 C1 回归:若生产端少传参数会 TypeError。

    旧 bug 用 AsyncMock(accept *args) 把 detect(subject) 的 TypeError 完全遮住,
    导致每只票永远 GREEN。这个 fake 用严格签名,生产端漏参数立刻炸。
    """

    async def detect(self, subject, tushare, bocha, llm, thresholds):
        return (
            SignalLevel.RED,
            [SignalResult(rule_name="price_anomaly", level=SignalLevel.RED, explanation="-9%")],
        )


def test_detection_cycle_passes_five_args_and_enqueues_after_commit(
    db_session: Session,
) -> None:
    """C1 回归:detect 收到全部 5 个参数(否则 _StrictDetector 抛 TypeError);
    C28 回归:generate_detail_card 只在 commit 之后 enqueue。"""
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    enqueued: list[str] = []

    with (
        patch("app.tasks.monitoring._build_detector", return_value=_StrictDetector()),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
        patch(
            "app.tasks.monitoring.generate_detail_card.delay",
            side_effect=lambda aid, **k: enqueued.append(aid),
        ),
    ):
        from app.tasks.monitoring import detection_cycle

        result = detection_cycle.apply().get()

    sigs = db_session.query(MonitoringSignal).filter_by(user_id=user.id).all()
    assert len(sigs) == 1  # detect 真的跑了并写了 signal(不是被 TypeError 吞成空)
    alerts = db_session.query(MonitoringAlert).filter_by(user_id=user.id).all()
    assert len(alerts) == 1
    assert len(enqueued) == 1 and enqueued[0] == alerts[0].id
    assert result["alerts_enqueued"] == 1


def test_detection_cycle_reraises_when_all_detects_fail(db_session: Session) -> None:
    """C1 回归:detect 全部失败时,cycle 必须 fail-loud 抛错,而不是标 success。"""
    user = _make_user(db_session)
    _make_position(db_session, user, "600519.SH")
    db_session.commit()

    class _BoomDetector:
        async def detect(self, subject, tushare, bocha, llm, thresholds):
            raise RuntimeError("detect boom")

    with (
        patch("app.tasks.monitoring._build_detector", return_value=_BoomDetector()),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        with pytest.raises(RuntimeError):
            detection_cycle.apply().get()


def test_detection_cycle_runs_codes_concurrently(db_session: Session) -> None:
    """C25 回归:多 ts_code 应并发跑(semaphore cap=5),不是逐个串行。"""
    user = _make_user(db_session)
    for i in range(10):
        _make_position(db_session, user, f"60000{i}.SH")
    db_session.commit()

    class _ConcurrencyTracker:
        def __init__(self) -> None:
            self.current = 0
            self.max_seen = 0

        async def detect(self, subject, tushare, bocha, llm, thresholds):
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
            await asyncio.sleep(0.02)
            self.current -= 1
            return (SignalLevel.GREEN, [])

    tracker = _ConcurrencyTracker()

    with (
        patch("app.tasks.monitoring._build_detector", return_value=tracker),
        patch("app.tasks.monitoring._get_session", return_value=db_session),
    ):
        from app.tasks.monitoring import detection_cycle

        detection_cycle.apply().get()

    assert tracker.max_seen > 1  # 真并发(旧 zip+await 串行只会是 1)
    assert tracker.max_seen <= 5  # semaphore cap 生效
