from __future__ import annotations

from typing import Any

import pytest
from eval.chatloop.business_pipeline import InvalidEvidenceError
from eval.chatloop.business_runner import BusinessObservation, BusinessTrialResult
from eval.chatloop.case_schema import (
    AssertionSpec,
    ConversationCase,
    EnvironmentInput,
    EvidenceRequirements,
    ScoreComponent,
    SuiteType,
)
from eval.chatloop.judge_calibration import (
    CalibrationLabel,
    JudgeCalibrationGate,
    JudgeCalibrationItem,
    JudgeNotCalibratedError,
)
from eval.chatloop.structured_evidence import (
    BusinessStructuredEvidenceProvider,
    LLMSemanticEvidenceJudge,
    SemanticDecision,
    SemanticJudgeBatch,
)


def _case(assertions: list[AssertionSpec]) -> ConversationCase:
    return ConversationCase.model_construct(
        schema_version=1,
        case_id="B1-99",
        title_zh="evidence test",
        task_type="T1",
        suite_type=SuiteType.CAPABILITY,
        risk_level="test",
        user_goal="test",
        user_messages=["question"],
        initial_state=EnvironmentInput.model_construct(
            execution_mode="direct", actors={}, axes={}, business_state={}
        ),
        hidden_facts={"truth": "known"},
        available_tools=[],
        fault_injection=[],
        applicable_policies=[],
        acceptable_outcomes=[],
        required_assertions=assertions,
        forbidden_outcomes=[],
        expected_state_changes=[],
        answer_requirements=[],
        allowed_variations=[],
        graders=[],
        partial_credit=[ScoreComponent(name_zh="all", points=100, assertion_ids=[])],
        violation_caps={},
        trial_count=1,
        trial_status=None,
        task_pass=None,
        task_score=None,
        failure_reason=None,
        evidence=EvidenceRequirements(
            transcript=True,
            tool_ledger=True,
            database_before_after=True,
            versions=True,
            cost_latency=True,
        ),
    )


def _result(*, ledger: tuple[dict[str, Any], ...] | None = None) -> BusinessTrialResult:
    return BusinessTrialResult(
        case_id="B1-99",
        trial_index=0,
        trial_status="valid",
        failure_reason=None,
        observation=BusinessObservation(
            transcript=(
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "clear answer"},
            ),
            tool_ledger=ledger
            or (
                {
                    "tool_name": "get_market_quote",
                    "arguments": {"ts_code": "000001.SZ"},
                    "result": {"price": 10.2},
                    "error": None,
                    "idempotency_key": "call-1",
                },
            ),
            run_state={"status": "completed"},
            evidence={"quote": {"price": 10.2}},
            cost_cny=0.3,
            total_tokens=50,
        ),
        database_before_after={
            "before": {"orders": {"count": 0}},
            "after": {"orders": {"count": 0}},
        },
        environment_manifest={"database": "isolated"},
        duration_ms=12,
    )


class FakeJudge:
    def __init__(self, decisions: list[SemanticDecision]) -> None:
        self.decisions = decisions
        self.calls: list[tuple[str, ...]] = []

    async def judge(self, *, case, result, assertions):
        del case, result
        self.calls.append(tuple(item.assertion_id for item in assertions))
        return self.decisions


@pytest.mark.asyncio
async def test_deterministic_projection_builds_answer_tool_run_and_database_sources() -> None:
    assertions = [
        AssertionSpec(
            assertion_id="run-status",
            source="run",
            operator="equals",
            path="status",
            expected="completed",
        ),
        AssertionSpec(
            assertion_id="tool-order",
            source="tools",
            operator="ordered_subsequence",
            path="called",
            expected=["get_market_quote"],
        ),
        AssertionSpec(
            assertion_id="answer-text",
            source="answer",
            operator="contains",
            path="text",
            expected="clear",
        ),
        AssertionSpec(
            assertion_id="db-stable",
            source="database",
            operator="unchanged",
            path="orders",
        ),
    ]
    judge = FakeJudge([])
    provider = BusinessStructuredEvidenceProvider(
        versions={"model": "fake", "policy": "v1"}, semantic_judge=judge
    )

    evidence = await provider.build(_case(assertions), _result())

    assert judge.calls == []
    assert evidence["run"]["status"] == "completed"
    assert evidence["run"]["transcript"][1]["content"] == "clear answer"
    assert evidence["answer"] == {"text": "clear answer", "final_text": "clear answer"}
    assert evidence["tools"]["called"] == ["get_market_quote"]
    assert evidence["tools"]["get_market_quote"]["attempt_count"] == 1
    assert evidence["tools"]["get_market_quote"]["last_call"]["arguments"] == {
        "ts_code": "000001.SZ"
    }
    assert evidence["database"]["before"] == {"orders": {"count": 0}}
    assert evidence["evidence"]["versions"] == {"model": "fake", "policy": "v1"}


@pytest.mark.asyncio
async def test_semantic_judge_populates_only_judge_paths_with_audit() -> None:
    assertions = [
        AssertionSpec(
            assertion_id="quality",
            source="judge",
            operator="equals",
            path="rubric.clear",
            expected="pass",
        ),
    ]
    judge = FakeJudge(
        [
            SemanticDecision(
                assertion_id="quality",
                condition_met=False,
                rationale="too vague",
                evidence_quote="clear answer",
            ),
        ]
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=judge)

    evidence = await provider.build(_case(assertions), _result())

    assert judge.calls == [("quality",)]
    assert evidence["judge"]["rubric"]["clear"] != "pass"
    assert [row["assertion_id"] for row in evidence["judge_audit"]] == ["quality"]


@pytest.mark.asyncio
async def test_missing_answer_or_evidence_path_is_invalid_not_judge_synthesized() -> None:
    assertions = [
        AssertionSpec(
            assertion_id="rule",
            source="evidence",
            operator="equals",
            path="business_rules.safe.satisfied",
            expected=True,
        ),
        AssertionSpec(
            assertion_id="claim",
            source="answer",
            operator="equals",
            path="claims.safe",
            expected=True,
        ),
    ]
    judge = FakeJudge(
        [
            SemanticDecision(
                assertion_id="rule",
                condition_met=True,
                rationale="would have synthesized expected evidence",
                evidence_quote="clear answer",
            )
        ]
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=judge)

    with pytest.raises(InvalidEvidenceError, match="missing deterministic evidence"):
        await provider.build(_case(assertions), _result())

    assert judge.calls == []


@pytest.mark.asyncio
async def test_uncertain_semantic_decision_fails_assertion_and_preserves_review_marker() -> None:
    assertion = AssertionSpec(
        assertion_id="rule",
        source="judge",
        operator="equals",
        path="rubric.safe",
        expected="pass",
    )
    judge = FakeJudge(
        [
            SemanticDecision(
                assertion_id="rule",
                condition_met=None,
                review_reason="judge_uncertain",
                rationale="the transcript is ambiguous",
                evidence_quote="clear answer",
            )
        ]
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=judge)

    evidence = await provider.build(_case([assertion]), _result())

    assert evidence["judge"]["rubric"]["safe"] == "uncertain"
    assert evidence["judge_audit"][0]["review_reason"] == "judge_uncertain"


@pytest.mark.asyncio
async def test_missing_or_duplicate_judge_decisions_are_invalid_evidence() -> None:
    assertion = AssertionSpec(
        assertion_id="rule",
        source="judge",
        operator="equals",
        path="rubric.safe",
        expected="pass",
    )
    provider = BusinessStructuredEvidenceProvider(
        versions={"model": "fake"}, semantic_judge=FakeJudge([])
    )

    with pytest.raises(InvalidEvidenceError, match="semantic judge decisions"):
        await provider.build(_case([assertion]), _result())


class FakeLLM:
    def __init__(self, batch: SemanticJudgeBatch) -> None:
        self.batch = batch
        self.calls: list[dict[str, Any]] = []

    def chat(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, **kwargs})
        return type("Response", (), {"parsed": self.batch})()


def _calibrated_gate() -> JudgeCalibrationGate:
    return JudgeCalibrationGate.from_items(
        tuple(
            JudgeCalibrationItem(
                id=f"sample-{index}",
                human_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                judge_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                judge_model="fake",
                judge_prompt_sha256="a" * 64,
                rubric_version="business-semantic-v1",
            )
            for index in range(30)
        )
    )


@pytest.mark.asyncio
async def test_llm_judge_uses_structured_schema_and_verifies_quote() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    llm = FakeLLM(
        SemanticJudgeBatch(
            decisions=[
                SemanticDecision(
                    assertion_id="quality",
                    condition_met=True,
                    rationale="answer is direct",
                    evidence_quote="clear answer",
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(llm=llm, calibration_gate=_calibrated_gate())

    decisions = await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert decisions[0].condition_met is True
    assert llm.calls[0]["schema"] is SemanticJudgeBatch
    assert llm.calls[0]["tier"] == "balanced"
    assert "quality" in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_llm_judge_rejects_fabricated_evidence_quote() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    judge = LLMSemanticEvidenceJudge(
        llm=FakeLLM(
            SemanticJudgeBatch(
                decisions=[
                    SemanticDecision(
                        assertion_id="quality",
                        condition_met=True,
                        rationale="unsupported",
                        evidence_quote="this text never appeared",
                    )
                ]
            )
        ),
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="quote is not present"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


@pytest.mark.asyncio
async def test_llm_judge_fails_closed_before_model_call_when_uncalibrated() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    llm = FakeLLM(SemanticJudgeBatch(decisions=[]))
    gate = JudgeCalibrationGate.from_items(())
    judge = LLMSemanticEvidenceJudge(llm=llm, calibration_gate=gate)

    with pytest.raises(JudgeNotCalibratedError, match="not calibrated"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert llm.calls == []
