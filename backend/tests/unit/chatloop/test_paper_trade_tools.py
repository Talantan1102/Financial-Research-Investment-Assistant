from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from uuid import uuid4

import pytest
from app.chatloop.approval_edits import ApprovedInput
from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.chatloop.paper_trade_tools import (
    PlacePaperOrderTool,
    SqlPaperTradingBackend,
    _dispatch_committed_order,
    paper_client_request_id,
)
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_hub import ToolHub
from app.chatloop.tool_runtime_policy import TOOL_RISK_METADATA, authorize_approved_paper_write
from app.runtime.models import ExecutionContext, RiskLevel
from app.schemas.paper_trading import PaperOrderRead
from app.services.llm_step import StepToolCall
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("name", "risk", "read_only"),
    [
        ("get_stock_quote", RiskLevel.LOW, True),
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
    if name == "get_stock_quote":
        assert metadata.idempotent is True


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
    assert backend.call["client_request_id"] == paper_client_request_id(
        str(run_id), "call-7"
    )
    assert backend.call["source_run_id"] == run_id
    assert backend.call["source_tool_call_id"] == "call-7"
    assert backend.call["original_proposal"] == original
    assert backend.call["confirmed"].quantity == 200
    assert backend.call["user_edits"] == {
        "limit_price": {"before": "1500", "after": "1499"},
        "quantity": {"before": 100, "after": 200},
    }


def test_long_tool_call_ids_use_distinct_bounded_business_keys() -> None:
    run_id = str(uuid4())
    first = "x" * 254 + "a"
    second = "x" * 254 + "b"
    assert len(paper_client_request_id(run_id, first)) <= 128
    assert paper_client_request_id(run_id, first) != paper_client_request_id(
        run_id, second
    )
    with pytest.raises(ValueError, match="255"):
        paper_client_request_id(run_id, "x" * 256)
    with pytest.raises(ValidationError):
        StepToolCall(
            id="x" * 256,
            name="place_paper_order",
            arguments="{}",
        )


def test_committed_order_dispatch_is_best_effort_and_replay_may_enqueue_again() -> None:
    calls: list[str] = []
    _dispatch_committed_order("order-1", calls.append)
    _dispatch_committed_order("order-1", calls.append)
    assert calls == ["order-1", "order-1"]

    def unavailable(_order_id: str) -> None:
        raise OSError("broker unavailable")

    _dispatch_committed_order("order-2", unavailable)


def test_sql_backend_dispatches_after_commit_and_returns_order_when_dispatch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order_id = uuid4()
    order = SimpleNamespace(id=order_id)
    sessions: list[SimpleNamespace] = []

    class Session:
        committed = False

        def __enter__(self) -> Session:
            sessions.append(self)  # type: ignore[arg-type]
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def commit(self) -> None:
            self.committed = True

        def refresh(self, _order: object) -> None:
            return None

    class Service:
        def execute_approved_order(self, **_kwargs: object) -> object:
            return order

    class Read:
        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"id": str(order_id), "status": "open"}

    monkeypatch.setattr(
        SqlPaperTradingBackend, "_service", staticmethod(lambda _session: Service())
    )
    monkeypatch.setattr(
        PaperOrderRead, "model_validate", classmethod(lambda _cls, _order: Read())
    )
    dispatches: list[str] = []

    def unavailable(dispatched_order_id: str) -> None:
        assert sessions[-1].committed is True
        dispatches.append(dispatched_order_id)
        raise OSError("broker unavailable")

    backend = SqlPaperTradingBackend(Session, dispatch_order=unavailable)
    confirmed = PlacePaperOrderArgs(
        side="buy",
        ts_code="600519.SH",
        name="贵州茅台",
        quantity=100,
        order_type="market",
    )

    first = backend.place(confirmed=confirmed)
    replay = backend.place(confirmed=confirmed)

    assert first == replay == {"id": str(order_id), "status": "open"}
    assert dispatches == [str(order_id), str(order_id)]


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


def _place_call(call_id: str, arguments: dict[str, object]) -> StepToolCall:
    import json

    return StepToolCall(
        id=call_id,
        name="place_paper_order",
        arguments=json.dumps(arguments),
    )


@pytest.mark.asyncio
async def test_real_tool_hub_dispatch_allows_only_matching_approved_call() -> None:
    backend = _Backend()
    hub = ToolHub(
        progressive=False,
        authorization_callback=authorize_approved_paper_write,
        visibility_resolver=lambda _state: frozenset({"place_paper_order"}),
    )
    hub.register_inprocess([PlacePaperOrderTool(backend)])
    user_id, run_id = uuid4(), uuid4()
    original = {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "order_type": "limit",
        "limit_price": "1500",
    }
    effective = {**original, "quantity": 200}
    state = ChatLoopState(
        user_id=str(user_id),
        session_id="session",
        request_id=str(run_id),
        messages=[],
        approved_inputs={"approved-call": ApprovedInput(original=original, effective=effective)},
    )

    [result] = await hub.dispatch([_place_call("approved-call", effective)], state)

    assert result.success is True
    assert backend.call is not None
    assert backend.call["confirmed"].quantity == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_id", [None, "other-call"])
async def test_real_tool_hub_dispatch_denies_missing_or_cross_call_approval(
    approved_id: str | None,
) -> None:
    backend = _Backend()
    hub = ToolHub(
        progressive=False,
        authorization_callback=authorize_approved_paper_write,
        visibility_resolver=lambda _state: frozenset({"place_paper_order"}),
    )
    hub.register_inprocess([PlacePaperOrderTool(backend)])
    user_id, run_id = uuid4(), uuid4()
    arguments = {
        "side": "buy",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "quantity": 100,
        "order_type": "market",
    }
    approvals = (
        {}
        if approved_id is None
        else {approved_id: ApprovedInput(original=arguments, effective=arguments)}
    )
    state = ChatLoopState(
        user_id=str(user_id),
        session_id="session",
        request_id=str(run_id),
        messages=[],
        approved_inputs=approvals,
    )

    [result] = await hub.dispatch([_place_call("attempt-call", arguments)], state)

    assert result.success is False
    assert backend.call is None
