from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import eval.chatloop.business_runner as business_runner_module
import pytest
from app.chatloop.state import ChatLoopState
from app.services.paper_trading.errors import PaperTradingError
from app.services.paper_trading.quote_provider import TushareRealtimeQuoteProvider
from eval.chatloop.business_runner import (
    _approval_pause_callback,
    _format_exception,
    _render_environment_messages,
    extract_business_tool_ledger,
)
from eval.chatloop.faults import FaultPlan


def test_format_exception_preserves_nested_task_group_causes() -> None:
    error = ExceptionGroup(
        "worker task failed",
        [RuntimeError("missing model credential"), TimeoutError("tool timed out")],
    )

    rendered = _format_exception(error)

    assert "ExceptionGroup: worker task failed" in rendered
    assert "RuntimeError: missing model credential" in rendered
    assert "TimeoutError: tool timed out" in rendered


def test_approval_pause_execution_guard_rejects_direct_case() -> None:
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="direct")),
        fault_plans=(
            FaultPlan(
                target="paper_settlement",
                mode="approval_pause",
                payload={"order_alias": "ord-b7-09", "fill_quantity": 200},
            ),
        ),
        environment=SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="approval_pause.*durable"):
        _approval_pause_callback(context)


@pytest.mark.parametrize(
    ("target", "payload"),
    (
        (
            "cancel_paper_order",
            {"order_alias": "ord-b7-09", "fill_quantity": 200},
        ),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": True}),
        ("paper_settlement", {"order_alias": "bad alias", "fill_quantity": 200}),
        (
            "paper_settlement",
            {"order_alias": "ord-b7-09", "fill_quantity": 200, "extra": True},
        ),
    ),
)
def test_approval_pause_execution_guard_revalidates_plan(
    target: str,
    payload: dict[str, object],
) -> None:
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="durable")),
        fault_plans=(SimpleNamespace(target=target, mode="approval_pause", payload=payload),),
        environment=SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="approval_pause"):
        _approval_pause_callback(context)


def test_approval_pause_execution_guard_rejects_multiple_plans() -> None:
    plan = FaultPlan(
        target="paper_settlement",
        mode="approval_pause",
        payload={"order_alias": "ord-b7-09", "fill_quantity": 200},
    )
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="durable")),
        fault_plans=(plan, plan),
        environment=SimpleNamespace(),
    )

    with pytest.raises(ValueError, match="at most one approval_pause"):
        _approval_pause_callback(context)


def test_approval_pause_callback_rejects_cross_user_order_alias() -> None:
    owner_user_id = UUID("00000000-0000-4000-8000-000000000001")
    requester_user_id = UUID("00000000-0000-4000-8000-000000000002")
    plan = FaultPlan(
        target="paper_settlement",
        mode="approval_pause",
        payload={"order_alias": "ord-b7-owner", "fill_quantity": 200},
    )
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="durable")),
        fault_plans=(plan,),
        actor=SimpleNamespace(user_id=requester_user_id),
        environment=SimpleNamespace(
            manifest=SimpleNamespace(order_alias_owners={"ord-b7-owner": str(owner_user_id)}),
            resolve_order_alias=lambda _alias: UUID("00000000-0000-4000-8000-00000000b716"),
        ),
    )

    with pytest.raises(PermissionError, match="order alias.*approval requester"):
        _approval_pause_callback(context)


@pytest.mark.asyncio
async def test_approval_delay_callback_ages_the_real_owned_pause_once() -> None:
    requester_user_id = UUID("00000000-0000-4000-8000-000000000001")
    run_id = uuid4()
    pause_id = uuid4()
    apply_delay = AsyncMock()
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="durable")),
        fault_plans=(
            FaultPlan(
                target="run_resume",
                mode="approval_delay",
                payload={"elapsed_seconds": 660},
            ),
        ),
        actor=SimpleNamespace(user_id=requester_user_id),
        environment=SimpleNamespace(apply_approval_delay=apply_delay),
    )
    callback = _approval_pause_callback(context)
    assert callback is not None
    pause = SimpleNamespace(
        id=pause_id,
        run_id=run_id,
        pause_type="approval",
        request_payload={"tool_calls": [{"name": "place_paper_order"}]},
    )

    await callback(str(run_id), pause)

    apply_delay.assert_awaited_once_with(
        run_id=run_id,
        pause_id=pause_id,
        elapsed_seconds=660,
        requester_user_id=requester_user_id,
    )
    with pytest.raises(RuntimeError, match="approval-delay.*more than once"):
        await callback(str(run_id), pause)


@pytest.mark.asyncio
async def test_suspended_quote_scope_uses_real_provider_mapping_and_restores_class() -> None:
    scope_factory = getattr(business_runner_module, "_suspended_quote_scope", None)
    assert scope_factory is not None, "eval-only suspended quote scope is missing"
    original = inspect.getattr_static(TushareRealtimeQuoteProvider, "_sdk_fetch")
    context = SimpleNamespace(
        case=SimpleNamespace(initial_state=SimpleNamespace(execution_mode="durable")),
        fault_plans=(
            FaultPlan(
                target="paper_quote_provider",
                mode="suspended_quote",
                payload={"ts_code": "000001.SZ"},
            ),
        ),
    )

    async with scope_factory(context):
        with pytest.raises(PaperTradingError) as caught:
            TushareRealtimeQuoteProvider().get_sync("000001.SZ")
        assert caught.value.code == "suspended_security"

    assert inspect.getattr_static(TushareRealtimeQuoteProvider, "_sdk_fetch") is original


@pytest.mark.parametrize(
    "message",
    (
        "撤销 {{order_id:}}",
        "撤销 {{order_id:ord-b7-09",
        "撤销 {{order_id:bad alias}}",
    ),
)
def test_order_placeholder_rejects_empty_unclosed_or_invalid_format(message: str) -> None:
    requester = UUID("00000000-0000-4000-8000-000000000001")

    with pytest.raises(ValueError, match="malformed order placeholder"):
        _render_environment_messages(
            [message],
            {},
            order_alias_owners={},
            requester_user_id=requester,
        )


def test_order_placeholder_rejects_unknown_alias() -> None:
    requester = UUID("00000000-0000-4000-8000-000000000001")

    with pytest.raises(KeyError, match="unknown order placeholder alias"):
        _render_environment_messages(
            ["撤销 {{order_id:ord-missing}}"],
            {},
            order_alias_owners={},
            requester_user_id=requester,
        )


def test_order_placeholder_rejects_non_uuid_seed_value() -> None:
    requester = UUID("00000000-0000-4000-8000-000000000001")

    with pytest.raises(ValueError, match="invalid UUID"):
        _render_environment_messages(
            ["撤销 {{order_id:ord-b7-09}}"],
            {"ord-b7-09": "not-a-uuid"},
            order_alias_owners={"ord-b7-09": str(requester)},
            requester_user_id=requester,
        )


def test_order_placeholder_rejects_missing_or_cross_user_owner() -> None:
    requester = UUID("00000000-0000-4000-8000-000000000001")
    other_user = UUID("00000000-0000-4000-8000-000000000002")
    order_id = "00000000-0000-4000-8000-00000000b709"

    with pytest.raises(ValueError, match="missing owner"):
        _render_environment_messages(
            ["撤销 {{order_id:ord-b7-09}}"],
            {"ord-b7-09": order_id},
            order_alias_owners={},
            requester_user_id=requester,
        )
    with pytest.raises(PermissionError, match="does not belong to requester"):
        _render_environment_messages(
            ["撤销 {{order_id:ord-b7-09}}"],
            {"ord-b7-09": order_id},
            order_alias_owners={"ord-b7-09": str(other_user)},
            requester_user_id=requester,
        )


def test_order_placeholder_renders_multiple_owned_templates() -> None:
    requester = UUID("00000000-0000-4000-8000-000000000001")
    first_id = "00000000-0000-4000-8000-00000000b707"
    second_id = "00000000-0000-4000-8000-00000000b709"

    rendered = _render_environment_messages(
        ["比较 {{order_id:ord-b7-07}} 和 {{order_id:ord-b7-09}}"],
        {"ord-b7-07": first_id, "ord-b7-09": second_id},
        order_alias_owners={"ord-b7-07": str(requester), "ord-b7-09": str(requester)},
        requester_user_id=requester,
    )

    assert rendered == [f"比较 {first_id} 和 {second_id}"]
    assert "{{order_id" not in rendered[0]


def test_extract_tool_ledger_keeps_arguments_results_errors_and_call_ids() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "ok-1",
                        "type": "function",
                        "function": {
                            "name": "get_market_quote",
                            "arguments": '{"ts_code":"000001.SZ"}',
                        },
                    },
                    {
                        "id": "bad-1",
                        "type": "function",
                        "function": {
                            "name": "place_paper_order",
                            "arguments": '{"quantity":100}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "ok-1",
                "content": '{"price":10.2}',
            },
            {
                "role": "tool",
                "tool_call_id": "bad-1",
                "content": "[ERROR] permission denied",
            },
        ],
    )

    ledger = extract_business_tool_ledger(state)

    assert ledger == (
        {
            "tool_name": "get_market_quote",
            "arguments": {"ts_code": "000001.SZ"},
            "result": {"price": 10.2},
            "error": None,
            "status": "completed",
            "error_code": None,
            "error_message": None,
            "idempotency_key": "ok-1",
        },
        {
            "tool_name": "place_paper_order",
            "arguments": {"quantity": 100},
            "result": None,
            "error": "permission denied",
            "status": "failed",
            "error_code": "tool_error",
            "error_message": "permission denied",
            "idempotency_key": "bad-1",
        },
    )


def test_extract_tool_ledger_marks_missing_response_instead_of_hiding_it() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "lost-1",
                        "type": "function",
                        "function": {"name": "get_news", "arguments": "{}"},
                    }
                ],
            }
        ],
    )

    ledger = extract_business_tool_ledger(state)

    assert ledger[0]["result"] is None
    assert ledger[0]["error"] == "missing tool response"
    assert "status" not in ledger[0]


def test_extract_tool_ledger_records_eval_fault_provenance_without_changing_tool_output() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "quote-1",
                        "type": "function",
                        "function": {
                            "name": "get_stock_quote",
                            "arguments": '{"ts_code":"300308.SZ"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "quote-1",
                "content": '{"price":135.2,"trade_date":"2026-07-24"}',
            },
        ],
    )

    ledger = extract_business_tool_ledger(
        state,
        fault_plans=(FaultPlan(target="get_stock_quote", mode="stale"),),
    )

    assert ledger[0]["result"] == {"price": 135.2, "trade_date": "2026-07-24"}
    assert ledger[0]["fault_injection"] == {
        "injected": True,
        "mode": "stale",
        "target": "get_stock_quote",
    }


def test_extract_tool_ledger_preserves_eval_fault_error_code() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "write-1",
                        "type": "function",
                        "function": {
                            "name": "manage_watchlist",
                            "arguments": '{"action":"add","ts_code":"002415.SZ"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "write-1",
                "content": (
                    "[ERROR] [response_lost_after_commit] "
                    "tool response was lost after the production write committed"
                ),
            },
        ],
    )

    ledger = extract_business_tool_ledger(
        state,
        fault_plans=(FaultPlan(target="manage_watchlist", mode="response_lost_after_commit"),),
    )

    assert ledger[0]["error_code"] == "response_lost_after_commit"
