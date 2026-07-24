from __future__ import annotations

from pathlib import Path

from eval.chatloop.scenario import Scenario, load_scenarios
from eval.chatloop.scorers import PaperTradingOutcomeScorer

GOLDEN = Path("backend/eval/chatloop/golden/paper_trading.jsonl")


def _case(case_id: str) -> Scenario:
    return next(case for case in load_scenarios(GOLDEN) if case.case_id == case_id)


def test_paper_trading_golden_uses_current_tools_and_loads_in_existing_harness() -> None:
    scenarios = load_scenarios(GOLDEN)
    assert len(scenarios) >= 5
    assert {case.case_id for case in scenarios} >= {
        "paper-research-no-write",
        "paper-buy-missing-quantity",
        "paper-buy-approved",
        "paper-buy-edited-approved",
        "paper-buy-rejected",
    }

    assert all("outcome" in case.expected for case in scenarios)
    serialized = GOLDEN.read_text(encoding="utf-8")
    assert "place_paper_order" in serialized
    assert "ask_user" in serialized
    assert "paper_trade" not in serialized


def test_research_and_missing_quantity_require_no_database_write() -> None:
    scorer = PaperTradingOutcomeScorer()

    research = _case("paper-research-no-write").expected["outcome"]
    research_result = scorer.score(
        research,
        [{"tool_name": "get_stock_quote", "args": {"ts_code": "600519.SH"}}],
        {
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 0, "available_cash": "1000000.00"},
        },
        {"pauses": [], "resumed": False},
    )
    assert research_result.passed

    missing = _case("paper-buy-missing-quantity").expected["outcome"]
    missing_result = scorer.score(
        missing,
        [{"tool_name": "ask_user", "args": {"question": "买多少股？"}}],
        {
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 0, "available_cash": "1000000.00"},
        },
        {"pauses": [{"pause_type": "input"}], "resumed": False},
    )
    assert missing_result.passed

    bad = scorer.score(
        missing,
        [{"tool_name": "place_paper_order", "args": {"ts_code": "600519.SH"}}],
        {
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 1, "available_cash": "850000.00"},
        },
        {"pauses": [{"pause_type": "approval"}], "resumed": False},
    )
    assert not bad.passed
    assert not bad.database_terminal_state


def test_explicit_buy_requires_high_risk_approval_pause_resume_and_database_order() -> None:
    expected = _case("paper-buy-approved").expected["outcome"]
    result = PaperTradingOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "place_paper_order",
                "args": {
                    "ts_code": "600519.SH",
                    "side": "buy",
                    "quantity": 100,
                    "order_type": "limit",
                    "limit_price": "1500",
                },
                "risk_level": "high",
            }
        ],
        {
            "order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
            },
        },
        {
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
        },
    )
    assert result.passed
    assert result.tool_trajectory
    assert result.risk_and_pause
    assert result.resume_semantics
    assert result.database_terminal_state

    no_pause = PaperTradingOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "place_paper_order",
                "args": {"quantity": 100},
                "risk_level": "high",
            }
        ],
        {"order_count": 1, "order": {"quantity": 100}},
        {"pauses": [], "resumed": True},
    )
    assert not no_pause.passed
    assert not no_pause.risk_and_pause

    not_resumed = PaperTradingOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "place_paper_order",
                "args": {
                    "ts_code": "600519.SH",
                    "side": "buy",
                    "quantity": 100,
                    "limit_price": "1500",
                },
                "risk_level": "high",
            }
        ],
        {
            "order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
            },
        },
        {
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": False,
        },
    )
    assert not not_resumed.passed
    assert not not_resumed.resume_semantics


def test_edited_approval_only_accepts_effective_order_and_audits_both_payloads() -> None:
    expected = _case("paper-buy-edited-approved").expected["outcome"]
    good_state = {
        "order_count": 1,
        "order": {"quantity": 200, "limit_price": "1499"},
        "audit": {
            "original": {"quantity": 100, "limit_price": "1500"},
            "effective": {"quantity": 200, "limit_price": "1499"},
        },
    }
    run_state = {
        "pauses": [
            {
                "pause_type": "approval",
                "decision": "approved",
                "original": {"quantity": 100, "limit_price": "1500"},
                "effective": {"quantity": 200, "limit_price": "1499"},
            }
        ],
        "resumed": True,
    }
    trace = [
        {
            "tool_name": "place_paper_order",
            "args": {"quantity": 200, "limit_price": "1499"},
            "risk_level": "high",
        }
    ]
    assert PaperTradingOutcomeScorer().score(expected, trace, good_state, run_state).passed

    original_was_executed = {
        **good_state,
        "order": {"quantity": 100, "limit_price": "1500"},
    }
    result = PaperTradingOutcomeScorer().score(expected, trace, original_was_executed, run_state)
    assert not result.passed
    assert not result.database_terminal_state

    pause_lost_edit_audit = {
        "pauses": [{"pause_type": "approval", "decision": "approved"}],
        "resumed": True,
    }
    result = PaperTradingOutcomeScorer().score(
        expected,
        trace,
        good_state,
        pause_lost_edit_audit,
    )
    assert not result.passed
    assert not result.risk_and_pause


def test_rejection_has_no_order_or_cash_side_effect() -> None:
    expected = _case("paper-buy-rejected").expected["outcome"]
    unchanged = {
        "before": {
            "order_count": 0,
            "available_cash": "1000000.00",
            "reserved_cash": "0.00",
        },
        "after": {
            "order_count": 0,
            "available_cash": "1000000.00",
            "reserved_cash": "0.00",
        },
    }
    run_state = {
        "pauses": [{"pause_type": "approval", "decision": "rejected"}],
        "resumed": True,
    }
    trace = [
        {
            "tool_name": "place_paper_order",
            "args": {"quantity": 100, "limit_price": "1500"},
            "risk_level": "high",
        }
    ]
    assert PaperTradingOutcomeScorer().score(expected, trace, unchanged, run_state).passed

    changed = {
        **unchanged,
        "after": {
            "order_count": 1,
            "available_cash": "850000.00",
            "reserved_cash": "150000.00",
        },
    }
    assert not PaperTradingOutcomeScorer().score(expected, trace, changed, run_state).passed


def test_forbidden_legacy_direct_trade_is_a_hard_failure() -> None:
    result = PaperTradingOutcomeScorer().score(
        {"expected_tools": ["place_paper_order"]},
        [{"tool_name": "buy_stock", "args": {}}],
        {},
        {},
    )
    assert not result.passed
    assert result.score == 0
    assert "buy_stock" in result.detail
