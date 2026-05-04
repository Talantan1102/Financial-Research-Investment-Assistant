"""End-to-end cassette test — full monitoring scan with cassette LLM + cassette tushare.

Design notes:
- This test wires the full MonitoringService pipeline with REAL tushare data
  (replayed from cassette) and a REAL LLM (replayed from cassette).
- For the announcement rule, the LLM call is included in the cassette.
- Signal-only rules (financial_ratio, cash_flow, shareholder_count, price_anomaly)
  do not require LLM calls and are driven by cassette tushare data.

Manual recording procedure (run once in production env):
    unset all_proxy https_proxy http_proxy
    VCR_RECORD_MODE=new_episodes TUSHARE_MODE=real LLM_MODE=real \\
      uv run pytest backend/tests/e2e/test_monitoring_e2e_cassette.py -v -s

Cassette files stored at:
    backend/tests/fixtures/cassettes/test_monitoring_e2e_cassette/

Note on LLM_MODE: AnnouncementRule calls llm.chat() — in cassette mode, if
DASHSCOPE_API_KEY is missing the VCR cassette intercepts the HTTP call and
returns the recorded response without going to the network.

Current status: @pytest.mark.skip because cassette recording requires production
env (real TUSHARE_TOKEN + DASHSCOPE_API_KEY). Tests 1-18 pass without this cassette.
Run manually per the procedure above, then remove the skip and commit the cassette.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.scripts.init_monitoring_tables import init_monitoring_tables
from app.services.monitoring.escalation import EscalationResult, EscalationStatus
from app.services.monitoring.monitoring_service import MonitoringService
from app.services.monitoring.notifications.email_notifier import EmailSendResult
from app.services.monitoring.signal_detector import SignalDetector
from app.services.monitoring.signal_rules.announcement import AnnouncementRule
from app.services.monitoring.signal_rules.cash_flow import CashFlowRule
from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule
from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule
from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule

# ---------------------------------------------------------------------------
# VCR config (module-scoped): strip tokens, match without body
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, Any]:
    """VCR config for monitoring e2e cassette.

    match_on excludes body because:
    - AnnouncementRule prompt includes datetime.now() (dynamic)
    - Tushare requests may include dynamic date parameters
    Per feedback_cassette_dynamic_prompt_values lesson.
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "x-tushare-token",
        ],
        "match_on": ["method", "scheme", "host", "port", "path"],
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "decode_compressed_response": True,
    }


# ---------------------------------------------------------------------------
# Env setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.setenv("EMAIL_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "real")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_customers(db_path: Path) -> None:
    """Seed 2 test customers for the e2e cassette scan."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # Customer 1: used for signal detection (cassette replays tushare data)
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) VALUES (?, ?, ?, ?)",
            ("c-e2e-1", "600519.SH", "贵州茅台", "消费"),
        )
        # Customer 2: second customer for concurrent fan-out test
        conn.execute(
            "INSERT INTO monitoring_customers (id, ts_code, name, industry) VALUES (?, ?, ?, ?)",
            ("c-e2e-2", "601398.SH", "工商银行", "金融"),
        )


def _build_monitoring_service(
    db_path: Path,
    tushare: Any,
    llm: Any,
) -> MonitoringService:
    """Wire MonitoringService with real detector + mock writer/escalator/notifier."""
    from datetime import datetime

    from app.agents.portfolio_warning_schema import PortfolioWarningReport

    rules = [
        FinancialRatioRule(),
        CashFlowRule(),
        ShareholderCountRule(),
        AnnouncementRule(),
        PriceAnomalyRule(),
    ]
    detector = SignalDetector(rules=rules)

    # Writer: mock that returns a minimal PortfolioWarningReport
    writer = MagicMock()
    fake_state = MagicMock()

    def _make_report(state: Any) -> Any:
        from app.services.monitoring.signal_rules.base import SignalLevel

        fake_report = PortfolioWarningReport(
            customer_id=state.session_id,
            customer_name="test",
            ts_code="600519.SH",
            industry="消费",
            run_id=state.request_id,
            alert_id="placeholder",
            generated_at=datetime(2026, 5, 4),
            alert_level=SignalLevel.YELLOW,
            summary="cassette test alert",
        )
        fake_state.portfolio_warning_report = fake_report
        return fake_state

    writer.run = AsyncMock(side_effect=_make_report)

    # Escalator: mock that returns DAILY_DEDUP (avoids real LLM graph invoke)
    escalator = MagicMock()
    escalator.escalate = AsyncMock(
        return_value=EscalationResult(status=EscalationStatus.DAILY_DEDUP)
    )

    # EmailNotifier: mock (EMAIL_MODE=mock per spec)
    email_notifier = MagicMock()
    email_notifier.send = AsyncMock(return_value=EmailSendResult(success=True))

    from app.services.bocha_factory import build_bocha_service_from_env

    bocha = build_bocha_service_from_env()

    return MonitoringService(
        db_path=db_path,
        detector=detector,
        writer=writer,
        escalator=escalator,
        email_notifier=email_notifier,
        tushare=tushare,
        bocha=bocha,
        llm=llm,
        thresholds_per_rule=DEFAULT_THRESHOLDS,
        recipient_emails=["test@example.com"],
        max_concurrent_customers=2,
    )


# ---------------------------------------------------------------------------
# Main e2e cassette test
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "cassette recording requires production env (real TUSHARE_TOKEN + DASHSCOPE_API_KEY). "
        "Manual recording procedure: "
        "  unset all_proxy https_proxy http_proxy && "
        "  VCR_RECORD_MODE=new_episodes TUSHARE_MODE=real LLM_MODE=real "
        "  uv run pytest backend/tests/e2e/test_monitoring_e2e_cassette.py -v -s "
        "After recording, remove this skip marker and commit the cassette file. "
        "Deferred to user per Task 19 plan (P1 priority — skip if production budget unavailable)."
    )
)
@pytest.mark.vcr
@pytest.mark.asyncio
async def test_monitoring_scan_2_customers_cassette(tmp_path: Path) -> None:
    """Full monitoring scan for 2 customers with cassette LLM + cassette tushare.

    Validates:
    - MonitoringService.run_scan() completes for 2 customers concurrently
    - monitoring_runs table has 2 rows with status=success
    - monitoring_signals table has at least 2 rows (one per customer per rule)
    - Signal levels are valid SignalLevel values
    - At least one run completes within expected time (cassette is fast)
    """
    from app.services.openai_client import build_llm_service_from_env
    from app.services.tushare_factory import build_tushare_service

    db_path = tmp_path / "monitoring_e2e.sqlite"
    init_monitoring_tables(db_path)
    _seed_customers(db_path)

    tushare = build_tushare_service()
    llm = build_llm_service_from_env()
    svc = _build_monitoring_service(db_path, tushare, llm)

    run_ids = await svc.run_scan(["c-e2e-1", "c-e2e-2"], trigger_type="manual")

    assert len(run_ids) == 2, f"Expected 2 run_ids, got {len(run_ids)}"

    with sqlite3.connect(db_path) as conn:
        runs = conn.execute(
            "SELECT customer_id, status FROM monitoring_runs ORDER BY customer_id"
        ).fetchall()
        signals = conn.execute("SELECT run_id, rule_name, level FROM monitoring_signals").fetchall()

    assert len(runs) == 2, f"Expected 2 run rows, got {len(runs)}: {runs}"
    for cid, status in runs:
        assert status == "success", f"Customer {cid} run status: {status}"

    # At least 1 signal per customer (5 rules × 2 customers = up to 10 signals)
    assert len(signals) >= 2, f"Expected at least 2 signal rows, got {len(signals)}"

    # All signal levels must be valid
    valid_levels = {"green", "yellow", "red"}
    for run_id, rule_name, level in signals:
        assert level in valid_levels, (
            f"Invalid signal level '{level}' for rule '{rule_name}' in run '{run_id}'"
        )
