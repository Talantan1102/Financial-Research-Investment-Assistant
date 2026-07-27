from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from app.chatloop.market_permission_tools import (
    ApplicationLinkArgs,
    CheckOrderEligibilityArgs,
    CheckOrderEligibilityTool,
    EmptyArgs,
    GetEntitlementApplicationLinkTool,
    GetMarketEntitlementsTool,
)
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_runtime_policy import TOOL_RISK_METADATA
from app.runtime.models import ExecutionContext, RiskLevel


class _Backend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_entitlements(self, *, user_id: object) -> list[dict[str, object]]:
        self.calls.append(("list_entitlements", user_id))
        return [
            {
                "market": "main",
                "status": "enabled",
                "can_buy": True,
                "can_sell": True,
                "can_subscribe": True,
            }
        ]

    def order_eligibility(self, *, user_id: object, ts_code: str, side: str) -> dict[str, object]:
        self.calls.append(("order_eligibility", user_id))
        assert ts_code == "688981.SH"
        assert side == "buy"
        return {
            "allowed": False,
            "required_permission": "star",
            "application_url": "/market-permissions/star/apply",
        }

    def application_link(
        self, *, user_id: object, market: str, intent_summary: str | None
    ) -> dict[str, object]:
        self.calls.append(("application_link", user_id))
        return {
            "market": market,
            "application_url": f"/market-permissions/{market}/apply",
            "intent_summary": intent_summary,
        }


def _state_and_context() -> tuple[ChatLoopState, ExecutionContext]:
    user_id, request_id = uuid4(), uuid4()
    state = ChatLoopState(
        user_id=str(user_id), session_id="session-1", request_id=str(request_id), messages=[]
    )
    context = ExecutionContext(
        request_id=str(request_id), turn_id="turn-1", task_id="tool-1", user_id=str(user_id)
    )
    return state, context


@pytest.mark.asyncio
async def test_check_order_eligibility_returns_link_without_mutating_state() -> None:
    backend = _Backend()
    tool = CheckOrderEligibilityTool(backend)
    state, context = _state_and_context()

    result = await tool.run_with_context(
        CheckOrderEligibilityArgs(ts_code="688981.SH", side="buy"), state, context
    )

    assert result == {
        "allowed": False,
        "required_permission": "star",
        "application_url": "/market-permissions/star/apply",
    }
    assert backend.calls == [("order_eligibility", UUID(context.user_id))]


@pytest.mark.asyncio
async def test_permission_tools_use_context_user_and_reject_identity_mismatch() -> None:
    backend = _Backend()
    tool = GetMarketEntitlementsTool(backend)
    state, context = _state_and_context()

    result = await tool.run_with_context(EmptyArgs(), state, context)

    assert result["entitlements"][0]["market"] == "main"
    assert backend.calls == [("list_entitlements", UUID(context.user_id))]
    mismatched = context.model_copy(update={"user_id": str(uuid4())})
    with pytest.raises(RuntimeError, match="identity"):
        await tool.run_with_context(EmptyArgs(), state, mismatched)


@pytest.mark.asyncio
async def test_application_link_sets_terminal_action_required_without_external_write() -> None:
    backend = _Backend()
    tool = GetEntitlementApplicationLinkTool(backend)
    state, context = _state_and_context()

    result = await tool.run_with_context(
        ApplicationLinkArgs(market="star", intent_summary="买入中芯国际 100 股"), state, context
    )

    assert result == {
        "market": "star",
        "application_url": "/market-permissions/star/apply",
        "intent_summary": "买入中芯国际 100 股",
    }
    assert backend.calls == [("application_link", UUID(context.user_id))]
    assert state.required_action is not None
    assert state.required_action.code == "action_required"
    assert state.required_action.action_url == "/market-permissions/star/apply"
    assert state.required_action.intent_summary == "买入中芯国际 100 股"


@pytest.mark.parametrize(
    "name",
    ("get_market_entitlements", "check_order_eligibility", "get_entitlement_application_link"),
)
def test_market_permission_tools_are_low_risk_read_only_and_idempotent(name: str) -> None:
    metadata = TOOL_RISK_METADATA[name]
    assert metadata.risk is RiskLevel.LOW
    assert metadata.read_only is True
    assert metadata.idempotent is True
