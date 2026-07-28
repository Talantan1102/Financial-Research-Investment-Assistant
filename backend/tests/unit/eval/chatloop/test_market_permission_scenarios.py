from __future__ import annotations

from pathlib import Path

from eval.chatloop.scenario import load_scenarios
from eval.chatloop.scorers import PaperTradingOutcomeScorer

GOLDEN = Path("backend/eval/chatloop/golden/market_permissions.jsonl")


def _case(case_id: str):
    return next(case for case in load_scenarios(GOLDEN) if case.case_id == case_id)


def test_missing_permission_requires_link_and_forbids_order_write() -> None:
    result = _case("star_permission_missing")

    assert result.required_tools == {
        "check_order_eligibility",
        "get_entitlement_application_link",
    }
    assert "place_paper_order" in result.forbidden_tools
    assert result.expected_outcome == "action_required"


def test_market_permission_golden_covers_permission_and_new_run_boundaries() -> None:
    scenarios = load_scenarios(GOLDEN)

    assert {scenario.case_id for scenario in scenarios} == {
        "main_permission_present",
        "star_permission_missing",
        "chinext_permission_missing",
        "restricted_buy_sell_allowed",
        "permission_return_requires_recheck",
    }
    assert all(scenario.outcome is not None for scenario in scenarios)


def test_missing_permission_scores_terminal_outcome_url_and_unchanged_order_state() -> None:
    expected = _case("star_permission_missing").outcome
    assert expected is not None

    result = PaperTradingOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "check_order_eligibility",
                "args": {"ts_code": "688981.SH", "side": "buy"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            },
            {
                "tool_name": "get_entitlement_application_link",
                "args": {"market": "star"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            },
        ],
        {
            "observation": {"version": 1, "status": "collected"},
            "snapshot_collected": True,
            "order_count": 0,
            "entitlement": {"market": "star", "can_buy": False, "can_sell": False},
        },
        {
            "observation": {"version": 1, "status": "collected"},
            "pauses": [],
            "resumed": False,
            "status": "completed",
            "outcome": {
                "code": "action_required",
                "payload": {"action_url": "/market-permissions/star/apply"},
            },
        },
    )

    assert result.passed
    assert result.terminal_outcome

    wrong_url = PaperTradingOutcomeScorer().score(
        expected,
        [],
        {"observation": {"version": 1, "status": "collected"}},
        {
            "observation": {"version": 1, "status": "collected"},
            "pauses": [],
            "resumed": False,
            "status": "completed",
            "outcome": {
                "code": "action_required",
                "payload": {"action_url": "/market-permissions/chinext/apply"},
            },
        },
    )
    assert not wrong_url.passed
    assert not wrong_url.terminal_outcome
