from app.chatloop.manage_watchlist_tool import ManageWatchlistArgs, ManageWatchlistTool
from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_docs import TOOL_DOCS


def test_watchlist_tool_schema_and_policy_boundary() -> None:
    args = ManageWatchlistArgs(action="add", ts_code="600519.SH")
    assert args.monitoring_enabled is False
    assert ManageWatchlistTool.name == "manage_watchlist"
    assert "approval" not in ManageWatchlistTool.description
    assert "manage_watchlist" in CHAT_SYSTEM_PROMPT
    assert "manage_watchlist" in TOOL_DOCS

