from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from app.chatloop.paper_trade_tool import PaperTradeArgs, PaperTradeTool
from app.chatloop.state import ChatLoopState
from pydantic import ValidationError

USER_ID = "11111111-1111-1111-1111-111111111111"


class FakeDependencies:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.cash = Decimal("1000000.00")

    async def account_balance(self, user_id: str) -> Decimal:
        assert user_id == USER_ID
        return self.cash

    async def dispatch(self, args: PaperTradeArgs, **scope: object) -> dict[str, object]:
        self.calls.append({"args": args, **scope})
        if args.action == "get_account":
            return {"account": {"available_cash": str(self.cash)}}
        if args.action == "prepare_order":
            return {
                "approval": {
                    "approval_id": "ap-1",
                    "approval_type": "paper_order",
                    "resource_id": "order-1",
                    "proposal": args.model_dump(mode="json"),
                    "preview": {"quantity": args.quantity},
                    "expires_at": "2030-01-01T00:00:00Z",
                }
            }
        return {"ok": True}


def _state() -> ChatLoopState:
    return ChatLoopState(user_id=USER_ID, session_id="session-1", request_id="req-1", messages=[])


def test_schema_exposes_prepare_but_not_confirm() -> None:
    schema = PaperTradeTool(FakeDependencies()).schema_for_llm()["function"]["parameters"]
    actions = schema["properties"]["action"]["enum"]
    assert actions == [
        "get_account",
        "list_orders",
        "get_order",
        "prepare_order",
        "prepare_cancel",
        "prepare_reset",
    ]
    assert "confirm" not in actions
    assert "user_id" not in schema["properties"]


def test_args_reject_confirm_and_user_id() -> None:
    with pytest.raises(ValidationError):
        PaperTradeArgs(action="confirm")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PaperTradeArgs(action="get_account", user_id=USER_ID)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_prepare_order_returns_approval_without_changing_cash() -> None:
    dependencies = FakeDependencies()
    before = await dependencies.account_balance(USER_ID)
    result = await PaperTradeTool(dependencies).run_with_state(
        PaperTradeArgs(
            action="prepare_order",
            side="buy",
            ts_code="600519.SH",
            name="贵州茅台",
            quantity=100,
            order_type="limit",
            limit_price=Decimal("1500"),
        ),
        _state(),
    )
    assert result["approval"]["approval_type"] == "paper_order"
    assert await dependencies.account_balance(USER_ID) == before
    assert dependencies.calls[-1]["user_id"] == UUID(USER_ID)
    assert dependencies.calls[-1]["session_id"] == "session-1"
    assert dependencies.calls[-1]["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_missing_order_fields_are_explicit() -> None:
    result = await PaperTradeTool(FakeDependencies()).run_with_state(
        PaperTradeArgs(action="prepare_order"), _state()
    )
    assert result == {
        "error": "missing_order_field",
        "missing_fields": ["side", "ts_code", "quantity"],
    }


@pytest.mark.asyncio
async def test_amount_semantics_are_converted_to_lots_in_preview() -> None:
    dependencies = FakeDependencies()
    result = await PaperTradeTool(dependencies).run_with_state(
        PaperTradeArgs(
            action="prepare_order",
            side="buy",
            ts_code="600519.SH",
            name="贵州茅台",
            amount=Decimal("10000"),
            order_type="limit",
            limit_price=Decimal("1500"),
        ),
        _state(),
    )
    assert result["approval"]["proposal"]["quantity"] == 6
    assert result["approval"]["preview"]["quantity"] == 6


@pytest.mark.asyncio
async def test_amount_without_price_is_missing_quantity_and_price() -> None:
    dependencies = FakeDependencies()
    result = await PaperTradeTool(dependencies).run_with_state(
        PaperTradeArgs(
            action="prepare_order",
            side="buy",
            ts_code="600519.SH",
            name="贵州茅台",
            amount=Decimal("10000"),
            order_type="market",
        ),
        _state(),
    )
    assert result == {
        "error": "missing_order_field",
        "missing_fields": ["quantity", "price"],
    }
    assert dependencies.calls == []


@pytest.mark.asyncio
async def test_query_actions_delegate_with_state_scope() -> None:
    dependencies = FakeDependencies()
    result = await PaperTradeTool(dependencies).run_with_state(
        PaperTradeArgs(action="list_orders"), _state()
    )
    assert result == {"ok": True}
    assert dependencies.calls[-1]["user_id"] == UUID(USER_ID)
