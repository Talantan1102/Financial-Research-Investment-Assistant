from __future__ import annotations

from pathlib import Path

from eval.chatloop.scenario import Scenario, load_scenarios
from eval.chatloop.scorers import WatchlistOutcomeScorer

GOLDEN = Path("backend/eval/chatloop/golden/watchlist_monitoring.jsonl")
OBSERVED = {"observation": {"version": 1, "status": "collected"}}


def _case(case_id: str) -> Scenario:
    return next(case for case in load_scenarios(GOLDEN) if case.case_id == case_id)


def test_watchlist_golden_loads_in_existing_harness_and_uses_current_tool() -> None:
    scenarios = load_scenarios(GOLDEN)
    assert len(scenarios) >= 4
    assert {case.case_id for case in scenarios} >= {
        "watchlist-add-default-monitoring",
        "watchlist-add-explicit-no-monitoring",
        "watchlist-update",
        "watchlist-remove",
    }
    assert all(case.expected["first_tool"] == "manage_watchlist" for case in scenarios)
    assert all("outcome" in case.expected for case in scenarios)
    assert all(
        case.expected["outcome"]["risk_levels"] == {"manage_watchlist": "low"} for case in scenarios
    )


def test_add_defaults_monitoring_off_and_writes_audit_without_pause() -> None:
    expected = _case("watchlist-add-default-monitoring").expected["outcome"]
    result = WatchlistOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "manage_watchlist",
                "args": {"action": "add", "ts_code": "600519.SH"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            }
        ],
        {
            **OBSERVED,
            "watchlist": {
                "count": 1,
                "exists": True,
                "ts_code": "600519.SH",
                "monitoring_enabled": False,
            },
            "audit": {"action": "add", "after": {"monitoring_enabled": False}},
        },
        {**OBSERVED, "pauses": [], "resumed": False, "status": "completed"},
    )
    assert result.passed
    assert result.risk_and_pause

    incorrectly_paused = WatchlistOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "manage_watchlist",
                "args": {"action": "add"},
                "risk_level": "low",
            }
        ],
        {
            "watchlist": {"count": 1, "exists": True, "monitoring_enabled": False},
            "audit": {"action": "add", "after": {"monitoring_enabled": False}},
        },
        {
            "pauses": [{"pause_type": "approval"}],
            "resumed": True,
            "status": "completed",
        },
    )
    assert not incorrectly_paused.passed
    assert not incorrectly_paused.risk_and_pause


def test_watchlist_update_and_remove_require_direct_write_audit_terminal_state() -> None:
    scorer = WatchlistOutcomeScorer()
    update = _case("watchlist-update").expected["outcome"]
    update_result = scorer.score(
        update,
        [
            {
                "tool_name": "manage_watchlist",
                "args": {
                    "action": "update",
                    "ts_code": "600519.SH",
                    "note": "长拿",
                    "monitoring_enabled": True,
                },
                "risk_level": "low",
                "permission_decisions": ["direct"],
            }
        ],
        {
            **OBSERVED,
            "watchlist": {
                "count": 1,
                "exists": True,
                "note": "长拿",
                "monitoring_enabled": True,
            },
            "audit": {"action": "update"},
        },
        {**OBSERVED, "pauses": [], "resumed": False, "status": "completed"},
    )
    assert update_result.passed

    remove = _case("watchlist-remove").expected["outcome"]
    remove_result = scorer.score(
        remove,
        [
            {
                "tool_name": "manage_watchlist",
                "args": {"action": "remove", "ts_code": "600519.SH"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            }
        ],
        {
            **OBSERVED,
            "watchlist": {"count": 0, "exists": False},
            "audit": {"action": "remove"},
        },
        {**OBSERVED, "pauses": [], "resumed": False, "status": "completed"},
    )
    assert remove_result.passed


def test_watchlist_claim_without_database_or_audit_change_fails() -> None:
    expected = _case("watchlist-add-explicit-no-monitoring").expected["outcome"]
    result = WatchlistOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "manage_watchlist",
                "args": {"action": "add"},
                "risk_level": "low",
            }
        ],
        {"watchlist": {"count": 0, "exists": False}, "audit": None},
        {"pauses": [], "resumed": False, "status": "completed"},
    )
    assert not result.passed
    assert not result.database_terminal_state
