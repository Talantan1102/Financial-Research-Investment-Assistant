from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.chatloop.state import ChatLoopState
from app.services.llm_step import StepToolCall
from app.services.run_chat_worker import DurableApprovalController, load_tool_risk_policy
from eval.chatloop.run_eval import _run, score_evaluation_results
from eval.chatloop.scenario import Scenario, load_scenarios
from eval.chatloop.scorers import PaperTradingOutcomeScorer
from eval.chatloop.sut_runner import (
    DurableRunHttpTransport,
    SqlOutcomeCollector,
    SutResult,
    TransportObservation,
    run_scenarios,
)

GOLDEN = Path("backend/eval/chatloop/golden/paper_trading.jsonl")
OBSERVED = {"observation": {"version": 1, "status": "collected"}}


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
    assert all(case.outcome is not None and case.outcome["version"] == 1 for case in scenarios)


@pytest.mark.asyncio
async def test_formal_research_golden_uses_production_low_direct_policy_without_pause() -> None:
    scenario = _case("paper-research-no-write")
    controller = DurableApprovalController(load_tool_risk_policy({}), frozenset())
    directive = await controller.check(
        phase="before_tools",
        state=ChatLoopState(user_id="u", session_id="s", request_id="r", messages=[]),
        tool_calls=(
            StepToolCall(
                id="quote",
                name=scenario.expected["first_tool"],
                arguments=json.dumps(scenario.expected["args_contains"]),
            ),
        ),
    )

    assert directive is None
    assert scenario.outcome is not None
    assert scenario.outcome["risk_levels"]["get_stock_quote"] == "low"
    assert scenario.outcome["permission_decisions"]["get_stock_quote"] == ["direct"]


def test_research_and_missing_quantity_require_no_database_write() -> None:
    scorer = PaperTradingOutcomeScorer()

    research = _case("paper-research-no-write").expected["outcome"]
    research_result = scorer.score(
        research,
        [
            {
                "tool_name": "get_stock_quote",
                "args": {"ts_code": "600519.SH"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            }
        ],
        {
            **OBSERVED,
            "snapshot_collected": True,
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 0, "available_cash": "1000000.00"},
        },
        {**OBSERVED, "pauses": [], "resumed": False, "status": "completed"},
    )
    assert research_result.passed

    missing = _case("paper-buy-missing-quantity").expected["outcome"]
    missing_result = scorer.score(
        missing,
        [
            {
                "tool_name": "ask_user",
                "args": {"question": "买多少股？"},
                "risk_level": "low",
                "permission_decisions": ["direct"],
            }
        ],
        {
            **OBSERVED,
            "snapshot_collected": True,
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 0, "available_cash": "1000000.00"},
        },
        {
            **OBSERVED,
            "pauses": [{"pause_type": "input"}],
            "resumed": False,
            "status": "waiting_input",
        },
    )
    assert missing_result.passed

    bad = scorer.score(
        missing,
        [{"tool_name": "place_paper_order", "args": {"ts_code": "600519.SH"}}],
        {
            "snapshot_collected": True,
            "before": {"order_count": 0, "available_cash": "1000000.00"},
            "after": {"order_count": 1, "available_cash": "850000.00"},
        },
        {
            "pauses": [{"pause_type": "approval"}],
            "resumed": False,
            "status": "waiting_approval",
        },
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
                "permission_decisions": ["approval_required", "approved"],
            }
        ],
        {
            **OBSERVED,
            "created_order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
                "source_run_matches": True,
                "current_generation": True,
            },
        },
        {
            **OBSERVED,
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
            "status": "completed",
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
        {"created_order_count": 1, "order": {"quantity": 100}},
        {"pauses": [], "resumed": True, "status": "completed"},
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
            "created_order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
                "source_run_matches": True,
                "current_generation": True,
            },
        },
        {
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": False,
            "status": "waiting_approval",
        },
    )
    assert not not_resumed.passed
    assert not not_resumed.resume_semantics


@pytest.mark.parametrize(
    "observed_permissions",
    [
        None,
        ["approval_required", "unknown"],
        ["direct"],
    ],
    ids=["missing", "unknown", "conflicting"],
)
def test_permission_trajectory_fails_closed_on_invalid_durable_decision(
    observed_permissions: list[str] | None,
) -> None:
    expected = {
        **(_case("paper-buy-approved").expected["outcome"]),
        "permission_decisions": {
            "place_paper_order": ["approval_required", "approved"],
        },
    }
    call = {
        "tool_name": "place_paper_order",
        "args": {
            "ts_code": "600519.SH",
            "side": "buy",
            "quantity": 100,
            "limit_price": "1500",
        },
        "risk_level": "high",
    }
    if observed_permissions is not None:
        call["permission_decisions"] = observed_permissions
    result = PaperTradingOutcomeScorer().score(
        expected,
        [call],
        {
            **OBSERVED,
            "created_order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
                "source_run_matches": True,
                "current_generation": True,
            },
        },
        {
            **OBSERVED,
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
            "status": "completed",
        },
    )

    assert result.score == 0
    assert not result.passed
    assert "permission" in result.detail


def _approved_call(
    *,
    permissions: list[str] | None = None,
    risk: str | None = "high",
    quantity: int = 100,
) -> dict[str, Any]:
    call: dict[str, Any] = {
        "tool_name": "place_paper_order",
        "args": {
            "ts_code": "600519.SH",
            "side": "buy",
            "quantity": quantity,
            "limit_price": "1500",
        },
    }
    if risk is not None:
        call["risk_level"] = risk
    if permissions is not None:
        call["permission_decisions"] = permissions
    return call


def _approved_states() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            **OBSERVED,
            "created_order_count": 1,
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
                "source_run_matches": True,
                "current_generation": True,
            },
        },
        {
            **OBSERVED,
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
            "status": "completed",
        },
    )


@pytest.mark.parametrize(
    "calls",
    [
        [
            _approved_call(permissions=["approval_required", "unknown"]),
            _approved_call(permissions=["approval_required", "approved"]),
        ],
        [
            _approved_call(permissions=["approval_required", "approved"]),
            _approved_call(permissions=["approval_required", "unknown"]),
        ],
        [
            _approved_call(risk="unknown", permissions=["approval_required", "approved"]),
            _approved_call(permissions=["approval_required", "approved"]),
        ],
        [
            _approved_call(quantity=200, permissions=["approval_required", "approved"]),
            _approved_call(permissions=["approval_required", "approved"]),
        ],
    ],
    ids=["bad-then-good", "good-then-bad", "bad-risk-then-good", "bad-args-then-good"],
)
def test_every_matching_call_must_have_valid_risk_permission_and_args(
    calls: list[dict[str, Any]],
) -> None:
    expected = {
        **(_case("paper-buy-approved").expected["outcome"]),
        "call_counts": {"place_paper_order": {"min": 1, "max": 2}},
    }
    database_state, run_state = _approved_states()

    result = PaperTradingOutcomeScorer().score(expected, calls, database_state, run_state)

    assert result.score == 0
    assert not result.passed


def test_repeated_write_is_a_hard_failure_even_when_terminal_state_looks_correct() -> None:
    expected = _case("paper-buy-approved").expected["outcome"]
    database_state, run_state = _approved_states()
    calls = [
        _approved_call(permissions=["approval_required", "approved"]),
        _approved_call(permissions=["approval_required", "approved"]),
    ]

    result = PaperTradingOutcomeScorer().score(expected, calls, database_state, run_state)

    assert result.score == 0
    assert not result.passed
    assert "call count" in result.detail


def test_unexpected_modern_write_is_a_hard_failure() -> None:
    expected = _case("paper-buy-approved").expected["outcome"]
    database_state, run_state = _approved_states()
    calls = [
        _approved_call(permissions=["approval_required", "approved"]),
        {
            "tool_name": "cancel_paper_order",
            "args": {"order_id": "unexpected"},
            "risk_level": "high",
            "permission_decisions": ["approval_required", "approved"],
        },
    ]

    result = PaperTradingOutcomeScorer().score(expected, calls, database_state, run_state)

    assert result.score == 0
    assert "unexpected write" in result.detail


def test_repeated_read_is_allowed_only_with_explicit_count_and_every_call_is_low_direct() -> None:
    expected = {
        **(_case("paper-research-no-write").expected["outcome"]),
        "call_counts": {"get_stock_quote": {"min": 1, "max": 2}},
    }
    calls = [
        {
            "tool_name": "get_stock_quote",
            "args": {"ts_code": "600519.SH"},
            "risk_level": "low",
            "permission_decisions": ["direct"],
        },
        {
            "tool_name": "get_stock_quote",
            "args": {"ts_code": "600519.SH"},
            "risk_level": "low",
            "permission_decisions": ["direct"],
        },
    ]
    database_state = {
        **OBSERVED,
        "snapshot_collected": True,
        "before": {"order_count": 0, "available_cash": "1000000.00"},
        "after": {"order_count": 0, "available_cash": "1000000.00"},
    }
    run_state = {**OBSERVED, "pauses": [], "resumed": False, "status": "completed"}

    assert PaperTradingOutcomeScorer().score(
        expected, calls, database_state, run_state
    ).passed
    calls[0]["permission_decisions"] = ["approved"]
    assert (
        PaperTradingOutcomeScorer().score(expected, calls, database_state, run_state).score
        == 0
    )


def test_edited_approval_only_accepts_effective_order_and_audits_both_payloads() -> None:
    expected = _case("paper-buy-edited-approved").expected["outcome"]
    good_state = {
        **OBSERVED,
        "created_order_count": 1,
        "order": {
            "quantity": 200,
            "limit_price": "1499",
            "source_run_matches": True,
            "current_generation": True,
        },
        "audit": {
            "original": {"quantity": 100, "limit_price": "1500"},
            "effective": {"quantity": 200, "limit_price": "1499"},
        },
    }
    run_state = {
        **OBSERVED,
        "pauses": [
            {
                "pause_type": "approval",
                "decision": "approved",
                "original": {"quantity": 100, "limit_price": "1500"},
                "effective": {"quantity": 200, "limit_price": "1499"},
            }
        ],
        "resumed": True,
        "status": "completed",
    }
    trace = [
        {
            "tool_name": "place_paper_order",
            "args": {"quantity": 200, "limit_price": "1499"},
            "risk_level": "high",
            "permission_decisions": ["approval_required", "approved"],
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
        "status": "completed",
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
        **OBSERVED,
        "snapshot_collected": True,
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
        **OBSERVED,
        "pauses": [{"pause_type": "approval", "decision": "rejected"}],
        "resumed": True,
        "status": "completed",
    }
    trace = [
        {
            "tool_name": "place_paper_order",
            "args": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
            },
            "risk_level": "high",
            "permission_decisions": ["approval_required", "rejected"],
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
        {
            "version": 1,
            "type": "paper_trading",
            "expected_tools": ["place_paper_order"],
            "tool_args_contains": {"place_paper_order": {}},
            "call_counts": {"place_paper_order": {"min": 1, "max": 1}},
            "risk_levels": {"place_paper_order": "high"},
            "permission_decisions": {
                "place_paper_order": ["approval_required", "approved"],
            },
            "run": {
                "pause_type": "approval",
                "decision": "approved",
                "resumed": True,
                "status": "completed",
            },
            "database_assertions": {"order_count": 0},
        },
        [{"tool_name": "buy_stock", "args": {}}],
        {**OBSERVED, "order_count": 0},
        {
            **OBSERVED,
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
            "status": "completed",
        },
    )
    assert not result.passed
    assert result.score == 0
    assert "buy_stock" in result.detail


def test_outcome_scorer_fails_closed_when_observed_run_or_database_is_missing() -> None:
    expected = _case("paper-buy-approved").outcome
    assert expected is not None
    trace = [
        {
            "tool_name": "place_paper_order",
            "args": {"quantity": 100},
            "risk_level": "high",
        }
    ]
    result = PaperTradingOutcomeScorer().score(expected, trace, None, None)
    assert not result.passed
    assert result.score == 0
    assert "missing observed" in result.detail


@pytest.mark.parametrize(
    ("database_state", "run_state"),
    [
        ({}, {"pauses": [], "resumed": False, "status": "completed"}),
        ({"snapshot_collected": True}, {}),
        ({}, {}),
        (
            {"snapshot_collected": True},
            {"pauses": [], "resumed": False, "status": "completed"},
        ),
    ],
)
def test_empty_actual_observation_scores_zero_instead_of_partial_credit(
    database_state: dict[str, object],
    run_state: dict[str, object],
) -> None:
    expected = _case("paper-research-no-write").expected["outcome"]
    result = PaperTradingOutcomeScorer().score(
        expected,
        [
            {
                "tool_name": "get_stock_quote",
                "args": {"ts_code": "600519.SH"},
                "risk_level": "low",
            }
        ],
        database_state,
        run_state,
    )
    assert result.score == 0
    assert not result.passed
    assert not result.tool_trajectory
    assert not result.risk_and_pause
    assert not result.resume_semantics
    assert not result.database_terminal_state


def test_durable_transport_maps_interaction_to_real_resume_payload_and_trace() -> None:
    scenario = _case("paper-buy-edited-approved")
    request = {
        "tool_calls": [
            {
                "id": "call-1",
                "name": "place_paper_order",
                "arguments": {
                    "ts_code": "600519.SH",
                    "side": "buy",
                    "quantity": 100,
                    "order_type": "limit",
                    "limit_price": "1500",
                },
            }
        ]
    }
    response = DurableRunHttpTransport._resume_payload(scenario, request)
    assert response["approved"] is True
    assert response["edited_arguments"]["call-1"]["quantity"] == 200
    assert response["edited_arguments"]["call-1"]["limit_price"] == "1499"

    trace = DurableRunHttpTransport._pause_trace(
        SimpleNamespace(
            pause_type="approval",
            request_payload=request,
            response_payload=response,
        )
    )
    assert trace["decision"] == "approved"
    assert trace["original"]["quantity"] == 100
    assert trace["effective"]["quantity"] == 200

    rejected = DurableRunHttpTransport._resume_payload(
        _case("paper-buy-rejected"),
        request,
    )
    assert rejected == {"approved": False}


@pytest.mark.parametrize(
    "outcome",
    [
        {
            "type": "paper_trading",
            "expected_tools": ["place_paper_order"],
            "tool_args_contains": {"place_paper_order": {}},
            "call_counts": {"place_paper_order": {"min": 1, "max": 1}},
            "risk_levels": {"place_paper_order": "high"},
            "permission_decisions": {
                "place_paper_order": ["approval_required", "approved"],
            },
            "run": {
                "pause_type": "approval",
                "decision": "approved",
                "resumed": True,
                "status": "completed",
            },
            "database_assertions": {"order_count": 1},
        },
        {
            "version": 1,
            "type": "paper_trading",
            "expected_tools": ["place_paper_order"],
            "tool_args_contains": {"place_paper_order": {}},
            "call_counts": {"place_paper_order": {"min": 1, "max": 1}},
            "risk_levels": {"place_paper_order": "high"},
            "permission_decisions": {
                "place_paper_order": ["approval_required", "approved"],
            },
            "run": {
                "pause_type": "approval",
                "decision": "approved",
                "resumed": True,
                "status": "completed",
            },
            "database_assertions": {"order_count": 1},
        },
    ],
)
def test_outcome_contract_fails_closed_when_version_or_interaction_is_missing(
    tmp_path: Path,
    outcome: dict[str, Any],
) -> None:
    raw = {
        "case_id": "bad-outcome",
        "category": "paper_trading",
        "user_input": "茅台给我整100股，1500挂着啊",
        "expected": {"first_tool": "place_paper_order", "outcome": outcome},
        "bucket": "金融数据",
        "difficulty": "直球",
    }
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="outcome"):
        load_scenarios(path)


def test_outcome_contract_fails_closed_when_call_counts_are_missing(tmp_path: Path) -> None:
    scenario = _case("paper-research-no-write")
    outcome = dict(scenario.expected["outcome"])
    outcome.pop("call_counts")
    raw = {
        "case_id": "missing-call-counts",
        "category": scenario.category,
        "user_input": scenario.user_input,
        "expected": {"first_tool": "get_stock_quote", "outcome": outcome},
        "bucket": scenario.bucket,
        "difficulty": scenario.difficulty,
    }
    path = tmp_path / "missing-call-counts.jsonl"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="call_counts"):
        load_scenarios(path)


class _FakeTransport:
    user_id = "00000000-0000-4000-8000-000000000001"

    async def execute(self, scenario: Scenario, run_idx: int) -> TransportObservation:
        del scenario, run_idx
        return TransportObservation(
            run_id="00000000-0000-4000-8000-000000000099",
            tool_calls=[
                {
                    "tool_name": "place_paper_order",
                    "args": {
                        "ts_code": "600519.SH",
                        "side": "buy",
                        "quantity": 100,
                        "limit_price": "1500",
                    },
                    "risk_level": "high",
                    "permission_decision": "approved",
                    "permission_decisions": ["approval_required", "approved"],
                }
            ],
            response_text="已提交",
            escalate_offered=False,
            run_state={
                **OBSERVED,
                "pauses": [{"pause_type": "approval", "decision": "approved"}],
                "resumed": True,
                "status": "completed",
            },
        )


class _FakeCollector:
    def __init__(self, *, wrong_after: bool = False) -> None:
        self._calls = 0
        self.prepared: list[str] = []
        self._wrong_after = wrong_after

    async def prepare(
        self,
        *,
        user_id: str,
        scenario: Scenario,
        sample_key: str,
    ) -> None:
        del user_id, scenario
        self.prepared.append(sample_key)
        self._calls = 0

    async def capture(
        self,
        *,
        user_id: str,
        run_id: str | None,
        scenario: Scenario,
    ) -> dict[str, Any]:
        del user_id, run_id, scenario
        self._calls += 1
        if self._calls == 1:
            return {
                **OBSERVED,
                "snapshot_collected": True,
                "order_count": 0,
                "available_cash": "1000000.00",
            }
        return {
            **OBSERVED,
            "snapshot_collected": True,
            "created_order_count": 0 if self._wrong_after else 1,
            "order_count": 0 if self._wrong_after else 1,
            "available_cash": "1000000.00",
            "order": {
                "ts_code": "600519.SH",
                "side": "buy",
                "quantity": 100,
                "limit_price": "1500",
                "source_run_matches": True,
                "current_generation": True,
            },
        }


@pytest.mark.asyncio
async def test_real_runner_seam_preserves_durable_risk_runpause_and_database_snapshots() -> None:
    scenario = _case("paper-buy-approved")
    [result] = await run_scenarios(
        [scenario],
        outcome_transport=_FakeTransport(),
        outcome_collector=_FakeCollector(),
    )
    assert result.tool_calls[0]["risk_level"] == "high"
    assert result.run_state == {
        **OBSERVED,
        "pauses": [{"pause_type": "approval", "decision": "approved"}],
        "resumed": True,
        "status": "completed",
    }
    assert result.database_state["before"]["order_count"] == 0
    assert result.database_state["after"]["order_count"] == 1


@pytest.mark.asyncio
async def test_each_k_sample_is_prepared_before_its_before_snapshot() -> None:
    scenario = _case("paper-buy-approved")
    collector = _FakeCollector()
    results = await run_scenarios(
        [scenario],
        k=5,
        outcome_transport=_FakeTransport(),
        outcome_collector=collector,
    )
    assert collector.prepared == [f"{scenario.case_id}:{run_idx}" for run_idx in range(5)]
    assert len(results) == 5
    assert all(result.database_state["before"]["order_count"] == 0 for result in results)
    assert all(result.database_state["after"]["created_order_count"] == 1 for result in results)


@pytest.mark.asyncio
async def test_default_collector_refuses_non_dedicated_user_before_touching_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CHATLOOP_EVAL_USER_ID",
        "00000000-0000-4000-8000-000000000002",
    )
    collector = SqlOutcomeCollector(session_factory=None)
    with pytest.raises(RuntimeError, match="dedicated eval user"):
        await collector.prepare(
            user_id="00000000-0000-4000-8000-000000000002",
            scenario=_case("paper-buy-approved"),
            sample_key="paper-buy-approved:0",
        )


@pytest.mark.asyncio
async def test_runner_does_not_synthesize_missing_runtime_risk() -> None:
    scenario = _case("paper-buy-approved")
    transport = _FakeTransport()
    original_execute = transport.execute

    async def execute_without_risk(
        case: Scenario,
        run_idx: int,
    ) -> TransportObservation:
        observed = await original_execute(case, run_idx)
        calls = [
            {key: value for key, value in call.items() if key != "risk_level"}
            for call in observed.tool_calls
        ]
        return TransportObservation(
            run_id=observed.run_id,
            tool_calls=calls,
            response_text=observed.response_text,
            escalate_offered=observed.escalate_offered,
            run_state=observed.run_state,
        )

    transport.execute = execute_without_risk  # type: ignore[method-assign]
    [result] = await run_scenarios(
        [scenario],
        outcome_transport=transport,
        outcome_collector=_FakeCollector(),
    )
    assert "risk_level" not in result.tool_calls[0]
    scored = PaperTradingOutcomeScorer().score(
        scenario.outcome or {},
        result.tool_calls,
        result.database_state,
        result.run_state,
    )
    assert not scored.risk_and_pause


def test_formal_eval_combines_behavior_and_outcome_and_fails_wrong_database() -> None:
    scenario = _case("paper-buy-approved")
    result = SutResult(
        case_id=scenario.case_id,
        run_idx=0,
        tool_calls=[
            {
                "tool_name": "place_paper_order",
                "args": {
                    "ts_code": "600519.SH",
                    "side": "buy",
                    "quantity": 100,
                    "limit_price": "1500",
                },
                "risk_level": "high",
                "permission_decisions": ["approval_required", "approved"],
            }
        ],
        response_text="已提交",
        escalate_offered=False,
        run_state={
            "pauses": [{"pause_type": "approval", "decision": "approved"}],
            "resumed": True,
            "status": "completed",
        },
        database_state={
            "before": {"order_count": 0},
            "after": {"order_count": 0},
            "order_count": 0,
            "created_order_count": 0,
        },
    )
    batch = score_evaluation_results([scenario], [result], offline=False, k=1)
    assert not batch.per_run_pass[scenario.case_id][0]
    assert not batch.outcome_scores[scenario.case_id][0].database_terminal_state


@pytest.mark.asyncio
async def test_run_eval_entry_reports_outcome_failure_and_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenario = _case("paper-buy-approved")

    async def fake_runner(
        scenarios: list[Scenario],
        *,
        dispatch_mode: str,
        k: int,
    ) -> list[SutResult]:
        del dispatch_mode
        transport = _FakeTransport()
        observation = await transport.execute(scenario, 0)
        transport_without_pause = _FakeTransport()

        async def missing_pause(
            _scenario: Scenario,
            _run_idx: int,
        ) -> TransportObservation:
            return TransportObservation(
                run_id=observation.run_id,
                tool_calls=observation.tool_calls,
                response_text=observation.response_text,
                escalate_offered=False,
                run_state={"pauses": [], "resumed": True, "status": "completed"},
            )

        transport_without_pause.execute = missing_pause  # type: ignore[method-assign]
        return await run_scenarios(
            scenarios,
            k=k,
            outcome_transport=transport_without_pause,
            outcome_collector=_FakeCollector(wrong_after=True),
        )

    exit_code = await _run(
        [scenario],
        k=1,
        dispatch="noop",
        offline=False,
        golden_path=GOLDEN,
        runner=fake_runner,
        record=False,
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "状态变更终态评分" in output
    assert "数据库终态" in output
