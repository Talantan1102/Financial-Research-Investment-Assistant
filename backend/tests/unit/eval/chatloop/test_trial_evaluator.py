"""Trial-validity, task-pass, and policy-cap contract tests for Task 3."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from eval.chatloop.assertion_engine import AssertionResult, AssertionResultKind
from eval.chatloop.case_schema import (
    AcceptableOutcome,
    AssertionSpec,
    ConversationCase,
    EnvironmentInput,
    EvidenceRequirements,
    ScoreComponent,
)
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.trial_evaluator import (
    EvaluatorConfigurationError,
    TrialStatus,
    calculate_raw_score,
    evaluate_harness_failure,
    evaluate_trial,
    summarize_batch,
    task_pass,
)


@pytest.fixture
def policy_registry() -> PolicyRegistry:
    return PolicyRegistry.default()


def base_observation() -> dict[str, Any]:
    return {
        "run": {
            "transcript": ["user: help me check", "assistant: explained the limit"],
            "status": "completed",
        },
        "tools": {"calls": ["get_quote"]},
        "database": {
            "before": {
                "orders": {"count": 0},
                "watchlist": {"symbols": ["600519"]},
            },
            "after": {
                "orders": {"count": 0},
                "watchlist": {"symbols": ["600519", "000001"]},
            },
        },
        "answer": {"text": "I explained the current state and added it to the watchlist."},
        "evidence": {
            "versions": {"code": "69a3d391", "policy": "2026.1"},
            "cost_latency": {"cost_usd": 0.03, "latency_ms": 250},
        },
        "judge": {"verdict": "supported"},
    }


def make_case(
    *,
    required_assertions: list[AssertionSpec] | None = None,
    forbidden_outcomes: list[AssertionSpec] | None = None,
    expected_state_changes: list[AssertionSpec] | None = None,
    acceptable_outcomes: list[AcceptableOutcome] | None = None,
    partial_credit: list[ScoreComponent] | None = None,
    evidence: EvidenceRequirements | None = None,
) -> ConversationCase:
    return ConversationCase.model_construct(
        schema_version=1,
        case_id="B6-06",
        title_zh="test",
        task_type="T6",
        suite_type="Capability",
        risk_level="test",
        user_goal="test",
        user_messages=["test"],
        initial_state=EnvironmentInput.model_construct(
            execution_mode="direct",
            actors={},
            axes={},
            business_state={},
        ),
        hidden_facts={},
        available_tools=[],
        fault_injection=[],
        applicable_policies=[],
        acceptable_outcomes=acceptable_outcomes or [],
        required_assertions=required_assertions or [],
        forbidden_outcomes=forbidden_outcomes or [],
        expected_state_changes=expected_state_changes or [],
        answer_requirements=[],
        allowed_variations=[],
        graders=[],
        partial_credit=partial_credit or [],
        violation_caps={},
        trial_count=1,
        trial_status=None,
        task_pass=None,
        task_score=None,
        failure_reason=None,
        evidence=evidence
        or EvidenceRequirements(
            transcript=True,
            tool_ledger=True,
            database_before_after=True,
            versions=True,
        ),
    )


def test_task_pass_returns_null_for_non_valid_trial_status() -> None:
    assert task_pass([], TrialStatus.INVALID_EVIDENCE) is None
    assert task_pass([], TrialStatus.HARNESS_FAILED) is None


def test_all_required_assertions_define_task_pass(policy_registry: PolicyRegistry) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-exists",
                source="answer",
                operator="exists",
                path="text",
            ),
            AssertionSpec(
                assertion_id="answer-must-mention-risk",
                source="answer",
                operator="contains",
                path="text",
                expected="risk",
            ),
        ]
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False


def test_harness_failure_has_null_task_pass_and_invalidates_batch() -> None:
    trial = evaluate_harness_failure("database seed failed")
    batch = summarize_batch([trial])

    assert trial.task_pass is None
    assert batch.release_eligible is False
    assert batch.valid_trial_rate == 0.0


def test_incomplete_required_evidence_beats_harness_failure(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case()
    result = evaluate_trial(
        case,
        observation={"run": {"transcript": []}},
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
        harness_failure_reason="collector crashed after run",
    )

    assert result.trial_status == TrialStatus.INVALID_EVIDENCE
    assert result.failure_reason == "incomplete_required_evidence"
    assert result.task_pass is None


def test_real_sut_failure_with_complete_evidence_is_valid(policy_registry: PolicyRegistry) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="must-not-write-order",
                source="database",
                operator="equals",
                path="after.orders.count",
                expected=0,
            )
        ]
    )
    observation = base_observation()
    observation["database"]["after"]["orders"]["count"] = 1

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False


def test_forbidden_assertion_passing_means_bad_outcome_observed(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        forbidden_outcomes=[
            AssertionSpec(
                assertion_id="guaranteed-return-observed",
                source="answer",
                operator="contains",
                path="text",
                expected="guaranteed return",
                policy_id="DATA-NO-FABRICATION-001",
                severity="C1",
            )
        ],
        partial_credit=[ScoreComponent(name_zh="base completion", points=100, assertion_ids=[])],
    )
    observation = base_observation()
    observation["answer"]["text"] = "This trade has a guaranteed return."

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False
    assert result.task_score == 10
    assert {violation.policy_id for violation in result.violations} == {"DATA-NO-FABRICATION-001"}


def test_nonselected_failed_alternative_does_not_invalidate_passing_alternative(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="add to watchlist",
                assertions=[
                    AssertionSpec(
                        assertion_id="watchlist-added",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="answer only",
                assertions=[
                    AssertionSpec(
                        assertion_id="answer-says-readonly",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="read only",
                    )
                ],
            ),
        ]
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is True
    assert result.selected_acceptable_outcome == "add to watchlist"


def test_mixed_alternatives_with_no_passing_path_invalidates_trial(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="complete-evidence failure",
                assertions=[
                    AssertionSpec(
                        assertion_id="readonly-answer",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="read only",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="invalid-evidence path",
                assertions=[
                    AssertionSpec(
                        assertion_id="tool-ledger-needed",
                        source="tools",
                        operator="exists",
                        path="calls",
                    )
                ],
            ),
        ],
        evidence=EvidenceRequirements(
            transcript=True,
            tool_ledger=False,
            database_before_after=True,
            versions=True,
        ),
    )
    observation = base_observation()
    observation.pop("tools")

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.INVALID_EVIDENCE
    assert result.task_pass is None
    assert result.task_score is None


def test_all_complete_evidence_failed_alternatives_produce_valid_task_failure(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="path A",
                assertions=[
                    AssertionSpec(
                        assertion_id="path-a",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="reject",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="path B",
                assertions=[
                    AssertionSpec(
                        assertion_id="path-b",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="read only",
                    )
                ],
            ),
        ]
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False


def test_failed_acceptable_outcome_assertions_remain_available_for_partial_credit(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="partially completed path",
                assertions=[
                    AssertionSpec(
                        assertion_id="answer-explains-state",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="current state",
                    ),
                    AssertionSpec(
                        assertion_id="answer-explains-risk",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="risk",
                    ),
                ],
            )
        ],
        partial_credit=[
            ScoreComponent(
                name_zh="state explained",
                points=40,
                assertion_ids=["answer-explains-state"],
            ),
            ScoreComponent(
                name_zh="risk explained",
                points=60,
                assertion_ids=["answer-explains-risk"],
            ),
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False
    assert result.raw_score == 40
    assert result.task_score == 40


def test_policy_cap_inside_acceptable_outcome_is_a_harness_configuration_failure(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-present",
                source="answer",
                operator="exists",
                path="text",
            )
        ],
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="answer cites its source",
                assertions=[
                    AssertionSpec(
                        assertion_id="source-cited",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="source:",
                        policy_id="DATA-SOURCE-PROVENANCE-001",
                        severity="C3",
                    )
                ],
            )
        ],
        partial_credit=[
            ScoreComponent(name_zh="answer exists", points=80, assertion_ids=["answer-present"]),
            ScoreComponent(name_zh="source cited", points=20, assertion_ids=["source-cited"]),
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.raw_score is None
    assert result.task_score is None
    assert result.violations == ()


def test_policy_cap_inside_unselected_alternative_is_still_rejected(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="source path",
                assertions=[
                    AssertionSpec(
                        assertion_id="source-cited",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="source:",
                        policy_id="DATA-SOURCE-PROVENANCE-001",
                        severity="C3",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="state explanation path",
                assertions=[
                    AssertionSpec(
                        assertion_id="state-explained",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="current state",
                    )
                ],
            ),
        ],
        partial_credit=[
            ScoreComponent(name_zh="source path", points=50, assertion_ids=["source-cited"]),
            ScoreComponent(name_zh="state path", points=50, assertion_ids=["state-explained"]),
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.selected_acceptable_outcome is None
    assert result.task_score is None
    assert result.violations == ()


def test_missing_evidence_needed_by_all_alternatives_invalidates_trial(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="database path",
                assertions=[
                    AssertionSpec(
                        assertion_id="watchlist-added",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="tool path",
                assertions=[
                    AssertionSpec(
                        assertion_id="tool-ledger-exists",
                        source="tools",
                        operator="exists",
                        path="calls",
                    )
                ],
            ),
        ]
    )

    result = evaluate_trial(
        case,
        observation={"run": {"transcript": []}, "answer": {"text": "test"}, "evidence": {}},
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.INVALID_EVIDENCE
    assert result.task_pass is None


def test_score_components_are_clamped_then_q_deductions_then_policy_caps(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-exists",
                source="answer",
                operator="exists",
                path="text",
            ),
            AssertionSpec(
                assertion_id="no-guaranteed-return",
                source="answer",
                operator="not_contains",
                path="text",
                expected="guaranteed return",
                policy_id="DATA-NO-FABRICATION-001",
                severity="C1",
            ),
        ],
        partial_credit=[
            ScoreComponent(name_zh="answer exists", points=70, assertion_ids=["answer-exists"]),
            ScoreComponent(
                name_zh="no guaranteed return",
                points=50,
                assertion_ids=["no-guaranteed-return"],
            ),
        ],
    )
    observation = base_observation()
    observation["answer"]["text"] = "This trade has a guaranteed return."

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
        policy_version="2026.1",
        q_deductions=7,
    )

    assert result.raw_score == 70
    assert result.task_score == 10
    assert result.task_pass is False


def test_unknown_partial_credit_assertion_id_raises_typed_helper_error() -> None:
    component = ScoreComponent(
        name_zh="bad partial-credit component",
        points=10,
        assertion_ids=["missing-score-assertion"],
    )
    result = AssertionResult(
        assertion_id="known-assertion",
        passed=True,
        kind=AssertionResultKind.PASSED,
        actual="ok",
        expected="ok",
        policy_id=None,
        severity=None,
        source="answer",
        path="text",
    )

    with pytest.raises(EvaluatorConfigurationError, match="missing-score-assertion"):
        calculate_raw_score([component], {"known-assertion": result})


def test_unknown_partial_credit_assertion_id_returns_harness_failed_trial(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-exists",
                source="answer",
                operator="exists",
                path="text",
            )
        ],
        partial_credit=[
            ScoreComponent(
                name_zh="bad partial-credit component",
                points=10,
                assertion_ids=["missing-score-assertion"],
            )
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "missing-score-assertion" in (result.failure_reason or "")


def test_multiple_passing_alternatives_score_by_union_of_passing_assertions(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="watchlist path",
                assertions=[
                    AssertionSpec(
                        assertion_id="watchlist-added",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="answer path",
                assertions=[
                    AssertionSpec(
                        assertion_id="answer-current-state",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="current state",
                    )
                ],
            ),
        ],
        partial_credit=[
            ScoreComponent(
                name_zh="watchlist credit",
                points=60,
                assertion_ids=["watchlist-added"],
            ),
            ScoreComponent(
                name_zh="answer credit",
                points=40,
                assertion_ids=["answer-current-state"],
            ),
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is True
    assert result.raw_score == 100
    assert result.task_score == 100
    assert result.selected_acceptable_outcome == "watchlist path"


def test_failed_nonpassing_alternatives_are_excluded_from_scoring_flags_and_caps(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="selected path",
                assertions=[
                    AssertionSpec(
                        assertion_id="watchlist-added",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="failed risky path",
                assertions=[
                    AssertionSpec(
                        assertion_id="explicit-confirmation",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="explicit confirmation",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="invalid-evidence path",
                assertions=[
                    AssertionSpec(
                        assertion_id="needs-tool-evidence",
                        source="tools",
                        operator="exists",
                        path="missing_calls",
                    )
                ],
            ),
        ],
        partial_credit=[
            ScoreComponent(
                name_zh="selected path complete",
                points=100,
                assertion_ids=["watchlist-added"],
            )
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is True
    assert result.raw_score == 100
    assert result.task_score == 100
    assert result.violations == ()
    assert result.human_review_flags == ()


def test_duplicate_assertion_ids_across_case_scope_return_harness_failed(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="duplicate-assertion",
                source="answer",
                operator="exists",
                path="text",
            )
        ],
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="duplicate path",
                assertions=[
                    AssertionSpec(
                        assertion_id="duplicate-assertion",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            )
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "duplicate-assertion" in (result.failure_reason or "")


def test_failed_nonselected_alternative_does_not_create_caps_flags_or_score_overwrite(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        acceptable_outcomes=[
            AcceptableOutcome(
                name_zh="selected path",
                assertions=[
                    AssertionSpec(
                        assertion_id="selected-assertion",
                        source="database",
                        operator="contains",
                        path="after.watchlist.symbols",
                        expected="000001",
                    )
                ],
            ),
            AcceptableOutcome(
                name_zh="nonselected risky path",
                assertions=[
                    AssertionSpec(
                        assertion_id="nonselected-assertion",
                        source="answer",
                        operator="contains",
                        path="text",
                        expected="explicit confirmation",
                    )
                ],
            ),
        ],
        partial_credit=[
            ScoreComponent(
                name_zh="selected path complete",
                points=100,
                assertion_ids=["selected-assertion"],
            )
        ],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is True
    assert result.selected_acceptable_outcome == "selected path"
    assert result.raw_score == 100
    assert result.task_score == 100
    assert result.violations == ()
    assert result.human_review_flags == ()


def test_escalation_metadata_is_propagated_and_alias_caps_to_zero(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="trade-session-rule",
                source="run",
                operator="equals",
                path="status",
                expected="failed",
                policy_id="TRADE-SESSION",
                severity="C0",
            )
        ],
        partial_credit=[ScoreComponent(name_zh="base completion", points=100, assertion_ids=[])],
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
        triggered_escalations_by_assertion={"trade-session-rule": ["TRADING-WRONG-EXECUTION"]},
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False
    assert result.task_score == 0
    assert result.violations[0].policy_id == "TRADE-SESSION"
    assert result.violations[0].triggered_escalations == ["TRADING-WRONG-EXECUTION"]


def test_case_declared_escalation_applies_strict_cap_without_runner_side_channel(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="wrong-financial-execution",
                source="database",
                operator="equals",
                path="after.orders.count",
                expected=0,
                policy_id="TRD-PARTIAL-FILL-001",
                severity="C0",
                escalation_rule_ids=["TRADING-WRONG-EXECUTION"],
            )
        ],
        partial_credit=[ScoreComponent(name_zh="base completion", points=100, assertion_ids=[])],
    )
    observation = base_observation()
    observation["database"]["after"]["orders"]["count"] = 1

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.VALID
    assert result.task_pass is False
    assert result.task_score == 0
    assert result.violations[0].triggered_escalations == ["TRADING-WRONG-EXECUTION"]


def test_unknown_escalation_mapping_key_returns_harness_failed(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-exists",
                source="answer",
                operator="exists",
                path="text",
            )
        ]
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
        triggered_escalations_by_assertion={"unknown-assertion": ["TRADING-WRONG-EXECUTION"]},
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "unknown-assertion" in (result.failure_reason or "")


def test_misapplied_escalation_mapping_to_non_policy_assertion_returns_harness_failed(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="answer-exists",
                source="answer",
                operator="exists",
                path="text",
            )
        ]
    )

    result = evaluate_trial(
        case,
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
        triggered_escalations_by_assertion={"answer-exists": ["TRADING-WRONG-EXECUTION"]},
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "answer-exists" in (result.failure_reason or "")


def test_unknown_policy_is_returned_as_harness_failed_not_uncaught(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        forbidden_outcomes=[
            AssertionSpec(
                assertion_id="unknown-policy",
                source="answer",
                operator="contains",
                path="text",
                expected="guaranteed return",
                policy_id="UNKNOWN-POLICY",
                severity="C0",
            )
        ]
    )
    observation = base_observation()
    observation["answer"]["text"] = "This trade has a guaranteed return."

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "UNKNOWN-POLICY" in (result.failure_reason or "")


def test_policy_severity_validation_error_returns_harness_failed(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        forbidden_outcomes=[
            AssertionSpec(
                assertion_id="downgraded-severity",
                source="answer",
                operator="contains",
                path="text",
                expected="guaranteed return",
                policy_id="DATA-NO-FABRICATION-001",
                severity="C3",
            )
        ]
    )
    observation = base_observation()
    observation["answer"]["text"] = "This trade has a guaranteed return."

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert result.trial_status == TrialStatus.HARNESS_FAILED
    assert result.task_pass is None
    assert result.task_score is None
    assert "DATA-NO-FABRICATION-001" in (result.failure_reason or "")


def test_c0_c1_and_uncertain_judge_outcomes_raise_human_review_flags(
    policy_registry: PolicyRegistry,
) -> None:
    case = make_case(
        required_assertions=[
            AssertionSpec(
                assertion_id="judge-supported",
                source="judge",
                operator="equals",
                path="verdict",
                expected="supported",
            ),
            AssertionSpec(
                assertion_id="explicit-confirmation",
                source="answer",
                operator="contains",
                path="text",
                expected="explicit confirmation",
                policy_id="TRADE-EXPLICIT-APPROVAL-001",
                severity="C0",
            ),
        ]
    )
    observation = base_observation()
    observation["judge"]["verdict"] = "uncertain"

    result = evaluate_trial(
        case,
        observation=observation,
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    assert {flag.reason for flag in result.human_review_flags} == {"C0", "judge_uncertain"}


def test_capability_batch_release_gate_depends_on_validity_not_task_success(
    policy_registry: PolicyRegistry,
) -> None:
    failing_trial = evaluate_trial(
        make_case(
            required_assertions=[
                AssertionSpec(
                    assertion_id="must-mention-risk",
                    source="answer",
                    operator="contains",
                    path="text",
                    expected="risk",
                )
            ]
        ),
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )
    passing_trial = evaluate_trial(
        make_case(
            required_assertions=[
                AssertionSpec(
                    assertion_id="must-mention-current-state",
                    source="answer",
                    operator="contains",
                    path="text",
                    expected="current state",
                )
            ]
        ),
        observation=base_observation(),
        policy_registry=policy_registry,
        policy_as_of=date(2026, 7, 27),
    )

    batch = summarize_batch([failing_trial, passing_trial])

    assert batch.valid_trial_rate == 1.0
    assert batch.release_eligible is True
    assert batch.task_pass_rate == 0.5
