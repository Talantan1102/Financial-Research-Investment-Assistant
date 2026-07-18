from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from typing import cast

import pytest
from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperAccountStatus,
    PaperCashLedger,
)
from app.models.user import User
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.errors import PaperTradingError
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-service-{suffix}",
        email=f"paper-service-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_get_or_create_defaults_to_one_million(db_session: Session, user: User) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))

    assert account.generation == 1
    assert account.initial_cash == Decimal("1000000.00")
    assert account.available_cash == Decimal("1000000.00")
    assert account.frozen_cash == Decimal("0.00")
    ledger = db_session.scalar(select(PaperCashLedger))
    assert ledger is not None
    assert ledger.kind == "initial_deposit"
    assert ledger.amount == Decimal("1000000.00")
    assert ledger.available_before == Decimal("0.00")
    assert ledger.available_after == Decimal("1000000.00")
    assert ledger.frozen_before == ledger.frozen_after == Decimal("0.00")


def test_get_or_create_accepts_explicit_initial_cash_and_does_not_duplicate(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    first = service.get_or_create(user_id=cast(uuid.UUID, user.id), initial_cash=Decimal("800000"))
    second = service.get_or_create(user_id=cast(uuid.UUID, user.id), initial_cash=Decimal("900000"))

    assert second.id == first.id
    assert second.initial_cash == Decimal("800000.00")
    assert db_session.query(PaperCashLedger).count() == 1


def test_get_active_missing_is_stable_error(db_session: Session, user: User) -> None:
    with pytest.raises(PaperTradingError) as caught:
        PaperAccountService(db_session).get_active(user_id=cast(uuid.UUID, user.id))

    assert caught.value.code == "paper_account_not_found"


@pytest.mark.parametrize(
    "cash",
    [
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("10000000000000000.00"),
    ],
)
def test_initial_cash_must_be_finite_and_positive(
    db_session: Session, user: User, cash: Decimal
) -> None:
    with pytest.raises(PaperTradingError) as caught:
        PaperAccountService(db_session).get_or_create(
            user_id=cast(uuid.UUID, user.id), initial_cash=cash
        )

    assert caught.value.code == "invalid_initial_cash"


def test_append_ledger_captures_before_and_after_balances(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))

    entry = service.append_ledger(
        account=account,
        kind="order_freeze",
        amount=Decimal("-1000.00"),
        available_after=Decimal("999000.00"),
        frozen_after=Decimal("1000.00"),
        business_key="order-freeze:request-1",
    )

    assert entry.available_before == Decimal("1000000.00")
    assert entry.available_after == Decimal("999000.00")
    assert entry.frozen_before == Decimal("0.00")
    assert entry.frozen_after == Decimal("1000.00")
    assert account.available_cash == Decimal("999000.00")
    assert account.frozen_cash == Decimal("1000.00")


def test_append_ledger_rejects_blank_key_and_invalid_balances(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))

    with pytest.raises(PaperTradingError) as caught:
        service.append_ledger(
            account=account,
            kind="order_freeze",
            amount=Decimal("1"),
            available_after=Decimal("NaN"),
            frozen_after=Decimal("0"),
            business_key=" ",
        )

    assert caught.value.code == "invalid_ledger_input"


def test_append_ledger_preserves_unique_business_key(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    service.append_ledger(
        account=account,
        kind="cash_adjustment",
        amount=Decimal("0"),
        available_after=cast(Decimal, account.available_cash),
        frozen_after=cast(Decimal, account.frozen_cash),
        business_key="same-key",
    )

    with pytest.raises(PaperTradingError) as caught:
        service.append_ledger(
            account=account,
            kind="cash_adjustment",
            amount=Decimal("0"),
            available_after=cast(Decimal, account.available_cash),
            frozen_after=cast(Decimal, account.frozen_cash),
            business_key="same-key",
        )

    assert caught.value.code == "duplicate_ledger_business_key"


def test_append_ledger_rejects_balance_transition_that_does_not_match_amount(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))

    with pytest.raises(PaperTradingError) as caught:
        service.append_ledger(
            account=account,
            kind="order_freeze",
            amount=Decimal("-1000.00"),
            available_after=Decimal("999500.00"),
            frozen_after=Decimal("500.00"),
            business_key="invalid-transition",
        )

    assert caught.value.code == "invalid_ledger_transition"


def test_append_ledger_rejects_detached_account(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    db_session.expunge(account)

    with pytest.raises(PaperTradingError) as caught:
        service.append_ledger(
            account=account,
            kind="cash_adjustment",
            amount=Decimal("0"),
            available_after=Decimal("1000000.00"),
            frozen_after=Decimal("0.00"),
            business_key="detached-account",
        )

    assert caught.value.code == "invalid_ledger_account"


def test_append_ledger_rejects_account_from_another_session(
    db_session: Session, user: User
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    foreign_session = Session(bind=db_session.connection())
    try:
        with pytest.raises(PaperTradingError) as caught:
            PaperAccountService(foreign_session).append_ledger(
                account=account,
                kind="cash_adjustment",
                amount=Decimal("0"),
                available_after=Decimal("1000000.00"),
                frozen_after=Decimal("0.00"),
                business_key="foreign-session",
            )
    finally:
        foreign_session.close()

    assert caught.value.code == "invalid_ledger_account"


def test_append_ledger_rejects_archived_generation(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    old = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000"),
        source_session_id="archive-session",
        confirmation_id="archive-confirmation",
    )

    with pytest.raises(PaperTradingError) as caught:
        service.append_ledger(
            account=old,
            kind="cash_adjustment",
            amount=Decimal("0"),
            available_after=Decimal("1000000.00"),
            frozen_after=Decimal("0.00"),
            business_key="archived-account",
        )

    assert caught.value.code == "stale_account_generation"


def test_reset_archives_old_generation_and_keeps_audit_snapshot(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    old = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    old.available_cash = Decimal("750000.00")  # type: ignore[assignment]
    old.frozen_cash = Decimal("250000.00")  # type: ignore[assignment]
    db_session.flush()
    pre_reset_version = old.version

    new = service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )

    assert old.status is PaperAccountStatus.ARCHIVED
    assert new.generation == 2
    assert new.available_cash == Decimal("800000.00")
    assert db_session.query(PaperAccount).count() == 2
    assert db_session.query(PaperCashLedger).count() == 2
    audit = db_session.scalar(select(PaperAccountResetAudit))
    assert audit is not None
    assert audit.old_account_id == old.id
    assert audit.new_account_id == new.id
    assert audit.pre_reset_summary == {
        "account_id": str(old.id),
        "generation": 1,
        "initial_cash": "1000000.00",
        "available_cash": "750000.00",
        "frozen_cash": "250000.00",
        "commission_rate": "0.00030000",
        "minimum_commission": "5.00",
        "status": "active",
        "version": pre_reset_version,
    }


def test_reset_retry_returns_same_account_without_duplicate_history(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    service.get_or_create(user_id=cast(uuid.UUID, user.id))
    first = service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )
    second = service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000.00"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )

    assert second.id == first.id
    assert db_session.query(PaperAccount).count() == 2
    assert db_session.query(PaperAccountResetAudit).count() == 1
    assert db_session.query(PaperCashLedger).count() == 2


def test_reset_confirmation_mismatch_fails_closed(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    service.get_or_create(user_id=cast(uuid.UUID, user.id))
    service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )

    with pytest.raises(PaperTradingError) as caught:
        service.reset_confirmed(
            user_id=cast(uuid.UUID, user.id),
            initial_cash=Decimal("900000"),
            source_session_id="session-1",
            confirmation_id="confirm-1",
        )

    assert caught.value.code == "reset_confirmation_conflict"


def test_reset_confirmation_cannot_cross_users(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    user_id = cast(uuid.UUID, user.id)
    service.get_or_create(user_id=user_id)
    service.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )
    suffix = uuid.uuid4().hex
    other = User(
        username=f"paper-other-{suffix}",
        email=f"paper-other-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.flush()

    with pytest.raises(PaperTradingError) as caught:
        service.reset_confirmed(
            user_id=cast(uuid.UUID, other.id),
            initial_cash=Decimal("800000"),
            source_session_id="session-1",
            confirmation_id="confirm-1",
        )

    assert caught.value.code == "reset_confirmation_conflict"


def test_distinct_confirmations_create_sequential_generations(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    user_id = cast(uuid.UUID, user.id)
    service.get_or_create(user_id=user_id)
    second = service.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("800000"),
        source_session_id="session-1",
        confirmation_id="confirm-1",
    )
    third = service.reset_confirmed(
        user_id=user_id,
        initial_cash=Decimal("700000"),
        source_session_id="session-1",
        confirmation_id="confirm-2",
    )

    assert second.status is PaperAccountStatus.ARCHIVED
    assert third.generation == 3
    assert db_session.query(PaperAccountResetAudit).count() == 2


def _committed_user(engine: Engine) -> uuid.UUID:
    with Session(engine) as session:
        suffix = uuid.uuid4().hex
        user = User(
            username=f"paper-concurrent-{suffix}",
            email=f"paper-concurrent-{suffix}@example.test",
            hashed_password="not-used",
        )
        session.add(user)
        session.commit()
        return cast(uuid.UUID, user.id)


def test_get_or_create_does_not_commit_callers_transaction(pg_test_engine: Engine) -> None:
    user_id = _committed_user(pg_test_engine)
    with Session(pg_test_engine) as first:
        PaperAccountService(first).get_or_create(user_id=user_id)
        first.rollback()

    with Session(pg_test_engine) as observer:
        assert observer.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id)) is None

    with Session(pg_test_engine) as writer:
        created = PaperAccountService(writer).get_or_create(user_id=user_id)
        account_id = cast(uuid.UUID, created.id)
        writer.commit()

    with Session(pg_test_engine) as observer:
        assert observer.get(PaperAccount, account_id) is not None


def test_concurrent_get_or_create_returns_single_account(pg_test_engine: Engine) -> None:
    user_id = _committed_user(pg_test_engine)
    barrier = threading.Barrier(2)
    ids: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def create() -> None:
        try:
            with Session(pg_test_engine) as session:
                barrier.wait(timeout=5)
                account = PaperAccountService(session).get_or_create(user_id=user_id)
                session.commit()
                ids.append(cast(uuid.UUID, account.id))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert len(ids) == 2
    assert ids[0] == ids[1]
    with Session(pg_test_engine) as observer:
        account = observer.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
        assert account is not None
        assert (
            len(
                observer.scalars(
                    select(PaperCashLedger).where(PaperCashLedger.account_id == account.id)
                ).all()
            )
            == 1
        )


def test_concurrent_cross_user_confirmation_conflict_is_stable(
    pg_test_engine: Engine,
) -> None:
    user_ids = [_committed_user(pg_test_engine), _committed_user(pg_test_engine)]
    for user_id in user_ids:
        with Session(pg_test_engine) as session:
            PaperAccountService(session).get_or_create(user_id=user_id)
            session.commit()
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def reset(user_id: uuid.UUID) -> None:
        try:
            with Session(pg_test_engine) as session:
                barrier.wait(timeout=5)
                try:
                    PaperAccountService(session).reset_confirmed(
                        user_id=user_id,
                        initial_cash=Decimal("800000"),
                        source_session_id="shared-session",
                        confirmation_id="shared-confirmation",
                    )
                    session.commit()
                    results.append("created")
                except PaperTradingError as exc:
                    session.rollback()
                    results.append(exc.code)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=reset, args=(user_id,)) for user_id in user_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(results) == ["created", "reset_confirmation_conflict"]


def test_concurrent_distinct_resets_get_sequential_generations(
    pg_test_engine: Engine,
) -> None:
    user_id = _committed_user(pg_test_engine)
    with Session(pg_test_engine) as session:
        PaperAccountService(session).get_or_create(user_id=user_id)
        session.commit()
    barrier = threading.Barrier(2)
    generations: list[int] = []
    errors: list[BaseException] = []

    def reset(confirmation_id: str) -> None:
        try:
            with Session(pg_test_engine) as session:
                barrier.wait(timeout=5)
                account = PaperAccountService(session).reset_confirmed(
                    user_id=user_id,
                    initial_cash=Decimal("800000"),
                    source_session_id="session-concurrent",
                    confirmation_id=confirmation_id,
                )
                session.commit()
                generations.append(cast(int, account.generation))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=reset, args=(confirmation_id,))
        for confirmation_id in ("confirm-a", "confirm-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(generations) == [2, 3]


def _create_committed_account(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = _committed_user(engine)
    with Session(engine) as session:
        account = PaperAccountService(session).get_or_create(user_id=user_id)
        session.commit()
        return user_id, cast(uuid.UUID, account.id)


def test_concurrent_ledger_updates_use_locked_current_balance(pg_test_engine: Engine) -> None:
    _, account_id = _create_committed_account(pg_test_engine)
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def freeze(key: str) -> None:
        try:
            with Session(pg_test_engine) as session:
                account = session.get(PaperAccount, account_id)
                assert account is not None
                barrier.wait(timeout=5)
                try:
                    PaperAccountService(session).append_ledger(
                        account=account,
                        kind="order_freeze",
                        amount=Decimal("-1000.00"),
                        available_after=Decimal("999000.00"),
                        frozen_after=Decimal("1000.00"),
                        business_key=key,
                    )
                    session.commit()
                    results.append("created")
                except PaperTradingError as exc:
                    session.rollback()
                    results.append(exc.code)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=freeze, args=(key,))
        for key in ("freeze-concurrent-a", "freeze-concurrent-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(results) == ["created", "invalid_ledger_transition"]
    with Session(pg_test_engine) as observer:
        account = observer.get(PaperAccount, account_id)
        assert account is not None
        assert account.available_cash == Decimal("999000.00")
        assert account.frozen_cash == Decimal("1000.00")


def test_concurrent_same_business_key_is_stable_and_preserves_outer_transactions(
    pg_test_engine: Engine,
) -> None:
    account_ids = [
        _create_committed_account(pg_test_engine)[1],
        _create_committed_account(pg_test_engine)[1],
    ]
    barrier = threading.Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def append(account_id: uuid.UUID) -> None:
        try:
            with Session(pg_test_engine) as session:
                account = session.get(PaperAccount, account_id)
                assert account is not None
                barrier.wait(timeout=5)
                try:
                    PaperAccountService(session).append_ledger(
                        account=account,
                        kind="cash_adjustment",
                        amount=Decimal("0"),
                        available_after=Decimal("1000000.00"),
                        frozen_after=Decimal("0.00"),
                        business_key="concurrent-shared-key",
                    )
                    session.commit()
                    results.append("created")
                except PaperTradingError as exc:
                    # The normalized conflict must leave the caller transaction usable.
                    session.execute(select(PaperAccount.id).limit(1))
                    session.rollback()
                    results.append(exc.code)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(account_id,)) for account_id in account_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(results) == ["created", "duplicate_ledger_business_key"]
