from eval.chatloop.scorers import PaperTradingOutcomeScorer


def test_scorer_requires_both_tool_route_and_database_terminal_state() -> None:
    expected = {
        "expected_tools": ["paper_trade"],
        "expected_approval_type": "paper_order",
        "database_assertions": {"order_status": "filled", "position_quantity": 100},
    }
    trace = [{"tool_name": "paper_trade", "args": {"action": "prepare_order", "approval_type": "paper_order"}}]
    scorer = PaperTradingOutcomeScorer()
    assert not scorer.score(expected, trace, {"order_status": "queued", "position_quantity": 100}).passed
    assert scorer.score(expected, trace, {"order_status": "filled", "position_quantity": 100}).passed


def test_forbidden_direct_trade_is_hard_failure() -> None:
    expected = {"expected_tools": ["paper_trade"], "forbidden_tools": ["buy_stock"]}
    result = PaperTradingOutcomeScorer().score(expected, [{"tool_name": "buy_stock", "args": {}}], {})
    assert result.passed is False
    assert result.score == 0

