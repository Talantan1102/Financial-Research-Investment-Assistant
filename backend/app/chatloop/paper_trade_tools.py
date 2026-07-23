"""User-scoped paper-trading tools; high-risk writes require Run approval."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from pydantic import BaseModel, TypeAdapter

from app.chatloop.approval_edits import thaw_approved_value
from app.chatloop.inprocess import InProcessTool
from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    GetPaperAccountArgs,
    GetPaperOrderArgs,
    ListPaperOrdersArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.chatloop.state import ChatLoopState
from app.runtime.models import ExecutionContext
from app.schemas.paper_trading import OrderDraft

_ANY = TypeAdapter(Any)


class PaperTradingBackend(Protocol):
    def get_account(self, *, user_id: uuid.UUID) -> Mapping[str, Any]: ...
    def list_orders(
        self, *, user_id: uuid.UUID, status: str | None, ts_code: str | None, limit: int
    ) -> list[Mapping[str, Any]]: ...
    def get_order(self, *, user_id: uuid.UUID, order_id: uuid.UUID) -> Mapping[str, Any]: ...
    def place(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def cancel(self, **kwargs: Any) -> Mapping[str, Any]: ...
    def reset(self, **kwargs: Any) -> Mapping[str, Any]: ...


class SqlPaperTradingBackend:
    """Short-lived synchronous transactions, executed by tools in a worker thread."""

    def __init__(self, session_factory: Any, *, dispatch_order: Any | None = None) -> None:
        self._session_factory = session_factory
        self._dispatch_order = dispatch_order

    @staticmethod
    def _service(session: Any) -> Any:
        from app.services.paper_trading.clock import TradingClock
        from app.services.paper_trading.order_service import PaperOrderService
        from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider
        from app.services.paper_trading.rulebook import RuleBook
        from app.tasks.paper_trading import _calendar

        return PaperOrderService(
            session,
            quote_provider=TushareRealtimeQuoteProvider(),
            clock=TradingClock(_calendar()),
            rulebook=RuleBook.from_builtin_fixture(),
            now=lambda: datetime.now(UTC),
        )

    def get_account(self, *, user_id: uuid.UUID) -> Mapping[str, Any]:
        from app.schemas.paper_trading import PaperAccountRead
        from app.services.paper_trading.account_service import PaperAccountService

        with self._session_factory() as session:
            account = PaperAccountService(session).get_or_create(user_id=user_id)
            session.commit()
            session.refresh(account)
            return PaperAccountRead.model_validate(account).model_dump(mode="json")

    def list_orders(
        self, *, user_id: uuid.UUID, status: str | None, ts_code: str | None, limit: int
    ) -> list[Mapping[str, Any]]:
        from sqlalchemy import select

        from app.models.paper_order import OrderStatus, PaperOrder
        from app.schemas.paper_trading import PaperOrderRead

        with self._session_factory() as session:
            query = select(PaperOrder).where(PaperOrder.user_id == user_id)
            if status is not None:
                query = query.where(PaperOrder.status == OrderStatus(status))
            if ts_code is not None:
                query = query.where(PaperOrder.ts_code == ts_code)
            rows = session.scalars(query.order_by(PaperOrder.created_at.desc()).limit(limit)).all()
            return [PaperOrderRead.model_validate(row).model_dump(mode="json") for row in rows]

    def get_order(self, *, user_id: uuid.UUID, order_id: uuid.UUID) -> Mapping[str, Any]:
        from sqlalchemy import select

        from app.models.paper_order import PaperOrder
        from app.schemas.paper_trading import PaperOrderRead
        from app.services.paper_trading.errors import PaperTradingError

        with self._session_factory() as session:
            row = session.scalar(
                select(PaperOrder).where(PaperOrder.id == order_id, PaperOrder.user_id == user_id)
            )
            if row is None:
                raise PaperTradingError("paper_order_not_found", "paper order not found")
            return PaperOrderRead.model_validate(row).model_dump(mode="json")

    def place(self, **kwargs: Any) -> Mapping[str, Any]:
        from app.schemas.paper_trading import PaperOrderRead

        confirmed = cast(PlacePaperOrderArgs, kwargs.pop("confirmed"))
        with self._session_factory() as session:
            order = self._service(session).execute_approved_order(
                confirmed=OrderDraft.model_validate(confirmed.model_dump()),
                **kwargs,
            )
            session.commit()
            session.refresh(order)
            payload = PaperOrderRead.model_validate(order).model_dump(mode="json")
            order_id = str(order.id)
        _dispatch_committed_order(order_id, self._dispatch_order)
        return payload

    def cancel(self, **kwargs: Any) -> Mapping[str, Any]:
        from app.schemas.paper_trading import PaperOrderRead

        with self._session_factory() as session:
            order = self._service(session).cancel_approved(**kwargs)
            session.commit()
            session.refresh(order)
            return PaperOrderRead.model_validate(order).model_dump(mode="json")

    def reset(self, **kwargs: Any) -> Mapping[str, Any]:
        from app.schemas.paper_trading import PaperAccountRead

        with self._session_factory() as session:
            account = self._service(session).reset_approved(**kwargs)
            session.commit()
            session.refresh(account)
            return PaperAccountRead.model_validate(account).model_dump(mode="json")


def _json_safe(value: Any) -> Any:
    return _ANY.dump_python(value, mode="json")


def _dispatch_committed_order(order_id: str, dispatch: Any | None = None) -> None:
    """Best-effort only: the transaction has already committed at this boundary."""
    try:
        if dispatch is None:
            from app.tasks.paper_trading import dispatch_match_order

            dispatch = dispatch_match_order
        dispatch(order_id)
    except Exception:
        return


def diff_arguments(
    original: Mapping[str, Any], effective: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    return {
        key: {"before": _json_safe(original.get(key)), "after": _json_safe(effective.get(key))}
        for key in sorted(set(original) | set(effective))
        if _json_safe(original.get(key)) != _json_safe(effective.get(key))
    }


def paper_client_request_id(run_id: str, tool_call_id: str) -> str:
    if not 1 <= len(tool_call_id) <= 255:
        raise ValueError("tool_call_id must contain 1 to 255 characters")
    digest = hashlib.sha256(
        f"{run_id}\x00{tool_call_id}".encode()
    ).hexdigest()
    return f"paper:{digest}"


def _identity(state: ChatLoopState, context: ExecutionContext) -> tuple[uuid.UUID, uuid.UUID]:
    if context.user_id != state.user_id or context.request_id != state.request_id:
        raise RuntimeError("execution identity does not match chat state")
    try:
        return uuid.UUID(state.user_id), uuid.UUID(state.request_id)
    except ValueError as exc:
        raise RuntimeError("paper trading requires UUID run and user identities") from exc


class _PaperTool(InProcessTool):
    def __init__(self, backend: PaperTradingBackend) -> None:
        self._backend = backend

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        del args, state
        raise RuntimeError("paper tools require execution context")


class GetPaperAccountTool(_PaperTool):
    name = "get_paper_account"
    description = "读取当前用户唯一的默认模拟账户；不会交易。"
    args_schema = GetPaperAccountArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        del args
        user_id, _ = _identity(state, context)
        return cast(
            dict[str, Any],
            _json_safe(await asyncio.to_thread(self._backend.get_account, user_id=user_id)),
        )


class ListPaperOrdersTool(_PaperTool):
    name = "list_paper_orders"
    description = "读取当前用户的模拟订单，可按状态或股票过滤；不会交易。"
    args_schema = ListPaperOrdersArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        parsed = cast(ListPaperOrdersArgs, args)
        user_id, _ = _identity(state, context)
        rows = await asyncio.to_thread(
            self._backend.list_orders,
            user_id=user_id,
            status=parsed.status,
            ts_code=parsed.ts_code,
            limit=parsed.limit,
        )
        return {"orders": _json_safe(rows)}


class GetPaperOrderTool(_PaperTool):
    name = "get_paper_order"
    description = "按订单 id 读取当前用户的模拟订单；不会交易。"
    args_schema = GetPaperOrderArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        parsed = cast(GetPaperOrderArgs, args)
        user_id, _ = _identity(state, context)
        return cast(
            dict[str, Any],
            _json_safe(
                await asyncio.to_thread(
                    self._backend.get_order, user_id=user_id, order_id=parsed.order_id
                )
            ),
        )


def _approved(
    context: ExecutionContext, schema: type[BaseModel]
) -> tuple[Mapping[str, Any], Mapping[str, Any], BaseModel]:
    approved = context.approved_input
    if approved is None:
        raise RuntimeError("approved input is required for paper-trading writes")
    original = cast(dict[str, Any], thaw_approved_value(approved.original))
    effective = cast(dict[str, Any], thaw_approved_value(approved.effective))
    return original, effective, schema.model_validate(effective)


class PlacePaperOrderTool(_PaperTool):
    name = "place_paper_order"
    description = "按用户明确给出的股票、方向和数量提交模拟买卖；执行前必须获得用户批准。"
    args_schema = PlacePaperOrderArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        del args
        user_id, run_id = _identity(state, context)
        original, effective, parsed = _approved(context, PlacePaperOrderArgs)
        order = await asyncio.to_thread(
            self._backend.place,
            user_id=user_id,
            client_request_id=paper_client_request_id(
                state.request_id, context.task_id
            ),
            confirmed=parsed,
            original_proposal=original,
            user_edits=diff_arguments(original, effective),
            source_run_id=run_id,
            source_tool_call_id=context.task_id,
        )
        return cast(dict[str, Any], _json_safe(order))


class CancelPaperOrderTool(_PaperTool):
    name = "cancel_paper_order"
    description = "撤销当前用户指定的未完成模拟订单；执行前必须获得用户批准。"
    args_schema = CancelPaperOrderArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        del args
        user_id, run_id = _identity(state, context)
        original, effective, approved_model = _approved(context, CancelPaperOrderArgs)
        parsed = cast(CancelPaperOrderArgs, approved_model)
        result = await asyncio.to_thread(
            self._backend.cancel,
            user_id=user_id,
            order_id=parsed.order_id,
            client_request_id=paper_client_request_id(
                state.request_id, context.task_id
            ),
            original_proposal=original,
            user_edits=diff_arguments(original, effective),
            source_run_id=run_id,
            source_tool_call_id=context.task_id,
        )
        return cast(dict[str, Any], _json_safe(result))


class ResetPaperAccountTool(_PaperTool):
    name = "reset_paper_account"
    description = "重置当前用户模拟账户并创建下一代账户；执行前必须获得用户批准。"
    args_schema = ResetPaperAccountArgs

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        del args
        user_id, run_id = _identity(state, context)
        original, effective, approved_model = _approved(context, ResetPaperAccountArgs)
        parsed = cast(ResetPaperAccountArgs, approved_model)
        result = await asyncio.to_thread(
            self._backend.reset,
            user_id=user_id,
            initial_cash=parsed.initial_cash,
            client_request_id=paper_client_request_id(
                state.request_id, context.task_id
            ),
            original_proposal=original,
            user_edits=diff_arguments(original, effective),
            source_run_id=run_id,
            source_tool_call_id=context.task_id,
        )
        return cast(dict[str, Any], _json_safe(result))


PAPER_TOOL_TYPES = (
    GetPaperAccountTool,
    ListPaperOrdersTool,
    GetPaperOrderTool,
    PlacePaperOrderTool,
    CancelPaperOrderTool,
    ResetPaperAccountTool,
)

__all__ = [
    "CancelPaperOrderTool",
    "GetPaperAccountTool",
    "GetPaperOrderTool",
    "ListPaperOrdersTool",
    "PAPER_TOOL_TYPES",
    "PaperTradingBackend",
    "PlacePaperOrderTool",
    "ResetPaperAccountTool",
    "SqlPaperTradingBackend",
    "diff_arguments",
    "paper_client_request_id",
]
