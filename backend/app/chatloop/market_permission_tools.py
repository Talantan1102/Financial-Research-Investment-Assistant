"""Read-only chat tools for a user's simulated market permissions."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.chatloop.inprocess import InProcessTool
from app.chatloop.outcomes import ActionRequiredOutcome
from app.chatloop.state import ChatLoopState
from app.models.investor_suitability import Market, MarketEntitlement
from app.runtime.models import ExecutionContext
from app.services.investor_suitability.instruments import classify_market
from app.services.paper_trading.account_service import PaperAccountService


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CheckOrderEligibilityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts_code: str = Field(min_length=1, max_length=16)
    side: Literal["buy", "sell"]


class ApplicationLinkArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    intent_summary: str | None = Field(default=None, max_length=500)


class MarketPermissionBackend(Protocol):
    def list_entitlements(self, *, user_id: uuid.UUID) -> list[Mapping[str, Any]]: ...

    def order_eligibility(
        self, *, user_id: uuid.UUID, ts_code: str, side: str
    ) -> Mapping[str, Any]: ...

    def application_link(
        self, *, user_id: uuid.UUID, market: str, intent_summary: str | None
    ) -> Mapping[str, Any]: ...


class SqlMarketPermissionBackend:
    """Per-call read-only database access for market-permission tools."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def list_entitlements(self, *, user_id: uuid.UUID) -> list[Mapping[str, Any]]:
        with self._session_factory() as session:
            account = PaperAccountService(session).get_active(user_id=user_id)
            rows = session.scalars(
                select(MarketEntitlement)
                .where(
                    MarketEntitlement.account_id == account.id,
                    MarketEntitlement.account_generation == account.generation,
                )
                .order_by(MarketEntitlement.market)
            ).all()
            return [_entitlement_payload(row) for row in rows]

    def order_eligibility(
        self, *, user_id: uuid.UUID, ts_code: str, side: str
    ) -> Mapping[str, Any]:
        market = classify_market(ts_code)
        with self._session_factory() as session:
            account = PaperAccountService(session).get_active(user_id=user_id)
            entitlement = session.scalar(
                select(MarketEntitlement).where(
                    MarketEntitlement.account_id == account.id,
                    MarketEntitlement.account_generation == account.generation,
                    MarketEntitlement.market == market,
                )
            )
            allowed = bool(
                entitlement is not None
                and (entitlement.can_buy if side == "buy" else entitlement.can_sell)
            )
            payload: dict[str, Any] = {
                "allowed": allowed,
                "required_permission": market.value,
                "market": market.value,
                "side": side,
            }
            if not allowed:
                payload["application_url"] = _application_url(market)
            return payload

    def application_link(
        self, *, user_id: uuid.UUID, market: str, intent_summary: str | None
    ) -> Mapping[str, Any]:
        parsed_market = Market(market)
        with self._session_factory() as session:
            PaperAccountService(session).get_active(user_id=user_id)
        return {
            "market": parsed_market.value,
            "application_url": _application_url(parsed_market),
            "intent_summary": intent_summary,
        }


def _entitlement_payload(row: MarketEntitlement) -> dict[str, Any]:
    return {
        "market": row.market.value,
        "status": row.status.value,
        "can_buy": row.can_buy,
        "can_sell": row.can_sell,
        "can_subscribe": row.can_subscribe,
        "rule_version": row.rule_version,
    }


def _application_url(market: Market) -> str:
    return f"/market-permissions/{market.value}/apply"


def _identity(state: ChatLoopState, context: ExecutionContext) -> uuid.UUID:
    if context.user_id != state.user_id or context.request_id != state.request_id:
        raise RuntimeError("execution identity does not match chat state")
    try:
        return uuid.UUID(context.user_id)
    except ValueError as exc:
        raise RuntimeError("market permission tools require UUID user identity") from exc


class _MarketPermissionTool(InProcessTool):
    def __init__(self, backend: MarketPermissionBackend) -> None:
        self._backend = backend

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        del args, state
        raise RuntimeError("market permission tools require execution context")


class GetMarketEntitlementsTool(_MarketPermissionTool):
    name = "get_market_entitlements"
    description = "查询当前模拟账户各市场的交易权限；不会申请或开通权限。"
    args_schema = EmptyArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        del args
        user_id = _identity(state, context)
        rows = await asyncio.to_thread(self._backend.list_entitlements, user_id=user_id)
        return {"entitlements": [dict(row) for row in rows]}


class CheckOrderEligibilityTool(_MarketPermissionTool):
    name = "check_order_eligibility"
    description = "在模拟下单前检查当前市场权限；不会创建订单或开通权限。"
    args_schema = CheckOrderEligibilityArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        parsed = cast(CheckOrderEligibilityArgs, args)
        user_id = _identity(state, context)
        return dict(
            await asyncio.to_thread(
                self._backend.order_eligibility,
                user_id=user_id,
                ts_code=parsed.ts_code,
                side=parsed.side,
            )
        )


class GetEntitlementApplicationLinkTool(_MarketPermissionTool):
    name = "get_entitlement_application_link"
    description = "返回市场权限申请页入口；不会代替用户提交申请或开通权限。"
    args_schema = ApplicationLinkArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        parsed = cast(ApplicationLinkArgs, args)
        user_id = _identity(state, context)
        result = dict(
            await asyncio.to_thread(
                self._backend.application_link,
                user_id=user_id,
                market=parsed.market.value,
                intent_summary=parsed.intent_summary,
            )
        )
        action_url = result.get("application_url")
        if not isinstance(action_url, str) or not action_url.startswith("/") or action_url.startswith("//"):
            raise RuntimeError("market permission application link must be internal")
        intent_summary = result.get("intent_summary")
        if not isinstance(intent_summary, str) or not intent_summary.strip():
            intent_summary = f"申请{parsed.market.value}市场交易权限"
            result["intent_summary"] = intent_summary
        state.required_action = ActionRequiredOutcome(
            action_type="market_permission_application",
            action_url=action_url,
            action_label=f"申请{parsed.market.value}市场权限",
            resume_hint="完成申请后，请在新的一轮对话中重新发起交易请求，系统会重新核验权限。",
            intent_summary=intent_summary,
        )
        return result


__all__ = [
    "ApplicationLinkArgs",
    "CheckOrderEligibilityArgs",
    "CheckOrderEligibilityTool",
    "EmptyArgs",
    "GetEntitlementApplicationLinkTool",
    "GetMarketEntitlementsTool",
    "MarketPermissionBackend",
    "SqlMarketPermissionBackend",
]
