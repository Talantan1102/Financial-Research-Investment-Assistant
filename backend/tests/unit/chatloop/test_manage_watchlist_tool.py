from __future__ import annotations

from uuid import uuid4

import pytest
from app.chatloop.manage_watchlist_tool import ManageWatchlistArgs, ManageWatchlistTool
from app.chatloop.state import ChatLoopState
from app.runtime.models import ExecutionContext


class _Backend:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None

    def manage(self, **kwargs: object) -> dict[str, object]:
        self.call = kwargs
        return {"removed": False, "monitoring_enabled": False}


@pytest.mark.asyncio
async def test_watchlist_executes_directly_with_state_identity_and_audit_source() -> None:
    backend = _Backend()
    tool = ManageWatchlistTool(backend)
    user_id = uuid4()
    state = ChatLoopState(
        user_id=str(user_id), session_id="session-9", request_id=str(uuid4()), messages=[]
    )
    context = ExecutionContext(
        request_id=state.request_id, turn_id="turn", task_id="watch-call", user_id=str(user_id)
    )
    args = ManageWatchlistArgs(action="add", ts_code="600519.SH", name="贵州茅台")

    result = await tool.run_with_context(args, state, context)

    assert result == {"removed": False, "monitoring_enabled": False}
    assert backend.call == {
        "user_id": user_id,
        "action": "add",
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "note": None,
        "monitoring_enabled": False,
        "changes": {},
        "source_session_id": "session-9",
        "source_tool_call_id": "watch-call",
    }
