from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperFill,
    PaperLotReservation,
    PaperOrder,
)
from app.schemas.paper_trading import OrderDraft, OrderPreview
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import TradingClock
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.fee_schedule import FeeSchedule
from app.services.paper_trading.quote_provider import RealtimeQuoteProvider, assert_fresh_quote
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import MarketPhase, QuoteLevel, RealtimeQuote, RuleSet

SHANGHAI = ZoneInfo("Asia/Shanghai")
_TS_CODE = re.compile(r"\d{6}\.(?:SH|SZ)")
_CENT = Decimal("0.01")
_PROPOSAL_UNIQUE_CONSTRAINT = "uq_paper_orders_account_generation_proposal"
_MAX_CONFIRMATION_ID_LENGTH = 128


class PaperOrderService:
    def __init__(
        self,
        session: Session,
        *,
        quote_provider: RealtimeQuoteProvider,
        clock: TradingClock,
        rulebook: RuleBook,
        fee_schedule: FeeSchedule | None = None,
        now: Callable[[], datetime],
    ) -> None:
        self._session = session
        self.quote_provider = quote_provider
        self.clock = clock
        self.rulebook = rulebook
        self.fee_schedule = fee_schedule or FeeSchedule.from_builtin_fixture()
        self.account_service = PaperAccountService(session)
        self._now = now

    def prepare_order(
        self,
        *,
        user_id: uuid.UUID,
        session_id: str,
        message_id: str,
        side: str,
        ts_code: str,
        name: str,
        quantity: int,
        order_type: str,
        limit_price: Decimal | None,
    ) -> tuple[PaperOrder, OrderPreview]:
        user_id = _require_uuid(user_id, field="user_id")
        session_id = _require_text(session_id, field="session_id", maximum=64)
        message_id = _require_text(message_id, field="message_id", maximum=64)
        draft = _draft(
            side=side,
            ts_code=ts_code,
            name=name,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
        )

        # Network I/O must not hold the account row lock. Everything after the
        # fetch is revalidated against the locked account snapshot.
        quote = self._quote(draft.ts_code)
        account = self.account_service.get_active(user_id=user_id, for_update=True)
        now = self._current_time()
        proposal = draft.model_dump(mode="json")
        fingerprint = _proposal_fingerprint(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            proposal=proposal,
        )
        existing = self._proposal_by_fingerprint(account=account, fingerprint=fingerprint)
        if existing is not None:
            self._validate_idempotent_proposal(
                existing,
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                proposal=proposal,
            )
            preview = self._calculate_preview(
                account=account,
                order_id=cast(uuid.UUID, existing.id),
                draft=draft,
                normalize_quote_name=False,
                quote=quote,
                now=now,
            )
            return existing, preview

        order_id = uuid.uuid4()
        preview = self._calculate_preview(
            account=account,
            order_id=order_id,
            draft=draft,
            normalize_quote_name=False,
            quote=quote,
            now=now,
        )
        order = PaperOrder(
            id=order_id,
            account_id=account.id,
            account_generation=account.generation,
            user_id=user_id,
            client_request_id=None,
            source_session_id=session_id,
            source_message_id=message_id,
            proposal_fingerprint=fingerprint,
            ts_code=draft.ts_code,
            name=preview.quote.name,
            side=draft.side,
            order_type=draft.order_type,
            quantity=draft.quantity,
            limit_price=draft.limit_price,
            filled_quantity=0,
            avg_fill_price=None,
            status=OrderStatus.AWAITING_CONFIRMATION,
            original_proposal=proposal,
            confirmed_payload=None,
            user_edits=None,
            quote_snapshot=preview.quote.model_dump(mode="json"),
            rules_version=preview.rules_version,
            reject_code=None,
            reject_message=None,
            expires_at=self._expires_at(now),
            confirmed_at=None,
            completed_at=None,
        )
        try:
            with self._session.begin_nested():
                self._session.add(order)
                self._session.flush()
        except IntegrityError as exc:
            if _constraint_name(exc) != _PROPOSAL_UNIQUE_CONSTRAINT:
                raise
            winner = self._proposal_by_fingerprint(account=account, fingerprint=fingerprint)
            if winner is None:
                raise
            self._validate_idempotent_proposal(
                winner,
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                proposal=proposal,
            )
            return winner, preview.model_copy(update={"order_id": winner.id})
        return order, preview

    def preview(
        self,
        *,
        user_id: uuid.UUID,
        order_id: uuid.UUID,
        draft: OrderDraft,
    ) -> OrderPreview:
        user_id = _require_uuid(user_id, field="user_id")
        order_id = _require_uuid(order_id, field="order_id")
        if not isinstance(draft, OrderDraft):
            raise PaperTradingError("invalid_order", "draft must be an OrderDraft")
        order = self._owned_order(user_id=user_id, order_id=order_id)
        account = self.account_service.get_active(user_id=user_id)
        if order.account_id != account.id or order.account_generation != account.generation:
            raise PaperTradingError("stale_account_generation", "账户已重置，请重新下单")
        normalized_draft = _canonical_draft(draft)
        quote = self._quote(normalized_draft.ts_code)
        now = self._current_time()
        return self._calculate_preview(
            account=account,
            order_id=order_id,
            draft=normalized_draft,
            normalize_quote_name=True,
            quote=quote,
            now=now,
        )

    def confirm(
        self,
        *,
        user_id: uuid.UUID,
        order_id: uuid.UUID,
        draft: OrderDraft,
        client_request_id: str,
    ) -> PaperOrder:
        user_id = _require_uuid(user_id, field="user_id")
        order_id = _require_uuid(order_id, field="order_id")
        client_request_id = _require_text(
            client_request_id,
            field="client_request_id",
            maximum=_MAX_CONFIRMATION_ID_LENGTH,
        )
        if not isinstance(draft, OrderDraft):
            raise PaperTradingError("invalid_order", "draft must be an OrderDraft")
        normalized_draft = _canonical_draft(draft)

        preflight_order = self._owned_order(user_id=user_id, order_id=order_id)
        existing = self._by_client_request_id(user_id=user_id, client_request_id=client_request_id)
        if existing is not None:
            self._validate_confirmation_retry(existing, order_id=order_id, draft=normalized_draft)
            return existing

        preflight_now = self._current_time()
        preflight_expired = preflight_now >= preflight_order.expires_at
        quote = None if preflight_expired else self._quote(normalized_draft.ts_code)

        self._lock_confirmation_key(user_id=user_id, client_request_id=client_request_id)
        existing = self._by_client_request_id(user_id=user_id, client_request_id=client_request_id)
        if existing is not None:
            self._validate_confirmation_retry(existing, order_id=order_id, draft=normalized_draft)
            return existing

        order = self._owned_order(user_id=user_id, order_id=order_id, for_update=True)
        if order.status is not OrderStatus.AWAITING_CONFIRMATION:
            raise PaperTradingError(
                "order_not_awaiting_confirmation", "order is no longer awaiting confirmation"
            )
        account = self.account_service.get_active(user_id=user_id, for_update=True)
        self._session.refresh(account, with_for_update=True)
        if order.account_id != account.id or order.account_generation != account.generation:
            raise PaperTradingError("stale_account_generation", "account generation has changed")

        now = self._current_time()
        if preflight_expired and now < order.expires_at:
            raise PaperTradingError(
                "trading_clock_moved_backwards", "trading clock moved backwards during confirmation"
            )
        if now >= order.expires_at:
            payload = normalized_draft.model_dump(mode="json")
            order.client_request_id = client_request_id
            order.confirmed_payload = payload
            order.user_edits = _json_diff(order.original_proposal, payload)
            order.confirmed_at = now
            order.status = OrderStatus.CANCELLED
            order.completed_at = now
            self._session.flush()
            return order

        if quote is None:  # guarded by the monotonic expiry check above
            raise PaperTradingError("quote_unavailable", "quote was not fetched for confirmation")
        preview = self._calculate_preview(
            account=account,
            order_id=order_id,
            draft=normalized_draft,
            normalize_quote_name=True,
            quote=quote,
            now=now,
        )
        final_draft = preview.draft
        continuous = preview.market_phase in {MarketPhase.MORNING, MarketPhase.AFTERNOON}
        if final_draft.order_type is OrderType.MARKET and not continuous:
            raise PaperTradingError(
                "market_order_outside_continuous_trading",
                "market orders require continuous trading",
            )

        if final_draft.side is OrderSide.BUY:
            reserved_cash = self._reserve_buy(
                account=account,
                order_id=cast(uuid.UUID, order.id),
                draft=final_draft,
                quote=quote,
                on=now.astimezone(SHANGHAI).date(),
            )
            reserved_quantity = 0
        else:
            reserved_cash = Decimal("0.00")
            reserved_quantity = self._reserve_sell(
                account=account,
                order=order,
                draft=final_draft,
                on=now.astimezone(SHANGHAI).date(),
            )

        payload = final_draft.model_dump(mode="json")
        order.client_request_id = client_request_id
        order.ts_code = final_draft.ts_code
        order.name = preview.quote.name
        order.side = final_draft.side
        order.order_type = final_draft.order_type
        order.quantity = final_draft.quantity
        order.limit_price = final_draft.limit_price
        order.reserved_cash = reserved_cash
        order.reserved_quantity = reserved_quantity
        order.confirmed_payload = payload
        order.user_edits = _json_diff(order.original_proposal, payload)
        confirmed_rules = self.rulebook.resolve(
            ts_code=quote.ts_code,
            board=_board(quote.ts_code),
            risk_warning=_risk_warning(quote.name),
            side=final_draft.side.value,
            on=now.astimezone(SHANGHAI).date(),
        )
        daily_lower, daily_upper = self.rulebook.price_bounds(confirmed_rules, quote.previous_close)
        order.quote_snapshot = {
            **preview.quote.model_dump(mode="json"),
            "daily_lower_bound": str(daily_lower),
            "daily_upper_bound": str(daily_upper),
            "price_tick": str(confirmed_rules.price_tick),
        }
        order.rules_version = preview.rules_version
        order.confirmed_at = now
        order.status = OrderStatus.OPEN if continuous else OrderStatus.QUEUED
        self._session.flush()
        return order

    def _reserve_buy(
        self,
        *,
        account: PaperAccount,
        order_id: uuid.UUID,
        draft: OrderDraft,
        quote: RealtimeQuote,
        on: date,
    ) -> Decimal:
        rules = self.rulebook.resolve(
            ts_code=quote.ts_code,
            board=_board(quote.ts_code),
            risk_warning=_risk_warning(quote.name),
            side=OrderSide.BUY.value,
            on=on,
        )
        if draft.order_type is OrderType.LIMIT:
            assert draft.limit_price is not None
            maximum_gross = _money(draft.limit_price * draft.quantity)
        else:
            _, upper = self.rulebook.price_bounds(rules, quote.previous_close)
            maximum_gross = _money(upper * draft.quantity)
        fees = self.fee_schedule.calculate(
            side=OrderSide.BUY.value,
            gross=maximum_gross,
            commission_rate=cast(Decimal, account.commission_rate),
            minimum_commission=cast(Decimal, account.minimum_commission),
        )
        reserve = _money(maximum_gross + fees.total)
        available = _money(cast(Decimal, account.available_cash))
        frozen = _money(cast(Decimal, account.frozen_cash))
        if reserve > available:
            raise PaperTradingError("insufficient_cash", "paper account has insufficient cash")
        self.account_service.append_ledger(
            account=account,
            kind="order_freeze",
            amount=-reserve,
            available_after=_money(available - reserve),
            frozen_after=_money(frozen + reserve),
            business_key=f"order-freeze:{order_id}",
            order_id=order_id,
        )
        return reserve

    def _reserve_sell(
        self, *, account: PaperAccount, order: PaperOrder, draft: OrderDraft, on: date
    ) -> int:
        candidates = self._session.execute(
            select(PaperHoldingLot, PaperOrder)
            .join(PaperFill, PaperFill.id == PaperHoldingLot.source_fill_id)
            .join(PaperOrder, PaperOrder.id == PaperFill.order_id)
            .where(
                PaperHoldingLot.account_id == account.id,
                PaperHoldingLot.generation == account.generation,
                PaperHoldingLot.ts_code == draft.ts_code,
                PaperHoldingLot.available_on <= on,
                PaperHoldingLot.remaining_quantity > PaperHoldingLot.frozen_quantity,
            )
            .order_by(PaperHoldingLot.created_at, PaperHoldingLot.id)
            .with_for_update(of=PaperHoldingLot)
        ).all()
        lots: list[PaperHoldingLot] = []
        for lot, source_order in candidates:
            if (
                source_order.account_id != account.id
                or source_order.user_id != order.user_id
                or source_order.account_generation != account.generation
            ):
                raise PaperTradingError(
                    "invalid_holding_provenance", "holding lot provenance is inconsistent"
                )
            lots.append(lot)
        available = sum(int(lot.remaining_quantity) - int(lot.frozen_quantity) for lot in lots)
        if available < draft.quantity:
            raise PaperTradingError(
                "insufficient_sellable_quantity", "sellable position is insufficient"
            )
        remaining = draft.quantity
        for lot in lots:
            quantity = min(remaining, int(lot.remaining_quantity) - int(lot.frozen_quantity))
            lot.frozen_quantity = int(lot.frozen_quantity) + quantity  # type: ignore[assignment]
            self._session.add(
                PaperLotReservation(
                    order_id=order.id,
                    lot_id=lot.id,
                    account_id=account.id,
                    account_generation=account.generation,
                    reserved_quantity=quantity,
                    remaining_quantity=quantity,
                )
            )
            remaining -= quantity
            if remaining == 0:
                break
        return draft.quantity

    def _by_client_request_id(
        self, *, user_id: uuid.UUID, client_request_id: str
    ) -> PaperOrder | None:
        return self._session.scalar(
            select(PaperOrder)
            .where(
                PaperOrder.user_id == user_id,
                PaperOrder.client_request_id == client_request_id,
            )
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _validate_confirmation_retry(
        order: PaperOrder, *, order_id: uuid.UUID, draft: OrderDraft
    ) -> None:
        requested_payload = draft.model_dump(mode="json")
        accepted_payload = draft.model_copy(update={"name": order.name}).model_dump(mode="json")
        if order.id != order_id or order.confirmed_payload not in (
            requested_payload,
            accepted_payload,
        ):
            raise PaperTradingError(
                "confirmation_idempotency_conflict",
                "confirmation key does not match the existing order",
            )

    def _lock_confirmation_key(self, *, user_id: uuid.UUID, client_request_id: str) -> None:
        lock_key = f"{user_id}:{client_request_id}"
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )

    def _calculate_preview(
        self,
        *,
        account: PaperAccount,
        order_id: uuid.UUID,
        draft: OrderDraft,
        normalize_quote_name: bool,
        quote: RealtimeQuote,
        now: datetime,
    ) -> OrderPreview:
        if quote.ts_code != draft.ts_code:
            raise PaperTradingError("security_identity_mismatch", "证券代码或名称与实时行情不一致")
        if quote.name != draft.name:
            if not normalize_quote_name:
                raise PaperTradingError(
                    "security_identity_mismatch", "证券代码或名称与实时行情不一致"
                )
            draft = draft.model_copy(update={"name": quote.name})
        if quote.suspended:
            raise PaperTradingError("suspended_security", "证券当前停牌")
        local_date = now.astimezone(SHANGHAI).date()
        rules = self.rulebook.resolve(
            ts_code=quote.ts_code,
            board=_board(quote.ts_code),
            risk_warning=_risk_warning(quote.name),
            side=draft.side.value,
            on=local_date,
        )
        assert_fresh_quote(quote, now, rules.quote_freshness_seconds)
        self._validate_book(quote=quote, rules=rules)
        sellable = self._sellable_quantity(account=account, ts_code=draft.ts_code, on=local_date)
        self.rulebook.validate_quantity(
            rules,
            draft.quantity,
            current_holding=sellable if draft.side is OrderSide.SELL else 0,
        )
        self._validate_limit_price(draft=draft, rules=rules, quote=quote)
        gross = self._estimated_gross(draft=draft, quote=quote)
        fees = self.fee_schedule.calculate(
            side=draft.side.value,
            gross=gross,
            commission_rate=cast(Decimal, account.commission_rate),
            minimum_commission=cast(Decimal, account.minimum_commission),
        )
        cash_required = (
            _money(gross + fees.total) if draft.side is OrderSide.BUY else Decimal("0.00")
        )
        available_cash = _money(cast(Decimal, account.available_cash))
        if draft.side is OrderSide.BUY and cash_required > available_cash:
            raise PaperTradingError("insufficient_cash", "模拟账户可用资金不足")
        return OrderPreview(
            order_id=order_id,
            draft=draft,
            quote=quote,
            estimated_gross=gross,
            estimated_fees=fees,
            estimated_cash_required=cash_required,
            available_cash=available_cash,
            sellable_quantity=sellable,
            market_phase=self.clock.phase(now),
            rules_version=f"{rules.version};fees={self.fee_schedule.version}",
        )

    def _quote(self, ts_code: str) -> RealtimeQuote:
        try:
            quote = self.quote_provider.get_sync(ts_code)
        except AttributeError as exc:
            raise PaperTradingError(
                "quote_unavailable", "实时行情提供器不支持同步交易路径"
            ) from exc
        if not isinstance(quote, RealtimeQuote):
            raise PaperTradingError("quote_unavailable", "实时行情数据无效")
        return quote

    def _owned_order(
        self, *, user_id: uuid.UUID, order_id: uuid.UUID, for_update: bool = False
    ) -> PaperOrder:
        statement = select(PaperOrder).where(
            PaperOrder.id == order_id, PaperOrder.user_id == user_id
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        order = self._session.scalar(statement)
        if order is None:
            raise PaperTradingError("paper_order_not_found", "模拟订单不存在")
        return order

    def _proposal_by_fingerprint(
        self, *, account: PaperAccount, fingerprint: str
    ) -> PaperOrder | None:
        return self._session.scalar(
            select(PaperOrder).where(
                PaperOrder.account_id == account.id,
                PaperOrder.account_generation == account.generation,
                PaperOrder.proposal_fingerprint == fingerprint,
            )
        )

    @staticmethod
    def _validate_idempotent_proposal(
        order: PaperOrder,
        *,
        user_id: uuid.UUID,
        session_id: str,
        message_id: str,
        proposal: dict[str, object],
    ) -> None:
        if (
            order.user_id != user_id
            or order.source_session_id != session_id
            or order.source_message_id != message_id
            or order.original_proposal != proposal
            or order.status is not OrderStatus.AWAITING_CONFIRMATION
        ):
            raise PaperTradingError(
                "proposal_idempotency_conflict", "订单提案幂等键与现有数据不一致"
            )

    def _sellable_quantity(self, *, account: PaperAccount, ts_code: str, on: date) -> int:
        available = self._session.scalar(
            select(
                func.coalesce(
                    func.sum(PaperHoldingLot.remaining_quantity - PaperHoldingLot.frozen_quantity),
                    0,
                )
            ).where(
                PaperHoldingLot.account_id == account.id,
                PaperHoldingLot.generation == account.generation,
                PaperHoldingLot.ts_code == ts_code,
                PaperHoldingLot.available_on <= on,
            )
        )
        return int(available or 0)

    def _current_time(self) -> datetime:
        now = self._now()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise PaperTradingError("invalid_order_time", "交易时钟必须返回带时区时间")
        return now

    def _expires_at(self, now: datetime) -> datetime:
        local = now.astimezone(SHANGHAI)
        expiry_date = local.date()
        expiry = datetime.combine(expiry_date, time(15), tzinfo=SHANGHAI)
        if local >= expiry or not self.clock.calendar.is_open_date(expiry_date):
            try:
                expiry_date = self.clock.calendar.next_open_date(expiry_date)
            except LookupError as exc:
                raise PaperTradingError("trading_calendar_unavailable", "缺少后续交易日") from exc
            expiry = datetime.combine(expiry_date, time(15), tzinfo=SHANGHAI)
        return expiry

    def _validate_book(self, *, quote: RealtimeQuote, rules: RuleSet) -> None:
        executable_bids = tuple(level for level in quote.bids if level.quantity > 0)
        executable_asks = tuple(level for level in quote.asks if level.quantity > 0)
        if not _strictly_sorted(executable_bids, descending=True):
            raise PaperTradingError("quote_unavailable", "买盘五档顺序无效")
        if not _strictly_sorted(executable_asks, descending=False):
            raise PaperTradingError("quote_unavailable", "卖盘五档顺序无效")
        if (
            executable_bids
            and executable_asks
            and executable_bids[0].price >= executable_asks[0].price
        ):
            raise PaperTradingError("quote_unavailable", "实时盘口价格交叉")
        lower, upper = self.rulebook.price_bounds(rules, quote.previous_close)
        for level in (*executable_bids, *executable_asks):
            units = level.price / rules.price_tick
            if units != units.to_integral_value() or level.price < lower or level.price > upper:
                raise PaperTradingError("quote_unavailable", "实时盘口价格不可执行")

    def _validate_limit_price(
        self, *, draft: OrderDraft, rules: RuleSet, quote: RealtimeQuote
    ) -> None:
        if draft.order_type is OrderType.MARKET:
            return
        price = draft.limit_price
        if price is None:  # guarded by OrderDraft; retained for type narrowing
            raise PaperTradingError("invalid_order", "限价单缺少价格")
        units = price / rules.price_tick
        if units != units.to_integral_value():
            raise PaperTradingError("invalid_price_tick", "限价不符合最小价格变动单位")
        lower, upper = self.rulebook.price_bounds(rules, quote.previous_close)
        if price < lower or price > upper:
            raise PaperTradingError("price_out_of_bounds", "限价超出当日涨跌幅范围")

    @staticmethod
    def _estimated_gross(*, draft: OrderDraft, quote: RealtimeQuote) -> Decimal:
        if draft.order_type is OrderType.LIMIT:
            assert draft.limit_price is not None
            return _money(draft.limit_price * draft.quantity)
        levels = quote.asks if draft.side is OrderSide.BUY else quote.bids
        remaining = draft.quantity
        gross = Decimal("0")
        for level in levels:
            if level.quantity == 0:
                continue
            consumed = min(remaining, level.quantity)
            gross += level.price * consumed
            remaining -= consumed
            if remaining == 0:
                return _money(gross)
        raise PaperTradingError("insufficient_market_depth", "当前五档数量不足以估算市价单")


def _draft(**values: object) -> OrderDraft:
    try:
        draft = OrderDraft.model_validate(values)
    except ValidationError as exc:
        raise PaperTradingError("invalid_order", "订单参数无效") from exc
    return _canonical_draft(draft)


def _canonical_draft(draft: OrderDraft) -> OrderDraft:
    canonical_code = draft.ts_code.upper()
    if _TS_CODE.fullmatch(canonical_code) is None:
        raise PaperTradingError("invalid_order", "证券代码无效")
    if len(draft.name) > 64:
        raise PaperTradingError("invalid_order", "证券名称过长")
    return draft.model_copy(update={"ts_code": canonical_code})


def _proposal_fingerprint(
    *,
    user_id: uuid.UUID,
    session_id: str,
    message_id: str,
    proposal: dict[str, object],
) -> str:
    payload = {
        "user_id": str(user_id),
        "source_session_id": session_id,
        "source_message_id": message_id,
        "draft": proposal,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_diff(
    original: dict[str, object], confirmed: dict[str, object]
) -> dict[str, dict[str, object]]:
    return {
        key: {"from": original.get(key), "to": confirmed.get(key)}
        for key in sorted(original.keys() | confirmed.keys())
        if original.get(key) != confirmed.get(key)
    }


def _constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return cast(str | None, getattr(diag, "constraint_name", None))


def _require_uuid(value: object, *, field: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise PaperTradingError("invalid_order", f"{field} must be a UUID")
    return value


def _require_text(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PaperTradingError("invalid_order", f"{field} is invalid")
    return value.strip()


def _board(ts_code: str) -> str:
    code, exchange = ts_code.split(".", maxsplit=1)
    if exchange == "SH" and code.startswith(("688", "689")):
        return "star"
    if exchange == "SZ" and code.startswith(("300", "301")):
        return "chinext"
    if (exchange == "SH" and code.startswith(("600", "601", "603", "605"))) or (
        exchange == "SZ" and code.startswith(("000", "001", "002", "003"))
    ):
        return "main"
    raise PaperTradingError("unsupported_trading_regime", "首版不支持该证券板块")


def _risk_warning(name: str) -> bool:
    normalized = name.strip().upper()
    return normalized.startswith(("ST", "*ST", "SST", "S*ST"))


def _strictly_sorted(levels: tuple[QuoteLevel, ...], *, descending: bool) -> bool:
    prices = [level.price for level in levels]
    ordered = sorted(prices, reverse=descending)
    return prices == ordered and len(set(prices)) == len(prices)


def _money(value: Decimal) -> Decimal:
    try:
        if not value.is_finite() or value < 0:
            raise PaperTradingError("invalid_order", "订单金额无效")
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    except DecimalException as exc:
        raise PaperTradingError("invalid_order", "订单金额超出可表示范围") from exc
