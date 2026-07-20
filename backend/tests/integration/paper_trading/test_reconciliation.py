from __future__ import annotations

import uuid
from decimal import Decimal

import app.tasks.paper_trading as paper_tasks
import pytest
from app.models.paper_account import PaperAccount, PaperAccountStatus, PaperCashLedger
from app.models.user import User
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


def test_ledger_mismatch_has_stable_code_and_suspends_idempotently(
    db_session: Session, account: PaperAccount
) -> None:
    account.available_cash = Decimal("999.00")
    db_session.flush()

    first = reconcile_account(db_session, account.id)
    second = reconcile_account(db_session, account.id)

    assert [row.code for row in first] == ["ledger_balance_mismatch"]
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
        for _index in range(3):
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

    def flaky(session: Session, account_id: uuid.UUID):
        if account_id == account_ids[2]:
            raise RuntimeError("isolated account failure")
        return original(session, account_id)

    monkeypatch.setattr(paper_tasks, "SessionLocal", factory)
    monkeypatch.setattr(paper_tasks, "reconcile_account", flaky)

    result = paper_tasks._reconcile_active_accounts()

    assert result == {"checked": 2, "suspended": 1, "errors": 1}
    verify = factory()
    try:
        statuses = [verify.get(PaperAccount, account_id).status for account_id in account_ids]
        assert statuses == [
            PaperAccountStatus.ACTIVE,
            PaperAccountStatus.SUSPENDED,
            PaperAccountStatus.ACTIVE,
        ]
    finally:
        verify.close()
