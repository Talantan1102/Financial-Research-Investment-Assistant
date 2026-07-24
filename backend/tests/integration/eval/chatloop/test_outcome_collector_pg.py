from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus
from app.models.user import User
from app.models.watchlist import WatchlistAudit, WatchlistItem
from app.services.watchlist_service import ChangeSource, WatchlistService
from eval.chatloop.scenario import Scenario, load_scenarios
from eval.chatloop.sut_runner import SqlOutcomeCollector
from sqlalchemy import select
from sqlalchemy.orm import Session

PAPER_GOLDEN = Path("backend/eval/chatloop/golden/paper_trading.jsonl")
WATCHLIST_GOLDEN = Path("backend/eval/chatloop/golden/watchlist_monitoring.jsonl")


def _case(path: Path, case_id: str) -> Scenario:
    return next(case for case in load_scenarios(path) if case.case_id == case_id)


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid4().hex
    row = User(
        username=f"outcome-eval-{suffix}",
        email=f"outcome-eval-{suffix}@example.com",
        hashed_password="test-password-hash",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_paper_prepare_creates_a_fresh_funded_generation_for_each_k_sample(
    db_session: Session,
    user: User,
) -> None:
    collector = SqlOutcomeCollector(session_factory=None)
    scenario = _case(PAPER_GOLDEN, "paper-buy-approved")

    generations = []
    for run_idx in range(5):
        collector._prepare_sync(
            db_session,
            user_id=user.id,
            scenario=scenario,
            sample_key=f"{scenario.case_id}:{run_idx}",
        )
        active = db_session.scalar(
            select(PaperAccount).where(
                PaperAccount.user_id == user.id,
                PaperAccount.status == PaperAccountStatus.ACTIVE,
            )
        )
        assert active is not None
        assert active.available_cash == Decimal("10000000.00")
        assert active.frozen_cash == Decimal("0.00")
        generations.append(active.generation)

    assert generations == sorted(set(generations))
    assert all(right == left + 1 for left, right in zip(generations, generations[1:]))


def test_watchlist_prepare_rebuilds_action_preconditions_without_audit_pollution(
    db_session: Session,
    user: User,
) -> None:
    collector = SqlOutcomeCollector(session_factory=None)
    scenario = _case(WATCHLIST_GOLDEN, "watchlist-update")
    service = WatchlistService(db_session)

    for run_idx in range(5):
        collector._prepare_sync(
            db_session,
            user_id=user.id,
            scenario=scenario,
            sample_key=f"{scenario.case_id}:{run_idx}",
        )
        item = db_session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user.id,
                WatchlistItem.ts_code == "600519.SH",
            )
        )
        assert item is not None
        assert item.note == "eval-seed"
        assert item.monitoring_enabled is False

        service.update(
            user_id=user.id,
            ts_code="600519.SH",
            changes={"note": "长拿", "monitoring_enabled": True},
            source=ChangeSource(
                session_id=f"actual-run-{run_idx}",
                tool_call_id=f"actual-call-{run_idx}",
            ),
        )

    setup_audits = list(
        db_session.scalars(
            select(WatchlistAudit).where(
                WatchlistAudit.user_id == user.id,
                WatchlistAudit.source_session_id.like("eval-setup-%"),
            )
        )
    )
    actual_audits = list(
        db_session.scalars(
            select(WatchlistAudit).where(
                WatchlistAudit.user_id == user.id,
                WatchlistAudit.source_session_id.like("actual-run-%"),
            )
        )
    )
    assert setup_audits
    assert len(actual_audits) == 5
    assert {audit.source_session_id for audit in setup_audits}.isdisjoint(
        {audit.source_session_id for audit in actual_audits}
    )
