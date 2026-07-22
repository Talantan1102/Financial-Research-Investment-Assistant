"""Approval card extraction/persistence contract for the chat worker."""

import json
from datetime import UTC, datetime, timedelta

from app.chatloop.paper_trade_tool import ApprovalPayload
from app.chatloop.state import ChatLoopState
from app.tasks.chat_runner import _approval_payloads


def _payload() -> dict[str, object]:
    return ApprovalPayload(
        approval_id="a1",
        approval_type="paper_order",
        resource_id="o1",
        proposal={"side": "buy", "quantity": 100},
        preview={"estimated_cash_required": "1000.00"},
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ).model_dump(mode="json")


def test_extracts_one_stable_approval_from_tool_messages() -> None:
    payload = _payload()
    state = ChatLoopState(
        user_id="00000000-0000-0000-0000-000000000001",
        session_id="s1",
        request_id="r1",
        messages=[
            {"role": "tool", "content": json.dumps({"approval": payload})},
            {"role": "tool", "content": json.dumps({"approval": payload})},
        ],
    )

    approvals = _approval_payloads(state)

    assert approvals == [payload]


def test_approval_payload_rejects_unknown_type() -> None:
    payload = _payload()
    payload["approval_type"] = "confirm"

    try:
        ApprovalPayload.model_validate(payload)
    except ValueError:
        return
    raise AssertionError("unknown approval type must be rejected")
