from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, DecimalException

from sqlalchemy import func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.state import InstanceState

from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperAccountStatus,
    PaperCashLedger,
    PaperHoldingLot,
)
from app.services.paper_trading.errors import PaperTradingError

DEFAULT_INITIAL_CASH = Decimal("1000000.00")
_DEFAULT_COMMISSION_RATE = Decimal("0.00030000")
_DEFAULT_MINIMUM_COMMISSION = Decimal("5.00")
_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("9999999999999999.99")
_ACCOUNT_CREATE_CONSTRAINTS = {
    "uq_paper_accounts_active_user",
    "uq_paper_accounts_user_generation",
}
_LEDGER_BUSINESS_KEY_CONSTRAINT = "paper_cash_ledger_business_key_key"


class PaperAccountService:
    DEFAULT_INITIAL_CASH = DEFAULT_INITIAL_CASH

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(
        self, *, user_id: uuid.UUID, initial_cash: Decimal | None = None
    ) -> PaperAccount:
        user_id = _require_uuid(user_id)
        requested_cash = _positive_money(
            DEFAULT_INITIAL_CASH if initial_cash is None else initial_cash,
            code="invalid_initial_cash",
            field="initial_cash",
        )
        existing = self._find_active(user_id=user_id)
        if existing is not None:
            return existing
        if (
            self._session.scalar(
                select(PaperAccount.id).where(PaperAccount.user_id == user_id).limit(1)
            )
            is not None
        ):
            raise PaperTradingError("paper_account_not_found", "No active paper account")

        account = PaperAccount.new(
            user_id=user_id,
            generation=1,
            initial_cash=requested_cash,
            commission_rate=_DEFAULT_COMMISSION_RATE,
            minimum_commission=_DEFAULT_MINIMUM_COMMISSION,
        )
        try:
            with self._session.begin_nested():
                self._session.add(account)
                self._session.flush()
                self._append_initial_deposit(account)
                self._session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) not in _ACCOUNT_CREATE_CONSTRAINTS:
                raise
            self._session.expire_all()
            winner = self._find_active(user_id=user_id)
            if winner is None:
                raise
            return winner
        return account

    def get_active(self, *, user_id: uuid.UUID, for_update: bool = False) -> PaperAccount:
        user_id = _require_uuid(user_id)
        account = self._find_active(user_id=user_id, for_update=for_update)
        if account is None:
            raise PaperTradingError("paper_account_not_found", "模拟账户不存在")
        return account

    def append_ledger(
        self,
        *,
        account: PaperAccount,
        kind: str,
        amount: Decimal,
        available_after: Decimal,
        frozen_after: Decimal,
        business_key: str,
    ) -> PaperCashLedger:
        kind = _require_text(kind, field="kind", maximum=32, code="invalid_ledger_input")
        business_key = _require_text(
            business_key,
            field="business_key",
            maximum=128,
            code="invalid_ledger_input",
        )
        amount = _finite_money(amount, code="invalid_ledger_input", field="amount")
        available_after = _nonnegative_money(
            available_after,
            code="invalid_ledger_input",
            field="available_after",
        )
        frozen_after = _nonnegative_money(
            frozen_after,
            code="invalid_ledger_input",
            field="frozen_after",
        )
        state: InstanceState[PaperAccount] = sa_inspect(account)
        if not state.persistent or state.session is not self._session:
            raise PaperTradingError(
                "invalid_ledger_account", "account must be persistent in this session"
            )
        if account.status is not PaperAccountStatus.ACTIVE:
            raise PaperTradingError("stale_account_generation", "账户已重置，请重新操作")
        if self._session.is_modified(account, include_collections=False):
            raise PaperTradingError(
                "dirty_ledger_account", "account has pending changes in this transaction"
            )

        with self._session.no_autoflush:
            locked = self._session.scalar(
                select(PaperAccount)
                .where(
                    PaperAccount.id == account.id,
                    PaperAccount.user_id == account.user_id,
                    PaperAccount.generation == account.generation,
                    PaperAccount.status == PaperAccountStatus.ACTIVE,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if locked is None or locked is not account:
            raise PaperTradingError("stale_account_generation", "账户已重置，请重新操作")

        available_before = _nonnegative_money(
            locked.available_cash,
            code="invalid_ledger_input",
            field="available_before",
        )
        frozen_before = _nonnegative_money(
            locked.frozen_cash,
            code="invalid_ledger_input",
            field="frozen_before",
        )
        self._lock_ledger_business_key(business_key)
        if (
            self._session.scalar(
                select(PaperCashLedger.id).where(PaperCashLedger.business_key == business_key)
            )
            is not None
        ):
            raise PaperTradingError("duplicate_ledger_business_key", "资金流水业务键已存在")

        entry = PaperCashLedger(
            account_id=locked.id,
            generation=locked.generation,
            kind=kind,
            amount=amount,
            available_before=available_before,
            available_after=available_after,
            frozen_before=frozen_before,
            frozen_after=frozen_after,
            business_key=business_key,
        )
        try:
            with self._session.begin_nested():
                locked.available_cash = available_after
                locked.frozen_cash = frozen_after
                self._session.add(entry)
                self._session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) != _LEDGER_BUSINESS_KEY_CONSTRAINT:
                raise
            raise PaperTradingError(
                "duplicate_ledger_business_key", "资金流水业务键已存在"
            ) from exc
        return entry

    def reset_confirmed(
        self,
        *,
        user_id: uuid.UUID,
        initial_cash: Decimal,
        source_session_id: str,
        confirmation_id: str,
    ) -> PaperAccount:
        user_id = _require_uuid(user_id)
        initial_cash = _positive_money(
            initial_cash, code="invalid_initial_cash", field="initial_cash"
        )
        source_session_id = _require_text(
            source_session_id,
            field="source_session_id",
            maximum=64,
            code="invalid_reset_confirmation",
        )
        confirmation_id = _require_text(
            confirmation_id,
            field="confirmation_id",
            maximum=64,
            code="invalid_reset_confirmation",
        )

        existing = self._confirmed_reset(
            source_session_id=source_session_id,
            confirmation_id=confirmation_id,
        )
        if existing is not None:
            return self._validate_confirmed_reset(
                existing, user_id=user_id, initial_cash=initial_cash
            )

        self._lock_reset_confirmation(
            source_session_id=source_session_id,
            confirmation_id=confirmation_id,
        )
        existing = self._confirmed_reset(
            source_session_id=source_session_id,
            confirmation_id=confirmation_id,
        )
        if existing is not None:
            return self._validate_confirmed_reset(
                existing, user_id=user_id, initial_cash=initial_cash
            )

        self._lock_user_resets(user_id)
        existing = self._confirmed_reset(
            source_session_id=source_session_id,
            confirmation_id=confirmation_id,
        )
        if existing is not None:
            return self._validate_confirmed_reset(
                existing, user_id=user_id, initial_cash=initial_cash
            )

        old = self.get_active(user_id=user_id, for_update=True)
        summary = _account_summary(old)
        old.status = PaperAccountStatus.ARCHIVED  # type: ignore[assignment]
        self._session.flush()

        new = PaperAccount.new(
            user_id=user_id,
            generation=int(old.generation) + 1,
            initial_cash=initial_cash,
            commission_rate=_DEFAULT_COMMISSION_RATE,
            minimum_commission=_DEFAULT_MINIMUM_COMMISSION,
        )
        self._session.add(new)
        self._session.flush()
        self._append_initial_deposit(new)
        self._session.add(
            PaperAccountResetAudit(
                user_id=user_id,
                old_account_id=old.id,
                new_account_id=new.id,
                old_generation=old.generation,
                new_generation=new.generation,
                source_session_id=source_session_id,
                confirmation_id=confirmation_id,
                pre_reset_summary=summary,
            )
        )
        self._session.flush()
        return new

    def edit_initial_cash_once(self, *, user_id: uuid.UUID, initial_cash: Decimal) -> PaperAccount:
        """Replace generation-one opening cash before any account activity."""
        user_id = _require_uuid(user_id)
        initial_cash = _positive_money(
            initial_cash, code="invalid_initial_cash", field="initial_cash"
        )
        account = self.get_active(user_id=user_id, for_update=True)
        if not self._can_edit_initial_cash(account):
            raise PaperTradingError(
                "initial_cash_edit_not_allowed",
                "Initial cash can only be edited once before account activity",
            )

        old_cash = _nonnegative_money(
            account.initial_cash,
            code="invalid_initial_cash",
            field="initial_cash",
        )
        self.append_ledger(
            account=account,
            kind="initial_deposit_reversal",
            amount=-old_cash,
            available_after=Decimal("0.00"),
            frozen_after=Decimal("0.00"),
            business_key=f"initial-cash-edit-reversal:{account.id}",
        )
        self.append_ledger(
            account=account,
            kind="initial_deposit",
            amount=initial_cash,
            available_after=initial_cash,
            frozen_after=Decimal("0.00"),
            business_key=f"initial-cash-edit-deposit:{account.id}",
        )
        account.initial_cash = initial_cash  # type: ignore[assignment]
        account.initial_cash_edited_at = datetime.now(UTC)  # type: ignore[assignment]
        self._session.flush()
        return account

    def _can_edit_initial_cash(self, account: PaperAccount) -> bool:
        if (
            account.generation != 1
            or account.initial_cash_edited_at is not None
            or account.frozen_cash != Decimal("0.00")
        ):
            return False

        ledgers = self._session.scalars(
            select(PaperCashLedger).where(
                PaperCashLedger.account_id == account.id,
                PaperCashLedger.generation == account.generation,
            )
        ).all()
        if len(ledgers) != 1:
            return False
        opening = ledgers[0]
        if (
            opening.kind != "initial_deposit"
            or opening.business_key != f"initial-deposit:{account.id}"
            or opening.amount != account.initial_cash
            or opening.available_before != Decimal("0.00")
            or opening.available_after != account.available_cash
            or opening.frozen_before != Decimal("0.00")
            or opening.frozen_after != Decimal("0.00")
        ):
            return False

        holding_count = self._session.scalar(
            select(func.count())
            .select_from(PaperHoldingLot)
            .where(
                PaperHoldingLot.account_id == account.id,
                PaperHoldingLot.generation == account.generation,
            )
        )
        if holding_count:
            return False

        bind = self._session.get_bind()
        if sa_inspect(bind).has_table("paper_orders"):
            order_exists = self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM paper_orders "
                    "WHERE account_id = :account_id AND account_generation = :generation)"
                ),
                {"account_id": account.id, "generation": account.generation},
            )
            if order_exists:
                return False
        return True

    def _find_active(self, *, user_id: uuid.UUID, for_update: bool = False) -> PaperAccount | None:
        statement = select(PaperAccount).where(
            PaperAccount.user_id == user_id,
            PaperAccount.status == PaperAccountStatus.ACTIVE,
        )
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def _append_initial_deposit(self, account: PaperAccount) -> PaperCashLedger:
        entry = PaperCashLedger(
            account_id=account.id,
            generation=account.generation,
            kind="initial_deposit",
            amount=account.initial_cash,
            available_before=Decimal("0.00"),
            available_after=account.initial_cash,
            frozen_before=Decimal("0.00"),
            frozen_after=Decimal("0.00"),
            business_key=f"initial-deposit:{account.id}",
        )
        self._session.add(entry)
        return entry

    def _confirmed_reset(
        self, *, source_session_id: str, confirmation_id: str
    ) -> PaperAccountResetAudit | None:
        return self._session.scalar(
            select(PaperAccountResetAudit).where(
                PaperAccountResetAudit.source_session_id == source_session_id,
                PaperAccountResetAudit.confirmation_id == confirmation_id,
            )
        )

    def _validate_confirmed_reset(
        self,
        audit: PaperAccountResetAudit,
        *,
        user_id: uuid.UUID,
        initial_cash: Decimal,
    ) -> PaperAccount:
        account = self._session.get(PaperAccount, audit.new_account_id)
        if (
            audit.user_id != user_id
            or account is None
            or account.user_id != user_id
            or account.initial_cash != initial_cash
        ):
            raise PaperTradingError("reset_confirmation_conflict", "重置确认与原请求不一致")
        return account

    def _lock_user_resets(self, user_id: uuid.UUID) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
            {"user_id": str(user_id)},
        )

    def _lock_reset_confirmation(self, *, source_session_id: str, confirmation_id: str) -> None:
        lock_key = f"{len(source_session_id)}:{source_session_id}{confirmation_id}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    def _lock_ledger_business_key(self, business_key: str) -> None:
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:business_key, 0))"),
            {"business_key": business_key},
        )


def _account_summary(account: PaperAccount) -> dict[str, object]:
    return {
        "account_id": str(account.id),
        "generation": account.generation,
        "initial_cash": f"{account.initial_cash:.2f}",
        "available_cash": f"{account.available_cash:.2f}",
        "frozen_cash": f"{account.frozen_cash:.2f}",
        "commission_rate": f"{account.commission_rate:.8f}",
        "minimum_commission": f"{account.minimum_commission:.2f}",
        "status": account.status.value,
        "version": account.version,
    }


def _require_uuid(value: object) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise PaperTradingError("invalid_user_id", "user_id must be a UUID")
    return value


def _require_text(value: object, *, field: str, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PaperTradingError(code, f"{field} must be nonblank and at most {maximum} characters")
    return value


def _positive_money(value: object, *, code: str, field: str) -> Decimal:
    normalized = _finite_money(value, code=code, field=field)
    if normalized <= 0:
        raise PaperTradingError(code, f"{field} must be positive")
    return normalized


def _nonnegative_money(value: object, *, code: str, field: str) -> Decimal:
    normalized = _finite_money(value, code=code, field=field)
    if normalized < 0:
        raise PaperTradingError(code, f"{field} must be nonnegative")
    return normalized


def _finite_money(value: object, *, code: str, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PaperTradingError(code, f"{field} must be a finite Decimal")
    try:
        normalized = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    except DecimalException as exc:
        raise PaperTradingError(code, f"{field} is outside the supported range") from exc
    if abs(normalized) > _MAX_MONEY:
        raise PaperTradingError(code, f"{field} is outside the supported range")
    return normalized


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)
