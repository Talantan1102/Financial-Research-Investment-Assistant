from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.paper_account import PaperAccount, PaperHoldingLot
from app.models.paper_order import OrderSide, OrderStatus, OrderType, PaperOrder
from app.schemas.paper_trading import OrderDraft, OrderPreview
from app.services.paper_trading.account_service import PaperAccountService
from app.services.paper_trading.clock import TradingClock
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.fee_schedule import FeeSchedule
from app.services.paper_trading.quote_provider import RealtimeQuoteProvider
from app.services.paper_trading.rulebook import RuleBook
from app.services.paper_trading.types import QuoteLevel, RealtimeQuote, RuleSet

SHANGHAI = ZoneInfo("Asia/Shanghai")
_TS_CODE = re.compile(r"\d{6}\.(?:SH|SZ)")
_CENT = Decimal("0.01")


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

        # Shared prepare/edit contract: this is deliberately the first database
        # operation that can precede creation of an order proposal.
        account = self.account_service.get_active(user_id=user_id, for_update=True)
        order_id = uuid.uuid4()
        preview = self._calculate_preview(
            account=account,
            order_id=order_id,
            draft=draft,
            normalize_quote_name=False,
        )
        order = PaperOrder(
            id=order_id,
            account_id=account.id,
            account_generation=account.generation,
            user_id=user_id,
            client_request_id=None,
            source_session_id=session_id,
            source_message_id=message_id,
            ts_code=draft.ts_code,
            name=preview.quote.name,
            side=draft.side,
            order_type=draft.order_type,
            quantity=draft.quantity,
            limit_price=draft.limit_price,
            filled_quantity=0,
            avg_fill_price=None,
            status=OrderStatus.AWAITING_CONFIRMATION,
            original_proposal=draft.model_dump(mode="json"),
            confirmed_payload=None,
            user_edits=None,
            quote_snapshot=preview.quote.model_dump(mode="json"),
            rules_version=preview.rules_version,
            reject_code=None,
            reject_message=None,
            expires_at=self._expires_at(self._current_time()),
            confirmed_at=None,
            completed_at=None,
        )
        self._session.add(order)
        self._session.flush()
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
        return self._calculate_preview(
            account=account,
            order_id=order_id,
            draft=normalized_draft,
            normalize_quote_name=True,
        )

    def _calculate_preview(
        self,
        *,
        account: PaperAccount,
        order_id: uuid.UUID,
        draft: OrderDraft,
        normalize_quote_name: bool,
    ) -> OrderPreview:
        now = self._current_time()
        quote = self._quote(draft.ts_code)
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
        self._validate_book(quote)

        local_date = now.astimezone(SHANGHAI).date()
        rules = self.rulebook.resolve(
            ts_code=quote.ts_code,
            board=_board(quote.ts_code),
            risk_warning=_risk_warning(quote.name),
            side=draft.side.value,
            on=local_date,
        )
        self._assert_fresh(
            quote=quote,
            now=now,
            max_age_seconds=rules.quote_freshness_seconds,
        )
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

    def _owned_order(self, *, user_id: uuid.UUID, order_id: uuid.UUID) -> PaperOrder:
        order = self._session.scalar(
            select(PaperOrder).where(PaperOrder.id == order_id, PaperOrder.user_id == user_id)
        )
        if order is None:
            raise PaperTradingError("paper_order_not_found", "模拟订单不存在")
        return order

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

    @staticmethod
    def _assert_fresh(*, quote: RealtimeQuote, now: datetime, max_age_seconds: int) -> None:
        age_seconds = abs((now - quote.quoted_at).total_seconds())
        if age_seconds > max_age_seconds:
            raise PaperTradingError("stale_quote", "实时行情已过期")

    @staticmethod
    def _validate_book(quote: RealtimeQuote) -> None:
        if not _strictly_sorted(quote.bids, descending=True):
            raise PaperTradingError("quote_unavailable", "买盘五档顺序无效")
        if not _strictly_sorted(quote.asks, descending=False):
            raise PaperTradingError("quote_unavailable", "卖盘五档顺序无效")
        if quote.bids[0].price >= quote.asks[0].price:
            raise PaperTradingError("quote_unavailable", "实时盘口价格交叉")

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
