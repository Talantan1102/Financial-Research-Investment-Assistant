from __future__ import annotations

import asyncio
import sys
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
from sqlalchemy import select, update
from sqlalchemy.orm import Session

PAPER_GOLDEN = Path("backend/eval/chatloop/golden/paper_trading.jsonl")
WATCHLIST_GOLDEN = Path("backend/eval/chatloop/golden/watchlist_monitoring.jsonl")


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


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


@pytest.mark.asyncio
async def test_sample_advisory_lock_rejects_concurrent_collector_and_releases_after_error(
    pg_async_session_factory,
) -> None:
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    first = SqlOutcomeCollector(pg_async_session_factory)
    second = SqlOutcomeCollector(pg_async_session_factory)

    with pytest.raises(RuntimeError, match="test release"):
        async with first.sample_lock(tenant_id=tenant_id, user_id=user_id):
            with pytest.raises(RuntimeError, match="another stateful outcome eval"):
                async with second.sample_lock(tenant_id=tenant_id, user_id=user_id):
                    pytest.fail("concurrent collector acquired the same advisory lock")
            raise RuntimeError("test release")

    async with second.sample_lock(tenant_id=tenant_id, user_id=user_id):
        assert second._active_lock is not None
    assert first._active_lock is None
    assert second._active_lock is None

    entered = asyncio.Event()
    never = asyncio.Event()

    async def hold_until_cancelled() -> None:
        async with first.sample_lock(tenant_id=tenant_id, user_id=user_id):
            entered.set()
            await never.wait()

    task = asyncio.create_task(hold_until_cancelled())
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with second.sample_lock(tenant_id=tenant_id, user_id=user_id):
        assert second._active_lock is not None


@pytest.mark.asyncio
async def test_capture_uses_one_repeatable_read_snapshot(
    pg_async_session_factory,
) -> None:
    user_id = uuid4()
    scenario = _case(PAPER_GOLDEN, "paper-research-no-write")
    collector = SqlOutcomeCollector(pg_async_session_factory)
    async with pg_async_session_factory() as session, session.begin():
        session.add(
            User(
                id=user_id,
                username=f"snapshot-{user_id.hex}",
                email=f"snapshot-{user_id.hex}@example.com",
                hashed_password="test-password-hash",
            )
        )
    async with pg_async_session_factory() as session, session.begin():
        await session.run_sync(
            lambda sync_session: collector._prepare_sync(
                sync_session,
                user_id=user_id,
                scenario=scenario,
                sample_key="snapshot:0",
            )
        )

    first_query_done = asyncio.Event()
    allow_capture_to_continue = asyncio.Event()

    async def pause_after_first_query() -> None:
        first_query_done.set()
        await allow_capture_to_continue.wait()

    collector._after_capture_account_read = pause_after_first_query  # type: ignore[method-assign]
    capture_task = asyncio.create_task(
        collector.capture(user_id=str(user_id), run_id=None, scenario=scenario)
    )
    await asyncio.wait_for(first_query_done.wait(), timeout=5)
    async with pg_async_session_factory() as session, session.begin():
        await session.execute(
            update(PaperAccount)
            .where(PaperAccount.user_id == user_id, PaperAccount.status == "active")
            .values(available_cash=Decimal("9000000.00"))
        )
    allow_capture_to_continue.set()
    first_snapshot = await asyncio.wait_for(capture_task, timeout=5)

    async def no_pause() -> None:
        return None

    collector._after_capture_account_read = no_pause  # type: ignore[method-assign]
    second_snapshot = await collector.capture(
        user_id=str(user_id),
        run_id=None,
        scenario=scenario,
    )

    assert first_snapshot["available_cash"] == "10000000"
    assert second_snapshot["available_cash"] == "9000000"
