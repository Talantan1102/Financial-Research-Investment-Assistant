from __future__ import annotations

import uuid
from decimal import Decimal
from typing import cast

import app.tasks.paper_trading as paper_tasks
import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus, PaperCashLedger
from app.models.user import User
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.reconciliation import reconcile_account
from app.tasks.celery_beat_schedule import beat_schedule
from app.tasks.paper_trading import reconcile_paper_accounts
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def account(db_session: Session) -> PaperAccount:
    token = uuid.uuid4().hex
    user = User(username=f"reconcile-{token}", email=f"{token}@example.test", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    row = PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000.00"))
    db_session.add(row)
    db_session.flush()
    db_session.add(
        PaperCashLedger(
            account_id=row.id,
            generation=1,
            kind="initial_deposit",
            amount=Decimal("1000.00"),
            available_before=Decimal("0.00"),
            available_after=Decimal("1000.00"),
            frozen_before=Decimal("0.00"),
            frozen_after=Decimal("0.00"),
            business_key=f"initial-deposit:{row.id}",
        )
    )
    db_session.flush()
    return row


def test_healthy_account_is_not_suspended(db_session: Session, account: PaperAccount) -> None:
    assert reconcile_account(db_session, account.id) == []
    assert account.status is PaperAccountStatus.ACTIVE


def test_initial_cash_edit_ledger_is_accepted_as_new_generation_authority(
    db_session: Session,
) -> None:
    token = uuid.uuid4().hex
    user = User(username=f"edit-{token}", email=f"edit-{token}@test", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=user.id)
    service.edit_initial_cash_once(user_id=user.id, initial_cash=Decimal("800000.00"))

    assert reconcile_account(db_session, account.id) == []
    assert account.available_cash == account.initial_cash == Decimal("800000.00")


def test_ledger_mismatch_has_stable_code_and_suspends_idempotently(
    db_session: Session, account: PaperAccount
) -> None:
    account.available_cash = Decimal("999.00")
    db_session.flush()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == ["cash_balance_mismatch", "ledger_balance_mismatch"]
    assert second == first
    assert account.status is PaperAccountStatus.SUSPENDED


def test_negative_cash_is_reported_even_when_database_constraint_was_bypassed(
    db_session: Session, account: PaperAccount
) -> None:
    db_session.execute(
        text(
            "ALTER TABLE paper_accounts DROP CONSTRAINT ck_paper_accounts_available_cash_nonnegative"
        )
    )
    db_session.execute(
        text("UPDATE paper_accounts SET available_cash = -1 WHERE id = :id"), {"id": account.id}
    )
    db_session.expire_all()

    result = reconcile_account(db_session, account.id)

    assert [row.code for row in result] == [
        "cash_available_negative",
        "cash_balance_mismatch",
        "ledger_balance_mismatch",
    ]


def test_negative_frozen_cash_has_exact_codes_and_idempotently_suspends(
    db_session: Session, account: PaperAccount
) -> None:
    db_session.execute(
        text("ALTER TABLE paper_accounts DROP CONSTRAINT ck_paper_accounts_frozen_cash_nonnegative")
    )
    db_session.execute(
        text("UPDATE paper_accounts SET frozen_cash = -1 WHERE id = :id"), {"id": account.id}
    )
    db_session.expire_all()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == [
        "cash_balance_mismatch",
        "cash_frozen_negative",
        "cash_reservation_mismatch",
        "ledger_balance_mismatch",
    ]
    assert second == first
    refreshed = db_session.get(PaperAccount, account.id)
    assert refreshed is not None
    assert refreshed.status is PaperAccountStatus.SUSPENDED


def test_missing_account_returns_stable_violation(db_session: Session) -> None:
    missing = uuid.uuid4()

    result = reconcile_account(db_session, missing)

    assert [(row.code, row.account_id, row.details) for row in result] == [
        ("account_not_found", missing, {})
    ]


def test_results_are_stably_sorted(db_session: Session, account: PaperAccount) -> None:
    account.available_cash = Decimal("999.00")
    account.frozen_cash = Decimal("1.00")
    db_session.flush()

    result = reconcile_account(db_session, account.id)

    assert result == sorted(result, key=lambda row: (row.code, repr(sorted(row.details.items()))))
    assert (
        db_session.scalar(select(PaperAccount.status).where(PaperAccount.id == account.id))
        is PaperAccountStatus.SUSPENDED
    )


def test_reconciliation_task_is_scheduled_every_five_minutes() -> None:
    entry = beat_schedule["paper_reconcile_accounts"]

    assert entry["task"] == "app.tasks.paper_trading.reconcile_paper_accounts"
    assert str(entry["schedule"]) == "<crontab: */5 * * * * (m/h/dM/MY/d)>"
    assert reconcile_paper_accounts.name == "app.tasks.paper_trading.reconcile_paper_accounts"


def test_periodic_scan_isolates_account_errors_and_commits_other_accounts(
    pg_test_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    setup = factory()
    accounts: list[PaperAccount] = []
    try:
        for _index in range(4):
            token = uuid.uuid4().hex
            user = User(
                username=f"scan-{token}", email=f"scan-{token}@example.test", hashed_password="x"
            )
            setup.add(user)
            setup.flush()
            row = PaperAccount.new(user_id=user.id, generation=1, initial_cash=Decimal("1000.00"))
            setup.add(row)
            setup.flush()
            setup.add(
                PaperCashLedger(
                    account_id=row.id,
                    generation=1,
                    kind="initial_deposit",
                    amount=Decimal("1000.00"),
                    available_before=Decimal("0.00"),
                    available_after=Decimal("1000.00"),
                    frozen_before=Decimal("0.00"),
                    frozen_after=Decimal("0.00"),
                    business_key=f"initial-deposit:{row.id}",
                )
            )
            accounts.append(row)
        accounts[1].available_cash = Decimal("999.00")
        setup.commit()
        account_ids = [row.id for row in accounts]
    finally:
        setup.close()

    original = paper_tasks.reconcile_account

    def flaky(session: Session, account_id: uuid.UUID, **kwargs: object):
        if account_id == account_ids[2]:
            raise RuntimeError("isolated account failure")
        if account_id == account_ids[3]:
            return None
        return original(session, account_id, **kwargs)

    monkeypatch.setattr(paper_tasks, "SessionLocal", factory)
    monkeypatch.setattr(paper_tasks, "reconcile_account", flaky)
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(paper_tasks, "_record_order_span", lambda **kwargs: emitted.append(kwargs))

    result = paper_tasks._reconcile_active_accounts()

    assert result == {"checked": 2, "suspended": 1, "errors": 1}
    assert len(emitted) == 3
    assert sum(int(cast(dict[str, object], row["attrs"])["violation_count"]) for row in emitted) > 0
    assert (
        sum(int(cast(dict[str, object], row["attrs"])["reconciliation_errors"]) for row in emitted)
        == 1
    )
    verify = factory()
    try:
        statuses = [verify.get(PaperAccount, account_id).status for account_id in account_ids]
        assert statuses == [
            PaperAccountStatus.ACTIVE,
            PaperAccountStatus.SUSPENDED,
            PaperAccountStatus.ACTIVE,
            PaperAccountStatus.ACTIVE,
        ]
    finally:
        verify.close()


def test_scan_selection_then_concurrent_reset_skips_archived_generation(
    pg_test_engine: Engine,
) -> None:
    factory = sessionmaker(bind=pg_test_engine, expire_on_commit=False)
    setup = factory()
    try:
        token = uuid.uuid4().hex
        user = User(username=f"race-{token}", email=f"race-{token}@test", hashed_password="x")
        setup.add(user)
        setup.flush()
        old = PaperAccountService(setup).get_or_create(user_id=user.id)
        user_id = user.id
        old_id = old.id
        setup.commit()
    finally:
        setup.close()

    scan_session = factory()
    reset_session = factory()
    try:
        selected = scan_session.scalar(
            select(PaperAccount.id).where(
                PaperAccount.id == old_id,
                PaperAccount.status == PaperAccountStatus.ACTIVE,
            )
        )
        assert selected == old_id
        replacement = PaperAccountService(reset_session).reset_confirmed(
            user_id=user_id,
            initial_cash=Decimal("500000.00"),
            source_session_id="race-reset",
            confirmation_id="race-reset-1",
        )
        replacement_id = replacement.id
        reset_session.commit()

        scan_session.expire_all()
        assert reconcile_account(scan_session, old_id, require_active=True) is None
        scan_session.rollback()
    finally:
        scan_session.close()
        reset_session.close()

    verify = factory()
    try:
        archived = verify.get(PaperAccount, old_id)
        active = verify.get(PaperAccount, replacement_id)
        assert archived is not None and active is not None
        assert archived.status is PaperAccountStatus.ARCHIVED
        assert active.status is PaperAccountStatus.ACTIVE
        assert reconcile_account(verify, replacement_id) == []
    finally:
        verify.close()
