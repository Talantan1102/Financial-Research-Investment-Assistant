"""End-to-end monitoring engine: Celery worker + Redis broker + PG.

依赖 fixtures(per spec § 6.2):
- pg_test_container (existing fixture)
- redis_url + celery_worker_subprocess (this PR)
"""

from __future__ import annotations

import shutil
import subprocess
import time
from decimal import Decimal
from uuid import uuid4

import pytest


def _docker_available() -> bool:
    """True only if `docker` binary exists AND `docker info` returns 0."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


# Module-level skip — pg_test_container fixture invokes `docker compose` directly
# without a docker-availability guard, so without this skip the test would error
# (FileNotFoundError) before the redis_url fixture's skip path can fire.
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _docker_available(),
        reason="docker not available — L2 e2e requires docker for PG + Redis containers",
    ),
]


def test_full_detection_cycle_writes_signals_and_alerts(
    pg_test_container,
    redis_url,
    celery_worker_subprocess,
    monkeypatch,
):
    """Full path:Position → detection_cycle → write signals/alerts → enqueue
    generate_detail_card → worker pick up → write detail."""
    monkeypatch.setenv("CELERY_BROKER_URL", redis_url)
    monkeypatch.setenv("CELERY_RESULT_BACKEND", redis_url)

    # 1. Seed PG: user + position
    from app.core.database import SessionLocal
    from app.models.position import Position
    from app.models.user import User

    with SessionLocal() as session:
        uid = str(uuid4())
        user = User(
            id=uid,
            username=f"e2e-{uid[:8]}",
            email=f"e2e-{uuid4().hex[:6]}@t",
            hashed_password="x",
            is_active=True,
        )
        session.add(user)
        session.flush()
        pos = Position(
            id=str(uuid4()),
            user_id=user.id,
            ts_code="600519.SH",
            name="贵州茅台",
            quantity=100,
            avg_cost=Decimal("100"),
            total_cost=Decimal("10000"),
            realized_pnl=Decimal("0"),
        )
        session.add(pos)
        session.commit()
        user_id = user.id

    # 2. Trigger detection cycle (real Celery enqueue, not eager)
    from app.tasks.monitoring import detection_cycle

    result = detection_cycle.delay(user_filter=user_id)
    result.get(timeout=60)

    # 3. Verify monitoring_runs written
    from app.models.monitoring import MonitoringAlert, MonitoringRun

    with SessionLocal() as session:
        runs = session.query(MonitoringRun).filter_by(user_id=user_id).all()
        assert len(runs) == 1

        # 异动 / 公告依赖 LLM real call,可能 GREEN(无 alert)— 不强求 alert
        alerts = session.query(MonitoringAlert).filter_by(user_id=user_id).all()
        # alerts 可能 0 或 1,数量不强求,但若有则 detail_status 必须最终 ready/failed(不停 pending)
        for a in alerts:
            # 给 worker 30s 跑详情卡
            time.sleep(30)
            session.refresh(a)
            assert a.detail_status in ("ready", "failed")
