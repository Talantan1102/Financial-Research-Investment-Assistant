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
    SEMANTIC_JUDGE_PROMPT_SHA256,
    SEMANTIC_JUDGE_RUBRIC_VERSION,
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


def _result(
    *,
    ledger: tuple[dict[str, Any], ...] | None = None,
    assistant_text: str = "clear answer",
) -> BusinessTrialResult:
    return BusinessTrialResult(
        case_id="B1-99",
        trial_index=0,
        trial_status="valid",
        failure_reason=None,
        observation=BusinessObservation(
            transcript=(
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": assistant_text},
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
                evidence_path="transcript.1.content",
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
                evidence_path="transcript.1.content",
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
                evidence_path="transcript.1.content",
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
    def __init__(self, batch: SemanticJudgeBatch, *, response_model: str | None = "fake") -> None:
        self.batch = batch
        self.response_model = response_model
        self.calls: list[dict[str, Any]] = []

    def chat(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, **kwargs})
        return type("Response", (), {"parsed": self.batch, "model": self.response_model})()


def _calibrated_gate(*, judge_model: str = "fake") -> JudgeCalibrationGate:
    identity = {
        "judge_model": judge_model,
        "judge_prompt_sha256": SEMANTIC_JUDGE_PROMPT_SHA256,
        "rubric_version": SEMANTIC_JUDGE_RUBRIC_VERSION,
    }
    return JudgeCalibrationGate.from_items(
        tuple(
            JudgeCalibrationItem(
                id=f"sample-{index}",
                human_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                judge_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                **identity,
            )
            for index in range(30)
        ),
        expected_identity=identity,
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
                    evidence_path="transcript.1.content",
                    evidence_quote="clear answer",
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    decisions = await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert decisions[0].condition_met is True
    assert llm.calls[0]["schema"] is SemanticJudgeBatch
    assert llm.calls[0]["tier"] == "balanced"
    assert llm.calls[0]["model"] == "fake"
    assert "quality" in llm.calls[0]["prompt"]
    assert "reference_context" in llm.calls[0]["prompt"]
    assert "observed_evidence" in llm.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_llm_judge_rejects_quote_found_only_in_hidden_facts() -> None:
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
                        rationale="copied reference data",
                        evidence_path="hidden_facts.truth",
                        evidence_quote="known",
                    )
                ]
            )
        ),
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="observed evidence"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


@pytest.mark.asyncio
async def test_llm_judge_rejects_quote_found_only_in_assertion_expected() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="expected-only-token",
    )
    judge = LLMSemanticEvidenceJudge(
        llm=FakeLLM(
            SemanticJudgeBatch(
                decisions=[
                    SemanticDecision(
                        assertion_id="quality",
                        condition_met=True,
                        rationale="copied assertion criteria",
                        evidence_path="assertion_criteria.0.expected",
                        evidence_quote="expected-only-token",
                    )
                ]
            )
        ),
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="observed evidence"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


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
                        evidence_path="transcript.1.content",
                        evidence_quote="this text never appeared",
                    )
                ]
            )
        ),
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="quote is not present"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


@pytest.mark.asyncio
async def test_llm_judge_rejects_json_structure_character_as_quote() -> None:
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
                    rationale="JSON punctuation is not source evidence",
                    evidence_path="transcript.1.content",
                    evidence_quote=":",
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="quote is not present"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


@pytest.mark.asyncio
async def test_llm_judge_rejects_wrong_evidence_path() -> None:
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
                    rationale="path does not exist",
                    evidence_path="transcript.9.content",
                    evidence_quote="clear answer",
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="evidence path"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])


@pytest.mark.asyncio
async def test_llm_judge_accepts_quote_with_real_quotes_and_backslash() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    assistant_text = 'Use "quoted" evidence from C:\\temp'
    llm = FakeLLM(
        SemanticJudgeBatch(
            decisions=[
                SemanticDecision(
                    assertion_id="quality",
                    condition_met=True,
                    rationale="verbatim source text",
                    evidence_path="transcript.1.content",
                    evidence_quote='"quoted" evidence from C:\\temp',
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    decisions = await judge.judge(
        case=_case([assertion]),
        result=_result(assistant_text=assistant_text),
        assertions=[assertion],
    )

    assert decisions[0].evidence_path == "transcript.1.content"


@pytest.mark.asyncio
async def test_llm_judge_rejects_quote_visible_only_after_json_escaping() -> None:
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
                    rationale="copied JSON encoding",
                    evidence_path="transcript.1.content",
                    evidence_quote='\\"quoted\\"',
                )
            ]
        )
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="quote is not present"):
        await judge.judge(
            case=_case([assertion]),
            result=_result(assistant_text='Use "quoted" evidence'),
            assertions=[assertion],
        )


@pytest.mark.asyncio
async def test_llm_judge_rejects_requested_model_not_bound_to_calibration() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    llm = FakeLLM(SemanticJudgeBatch(decisions=[]), response_model="requested-model")
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="requested-model",
        calibration_gate=_calibrated_gate(judge_model="calibrated-model"),
    )

    with pytest.raises(JudgeNotCalibratedError, match="judge model"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("response_model", [None, "other-model"])
async def test_llm_judge_rejects_missing_or_mismatched_response_model(
    response_model: str | None,
) -> None:
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
                    rationale="response came from the wrong model",
                    evidence_path="transcript.1.content",
                    evidence_quote="clear answer",
                )
            ]
        ),
        response_model=response_model,
    )
    judge = LLMSemanticEvidenceJudge(
        llm=llm,
        judge_model="fake",
        calibration_gate=_calibrated_gate(),
    )

    with pytest.raises(InvalidEvidenceError, match="response model"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert llm.calls[0]["model"] == "fake"


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
    judge = LLMSemanticEvidenceJudge(llm=llm, judge_model="fake", calibration_gate=gate)

    with pytest.raises(JudgeNotCalibratedError, match="not calibrated"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert llm.calls == []


@pytest.mark.asyncio
async def test_llm_judge_rejects_calibrated_old_prompt_without_expected_identity() -> None:
    assertion = AssertionSpec(
        assertion_id="quality",
        source="judge",
        operator="equals",
        path="rubric.clear",
        expected="pass",
    )
    old_prompt_sha256 = "a" * 64
    assert old_prompt_sha256 != SEMANTIC_JUDGE_PROMPT_SHA256
    gate = JudgeCalibrationGate.from_items(
        tuple(
            JudgeCalibrationItem(
                id=f"old-prompt-{index}",
                human_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                judge_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
                judge_model="fake",
                judge_prompt_sha256=old_prompt_sha256,
                rubric_version=SEMANTIC_JUDGE_RUBRIC_VERSION,
            )
            for index in range(30)
        )
    )
    assert gate.calibrated is True
    assert gate.expected_identity is None
    llm = FakeLLM(SemanticJudgeBatch(decisions=[]))
    judge = LLMSemanticEvidenceJudge(llm=llm, judge_model="fake", calibration_gate=gate)

    with pytest.raises(JudgeNotCalibratedError, match="expected identity"):
        await judge.judge(case=_case([assertion]), result=_result(), assertions=[assertion])

    assert llm.calls == []
