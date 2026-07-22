from eval.chatloop.scorers import WatchlistOutcomeScorer


def test_watchlist_direct_write_and_monitoring_terminal_state() -> None:
    expected = {"database_assertions": {"watchlist_count": 1, "monitoring_enabled": False, "audit_action": "add"}}
    trace = [{"tool_name": "manage_watchlist", "args": {"action": "add"}}]
    scorer = WatchlistOutcomeScorer()
    assert scorer.score(expected, trace, {"watchlist_count": 1, "monitoring_enabled": False, "audit_action": "add"}).passed
    assert not scorer.score(expected, [{"tool_name": "paper_trade", "args": {}}], {"watchlist_count": 1, "monitoring_enabled": False, "audit_action": "add"}).passed


def test_remove_keeps_position_monitoring() -> None:
    expected = {"database_assertions": {"watchlist_count": 0, "position_monitoring": True, "audit_action": "remove"}}
    result = WatchlistOutcomeScorer().score(expected, [{"tool_name": "manage_watchlist", "args": {"action": "remove"}}], {"watchlist_count": 0, "position_monitoring": True, "audit_action": "remove"})
    assert result.passed
