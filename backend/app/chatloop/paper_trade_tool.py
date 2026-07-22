"""Agent-facing paper-trading query and prepare tool.

The tool deliberately has no confirmation action.  Confirmation is an HTTP/UI
operation so that an approval card can be edited and explicitly accepted by a
human.  Ownership is always taken from :class:`ChatLoopState`.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.models.paper_order import OrderSide, OrderType

PaperAction = Literal[
    "get_account",
    "list_orders",
    "get_order",
    "prepare_order",
    "prepare_cancel",
    "prepare_reset",
]


class PaperTradeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: PaperAction
    order_id: UUID | None = None
    side: OrderSide | None = None
    ts_code: str | None = None
    name: str | None = None
    quantity: int | None = Field(default=None, strict=True, gt=0)
    amount: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    order_type: OrderType | None = None
    limit_price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    initial_cash: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)


class ApprovalPayload(BaseModel):
    """Stable payload shared by the worker approval event and chat card."""

    approval_id: str
    approval_type: Literal["paper_order", "paper_cancel", "paper_reset"]
    resource_id: str
    proposal: dict[str, Any]
    preview: dict[str, Any]
    expires_at: datetime


class PaperTradeDependencies(Protocol):
    async def dispatch(
        self,
        args: PaperTradeArgs,
        *,
        user_id: UUID,
        session_id: str,
        request_id: str,
    ) -> dict[str, Any]: ...


def _missing(action: PaperAction, args: PaperTradeArgs) -> list[str]:
    if action == "prepare_order":
        fields: list[str] = []
        if args.side is None:
            fields.append("side")
        if args.ts_code is None or not args.ts_code.strip():
            fields.append("ts_code")
        if args.name is None or not args.name.strip():
            fields.append("name")
        if args.quantity is None:
            if args.amount is None:
                fields.append("quantity")
            elif args.limit_price is None:
                fields.extend(("quantity", "price"))
        return fields
    if action in {"get_order", "prepare_cancel"} and args.order_id is None:
        return ["order_id"]
    if action == "prepare_reset" and args.initial_cash is None:
        return ["initial_cash"]
    return []


def _as_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("ChatLoopState.user_id must be a UUID") from exc


class PaperTradeTool(InProcessTool):
    name = "paper_trade"
    description = (
        "查询模拟账户或订单，或在用户明确要求买卖、撤单、重置时准备一张待确认卡；本工具不执行确认。"
    )
    args_schema = PaperTradeArgs

    def __init__(self, dependencies: PaperTradeDependencies | Any) -> None:
        self._dependencies = dependencies

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        parsed = PaperTradeArgs.model_validate(args.model_dump())
        missing = _missing(parsed.action, parsed)
        if missing:
            return {"error": "missing_order_field", "missing_fields": missing}

        if parsed.action == "prepare_order" and parsed.amount is not None:
            parsed = self._quantity_from_amount(parsed)
            if parsed.quantity is None:
                return {"error": "missing_order_field", "missing_fields": ["quantity"]}

        user_id = _as_uuid(state.user_id)
        scope = {
            "user_id": user_id,
            "session_id": state.session_id,
            "request_id": state.request_id,
        }
        dispatch = getattr(self._dependencies, "dispatch", None)
        if dispatch is not None:
            result = dispatch(parsed, **scope)
        else:
            method_name = parsed.action
            method: Callable[..., Any] = getattr(self._dependencies, method_name)
            result = method(parsed, **scope)
        if inspect.isawaitable(result):
            result = await result
        if parsed.action.startswith("prepare_") and isinstance(result, dict):
            # Dependencies may return an already-normalized approval. Validate
            # it here so malformed cards never reach the model/UI boundary.
            approval = result.get("approval")
            if approval is not None:
                normalized = ApprovalPayload.model_validate(approval)
                return {**result, "approval": normalized.model_dump(mode="json")}
        return result

    @staticmethod
    def _quantity_from_amount(args: PaperTradeArgs) -> PaperTradeArgs:
        # Amount semantics need a deterministic price.  A limit order has an
        # explicit price; market orders must provide quantity and are rejected
        # as missing rather than inventing a price from stale data.
        if args.limit_price is None or args.amount is None:
            return args
        lots = (args.amount / args.limit_price).to_integral_value(rounding=ROUND_DOWN)
        quantity = int(lots)
        if quantity <= 0:
            return args
        return args.model_copy(update={"quantity": quantity})


__all__ = ["ApprovalPayload", "PaperTradeArgs", "PaperTradeDependencies", "PaperTradeTool"]
