import pytest
from app.agents.schemas import ChatState

pytestmark = pytest.mark.unit


def test_chatstate_accepts_forced_tool_fields() -> None:
    s = ChatState(
        user_id="u1",
        session_id="s1",
        user_message="/quote 600519.SH",
        request_id="r1",
        trace_request_id="r1",
        forced_tool_name="get_stock_quote",
        forced_tool_args={"ts_code": "600519.SH"},
    )
    assert s.forced_tool_name == "get_stock_quote"
    assert s.forced_tool_args == {"ts_code": "600519.SH"}


def test_chatstate_forced_fields_default_none() -> None:
    s = ChatState(
        user_id="u1",
        session_id="s1",
        user_message="hi",
        request_id="r1",
        trace_request_id="r1",
    )
    assert s.forced_tool_name is None
    assert s.forced_tool_args is None
