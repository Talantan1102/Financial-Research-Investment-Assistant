from __future__ import annotations

import threading
import uuid
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from app.core.database import get_db
from app.models.paper_account import (
    PaperAccount,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.models.user import User
from app.router.auth_router import get_current_user_required
from app.router.paper_trading_router import router
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.errors import PaperTradingError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session


@pytest.fixture
def user(db_session: Session) -> User:
    suffix = uuid.uuid4().hex
    row = User(
        username=f"paper-endpoint-{suffix}",
        email=f"paper-endpoint-{suffix}@example.test",
        hashed_password="not-used",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _app_for_session(session: Session, user: User | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    def override_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user_required] = lambda: user
    return app


def test_get_account_creates_and_commits_default_account(db_session: Session, user: User) -> None:
    client = TestClient(_app_for_session(db_session, user))

    response = client.get("/api/v0/paper-trading/account")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(response.json()["id"]),
        "generation": 1,
        "initial_cash": "1000000.00",
        "available_cash": "1000000.00",
        "frozen_cash": "0.00",
        "status": "active",
    }
    db_session.expire_all()
    persisted = db_session.scalar(select(PaperAccount).where(PaperAccount.user_id == user.id))
    assert persisted is not None
    assert persisted.available_cash == Decimal("1000000.00")


def test_get_account_requires_authentication(db_session: Session) -> None:
    response = TestClient(_app_for_session(db_session, None)).get("/api/v0/paper-trading/account")

    assert response.status_code == 401


def test_accounts_are_isolated_by_authenticated_user(db_session: Session, user: User) -> None:
    other = User(
        username=f"paper-other-{uuid.uuid4().hex}",
        email=f"paper-other-{uuid.uuid4().hex}@example.test",
        hashed_password="not-used",
    )
    db_session.add(other)
    db_session.flush()

    first = TestClient(_app_for_session(db_session, user)).get("/api/v0/paper-trading/account")
    second = TestClient(_app_for_session(db_session, other)).get("/api/v0/paper-trading/account")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]


def test_initial_cash_changes_exactly_once_with_append_only_ledger(
    db_session: Session, user: User
) -> None:
    client = TestClient(_app_for_session(db_session, user))

    changed = client.patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )
    repeated = client.patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "900000.00"},
    )

    assert changed.status_code == 200
    assert changed.json()["initial_cash"] == "800000.00"
    assert changed.json()["available_cash"] == "800000.00"
    assert changed.json()["frozen_cash"] == "0.00"
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "initial_cash_edit_not_allowed"
    ledgers = db_session.scalars(select(PaperCashLedger)).all()
    by_key = {row.business_key: row for row in ledgers}
    opening = next(row for row in ledgers if row.business_key.startswith("initial-deposit:"))
    reversal = by_key[f"initial-cash-edit-reversal:{opening.account_id}"]
    replacement = by_key[f"initial-cash-edit-deposit:{opening.account_id}"]
    assert (opening.kind, opening.amount) == ("initial_deposit", Decimal("1000000.00"))
    assert (reversal.kind, reversal.amount) == (
        "initial_deposit_reversal",
        Decimal("-1000000.00"),
    )
    assert (replacement.kind, replacement.amount) == (
        "initial_deposit",
        Decimal("800000.00"),
    )
    assert reversal.available_before == Decimal("1000000.00")
    assert reversal.available_after == Decimal("0.00")
    assert replacement.available_before == Decimal("0.00")
    assert replacement.available_after == Decimal("800000.00")
    assert len({row.business_key for row in ledgers}) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"initial_cash": "0"},
        {"initial_cash": "-1"},
        {"initial_cash": "NaN"},
        {"initial_cash": "Infinity"},
        {"initial_cash": "1.001"},
        {"initial_cash": "10000000000000000.00"},
        {"initial_cash": True},
    ],
)
def test_initial_cash_payload_is_strict_and_within_numeric_18_2(
    db_session: Session, user: User, payload: dict[str, object]
) -> None:
    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash", json=payload
    )

    assert response.status_code == 422


def test_initial_cash_edit_rejects_non_generation_one(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    service.get_or_create(user_id=cast(uuid.UUID, user.id))
    service.reset_confirmed(
        user_id=cast(uuid.UUID, user.id),
        initial_cash=Decimal("700000.00"),
        source_session_id="endpoint-test",
        confirmation_id="reset-1",
    )
    db_session.commit()

    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "initial_cash_edit_not_allowed"


def test_initial_cash_edit_rejects_ledger_or_holding_activity(
    db_session: Session, user: User
) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    service.append_ledger(
        account=account,
        kind="cash_adjustment",
        amount=Decimal("0.00"),
        available_after=cast(Decimal, account.available_cash),
        frozen_after=Decimal("0.00"),
        business_key=f"activity:{account.id}",
    )
    db_session.commit()

    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "initial_cash_edit_not_allowed"


def test_initial_cash_edit_rejects_holding_activity(db_session: Session, user: User) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    db_session.add(
        PaperHoldingLot(
            account_id=account.id,
            generation=account.generation,
            ts_code="600000.SH",
            name="Test Stock",
            source_fill_id=uuid.uuid4(),
            original_quantity=100,
            remaining_quantity=100,
            frozen_quantity=0,
            unit_cost=Decimal("10.0000"),
            available_on=date(2026, 7, 20),
        )
    )
    db_session.commit()

    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "initial_cash_edit_not_allowed"


def test_initial_cash_edit_rejects_frozen_cash(db_session: Session, user: User) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    account.frozen_cash = Decimal("100.00")  # type: ignore[assignment]
    account.available_cash = Decimal("999900.00")  # type: ignore[assignment]
    db_session.commit()

    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "initial_cash_edit_not_allowed"


def test_initial_cash_edit_rejects_suspended_account(db_session: Session, user: User) -> None:
    service = PaperAccountService(db_session)
    account = service.get_or_create(user_id=cast(uuid.UUID, user.id))
    account.status = PaperAccountStatus.SUSPENDED  # type: ignore[assignment]
    db_session.commit()

    response = TestClient(_app_for_session(db_session, user)).patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paper_account_not_found"


def test_initial_cash_edit_rolls_back_both_ledgers_and_account(
    db_session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(_app_for_session(db_session, user))
    assert client.get("/api/v0/paper-trading/account").status_code == 200
    original = PaperAccountService.append_ledger
    calls = 0

    def fail_second_append(self: PaperAccountService, **kwargs: object) -> PaperCashLedger:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PaperTradingError("forced_failure", "forced failure")
        return original(self, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(PaperAccountService, "append_ledger", fail_second_append)

    response = client.patch(
        "/api/v0/paper-trading/account/initial-cash",
        json={"initial_cash": "800000.00"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "forced_failure"
    db_session.expire_all()
    account = db_session.scalar(select(PaperAccount).where(PaperAccount.user_id == user.id))
    assert account is not None
    assert account.initial_cash == account.available_cash == Decimal("1000000.00")
    assert account.initial_cash_edited_at is None
    assert db_session.query(PaperCashLedger).count() == 1


def _committed_user(engine: Engine) -> uuid.UUID:
    with Session(engine) as session:
        suffix = uuid.uuid4().hex
        user = User(
            username=f"pec-{suffix[:12]}",
            email=f"pec-{suffix[:12]}@example.test",
            hashed_password="not-used",
        )
        session.add(user)
        session.commit()
        return cast(uuid.UUID, user.id)


def _app_for_engine(engine: Engine, user_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    def override_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user_required] = lambda: type(
        "AuthenticatedUser", (), {"id": user_id}
    )()
    return app


def test_concurrent_initial_cash_patch_allows_exactly_one(pg_test_engine: Engine) -> None:
    user_id = _committed_user(pg_test_engine)
    app = _app_for_engine(pg_test_engine, user_id)
    assert TestClient(app).get("/api/v0/paper-trading/account").status_code == 200
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    errors: list[BaseException] = []

    def patch(value: str) -> None:
        try:
            barrier.wait(timeout=5)
            response = TestClient(app).patch(
                "/api/v0/paper-trading/account/initial-cash",
                json={"initial_cash": value},
            )
            statuses.append(response.status_code)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=patch, args=(value,)) for value in ("800000", "900000")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert sorted(statuses) == [200, 409]
    with Session(pg_test_engine) as observer:
        account = observer.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
        assert account is not None
        assert account.initial_cash in {Decimal("800000.00"), Decimal("900000.00")}
        assert account.initial_cash == account.available_cash
        assert account.initial_cash_edited_at is not None
        ledgers = observer.scalars(
            select(PaperCashLedger).where(PaperCashLedger.account_id == account.id)
        ).all()
        assert len(ledgers) == 3


def test_model_exposes_edit_marker_and_holding_activity_table(
    db_session: Session, user: User
) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=cast(uuid.UUID, user.id))
    assert account.initial_cash_edited_at is None
    assert PaperHoldingLot.__tablename__ == "paper_holding_lots"
