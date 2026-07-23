from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType
from uuid import uuid4

import pytest
from app.chatloop.approval_edits import ApprovedInput
from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.chatloop.paper_trade_tools import PlacePaperOrderTool
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_runtime_policy import TOOL_RISK_METADATA
from app.runtime.models import ExecutionContext, RiskLevel
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("name", "risk", "read_only"),
    [
        ("get_paper_account", RiskLevel.LOW, True),
        ("list_paper_orders", RiskLevel.LOW, True),
        ("get_paper_order", RiskLevel.LOW, True),
        ("place_paper_order", RiskLevel.HIGH, False),
        ("cancel_paper_order", RiskLevel.HIGH, False),
        ("reset_paper_account", RiskLevel.HIGH, False),
        ("manage_watchlist", RiskLevel.LOW, False),
    ],
)
def test_paper_tool_risk_is_static(name: str, risk: RiskLevel, read_only: bool) -> None:
    metadata = TOOL_RISK_METADATA[name]
    assert metadata.risk is risk
    assert metadata.read_only is read_only


@pytest.mark.parametrize(
    "payload",
    [
        {
            "side": "buy",
            "ts_code": "600519.SH",
            "name": "茅台",
            "quantity": True,
            "order_type": "market",
        },
        {
            "side": "buy",
            "ts_code": "600519.SH",
            "name": "茅台",
            "quantity": 100,
            "order_type": "market",
            "limit_price": "1",
        },
        {
            "side": "sell",
            "ts_code": "600519.SH",
            "name": "茅台",
            "quantity": 100,
            "order_type": "limit",
        },
    ],
)
def test_place_schema_is_closed_and_enforces_order_shape(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PlacePaperOrderArgs.model_validate(payload)


def test_high_risk_schemas_are_closed() -> None:
    with pytest.raises(ValidationError):
        CancelPaperOrderArgs.model_validate({"order_id": str(uuid4()), "user_id": str(uuid4())})
    with pytest.raises(ValidationError):
        ResetPaperAccountArgs.model_validate({"initial_cash": "1000000", "session_id": "bad"})


class _Backend:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    def place(self, **kwargs: object) -> dict[str, object]:
        self.call = kwargs
        return {"id": str(uuid4()), "status": "open", "reserved_cash": Decimal("123.45")}


@pytest.mark.asyncio
async def test_place_uses_only_effective_approved_args_and_state_identity() -> None:
    backend = _Backend()
    tool = PlacePaperOrderTool(backend)
    user_id, run_id = uuid4(), uuid4()
    original = {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": "1500",
    }
    effective = {**original, "quantity": 200, "limit_price": "1499"}
    state = ChatLoopState(
        user_id=str(user_id), session_id="session-from-state", request_id=str(run_id), messages=[]
    )
    context = ExecutionContext(
        request_id=str(run_id),
        turn_id="turn-1",
        task_id="call-7",
        user_id=str(user_id),
        approved_input=ApprovedInput(
            original=MappingProxyType(original), effective=MappingProxyType(effective)
        ),
    )

    result = await tool.run_with_context(
        PlacePaperOrderArgs.model_validate(effective), state, context
    )

    assert result["reserved_cash"] == "123.45"
    assert backend.call is not None
    assert backend.call["user_id"] == user_id
    assert backend.call["client_request_id"] == f"{run_id}:call-7"
    assert backend.call["source_run_id"] == run_id
    assert backend.call["source_tool_call_id"] == "call-7"
    assert backend.call["original_proposal"] == original
    assert backend.call["confirmed"].quantity == 200
    assert backend.call["user_edits"] == {
        "limit_price": {"before": "1500", "after": "1499"},
        "quantity": {"before": 100, "after": 200},
    }


@pytest.mark.asyncio
async def test_place_fails_closed_without_approved_input() -> None:
    tool = PlacePaperOrderTool(_Backend())
    user_id, run_id = uuid4(), uuid4()
    args = PlacePaperOrderArgs(
        side="buy", ts_code="600519.SH", name="贵州茅台", quantity=100, order_type="market"
    )
    state = ChatLoopState(
        user_id=str(user_id), session_id="session", request_id=str(run_id), messages=[]
    )
    context = ExecutionContext(
        request_id=str(run_id), turn_id="turn", task_id="call", user_id=str(user_id)
    )
    with pytest.raises(RuntimeError, match="approved input"):
        await tool.run_with_context(args, state, context)
