from __future__ import annotations

from typing import Any

import pytest
from eval.chatloop.business_pipeline import InvalidEvidenceError
from eval.chatloop.business_runner import BusinessObservation, BusinessTrialResult
from eval.chatloop.case_loader import load_catalog
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
from eval.chatloop.policy_registry import PolicyRegistry
from eval.chatloop.structured_evidence import (
    SEMANTIC_JUDGE_PROMPT_SHA256,
    SEMANTIC_JUDGE_RUBRIC_VERSION,
    BusinessStructuredEvidenceProvider,
    LLMSemanticEvidenceJudge,
    SemanticDecision,
    SemanticJudgeBatch,
)
from eval.chatloop.trial_evaluator import TrialStatus, evaluate_trial


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
    raw_evidence: dict[str, Any] | None = None,
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
            tool_ledger=(
                ledger
                if ledger is not None
                else (
                    {
                        "tool_name": "get_market_quote",
                        "arguments": {"ts_code": "000001.SZ"},
                        "result": {"price": 10.2},
                        "error": None,
                        "idempotency_key": "call-1",
                    },
                )
            ),
            run_state={"status": "completed"},
            evidence=raw_evidence if raw_evidence is not None else {"quote": {"price": 10.2}},
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


def _successful_quote_ledger(
    *,
    trade_date: str = "20260724",
    requested_at: str = "2026-07-27T10:00:00+08:00",
    fault_injected: bool = False,
) -> tuple[dict[str, Any], ...]:
    return (
        {
            "tool_name": "lookup_ts_code",
            "arguments": {"name": "中际旭创"},
            "result": {"name": "中际旭创", "ts_code": "300308.SZ"},
            "error": None,
            "idempotency_key": "lookup-1",
        },
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {
                "ts_code": "300308.SZ",
                "price": 135.2,
                "change_pct": 2.1,
                "volume": 123456.0,
                "trade_date": trade_date,
                "requested_at": requested_at,
            },
            "error": None,
            "idempotency_key": "quote-1",
            **(
                {
                    "fault_injection": {
                        "injected": True,
                        "mode": "stale",
                        "target": "get_stock_quote",
                    }
                }
                if fault_injected
                else {}
            ),
        },
    )


@pytest.mark.asyncio
async def test_projects_quote_facts_and_field_provenance_from_successful_tool_ledger() -> None:
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(_case([]), _result(ledger=_successful_quote_ledger()))

    assert evidence["evidence"]["entity"]["ts_code"] == "300308.SZ"
    assert evidence["evidence"]["quote"] == {
        "ts_code": "300308.SZ",
        "price": 135.2,
        "change_pct": 2.1,
        "volume": 123456.0,
        "trade_date": "2026-07-24",
        "requested_at": "2026-07-27T10:00:00+08:00",
    }
    assert evidence["evidence"]["provenance"]["entity.ts_code"] == {
        "tool_name": "lookup_ts_code",
        "call_index": 0,
        "result_path": "result.ts_code",
    }
    assert evidence["evidence"]["provenance"]["quote.price"] == {
        "tool_name": "get_stock_quote",
        "call_index": 1,
        "result_path": "result.price",
    }
    assert evidence["evidence"]["provenance"]["quote.trade_date"]["call_index"] == 1


@pytest.mark.asyncio
async def test_projects_complete_stale_quote_payload_without_semantic_conclusions() -> None:
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(
        _case([]),
        _result(
            ledger=_successful_quote_ledger(
                trade_date="2026-07-24",
                requested_at="2026-07-27T10:20:00+08:00",
                fault_injected=True,
            )
        ),
    )

    assert evidence["evidence"]["quote"]["trade_date"] == "2026-07-24"
    assert evidence["evidence"]["quote"]["requested_at"] == "2026-07-27T10:20:00+08:00"
    assert "business_rules" not in evidence["evidence"]
    assert "claims" not in evidence["answer"]
    assert evidence["evidence"]["provenance"]["quote.trade_date"]["fault_injection"] == {
        "injected": True,
        "mode": "stale",
        "target": "get_stock_quote",
    }
    assert evidence["tools"]["get_stock_quote"]["last_call"]["fault_injection"]["mode"] == ("stale")


@pytest.mark.asyncio
async def test_failed_calls_and_missing_quote_fields_do_not_fabricate_facts() -> None:
    ledger = (
        {
            "tool_name": "lookup_ts_code",
            "arguments": {"name": "中际旭创"},
            "result": {"ts_code": "SHOULD-NOT-APPEAR"},
            "error": "lookup failed",
        },
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {"price": 999.0, "trade_date": "20260724"},
            "error": "quote failed",
        },
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {"price": 135.2},
            "error": None,
        },
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(_case([]), _result(ledger=ledger, raw_evidence={}))

    assert "entity" not in evidence["evidence"]
    assert evidence["evidence"]["quote"] == {"price": 135.2}
    assert "trade_date" not in evidence["evidence"]["quote"]
    assert "quote.trade_date" not in evidence["evidence"]["provenance"]


@pytest.mark.asyncio
async def test_quote_projection_ignores_undeclared_tool_metadata() -> None:
    ledger = list(_successful_quote_ledger())
    ledger[1]["result"]["internal_cache_key"] = "20260724"
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(_case([]), _result(ledger=tuple(ledger)))

    assert "internal_cache_key" not in evidence["evidence"]["quote"]
    assert "quote.internal_cache_key" not in evidence["evidence"]["provenance"]


@pytest.mark.asyncio
async def test_tool_ledger_quote_facts_replace_raw_quote_but_preserve_unrelated_raw_fields() -> (
    None
):
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(
        _case([]),
        _result(
            ledger=_successful_quote_ledger(),
            raw_evidence={
                "entity": {"ts_code": "RAW.CODE", "display_name": "保留名称"},
                "quote": {"price": 999.0, "analyst_note": "保留原始备注"},
                "provenance": {"quote.price": {"tool_name": "raw"}},
                "unrelated": {"keep": True},
            },
        ),
    )

    assert evidence["evidence"]["entity"] == {
        "ts_code": "300308.SZ",
        "display_name": "保留名称",
    }
    assert evidence["evidence"]["quote"] == {
        "ts_code": "300308.SZ",
        "price": 135.2,
        "change_pct": 2.1,
        "volume": 123456.0,
        "trade_date": "2026-07-24",
        "requested_at": "2026-07-27T10:00:00+08:00",
    }
    assert evidence["evidence"]["unrelated"] == {"keep": True}
    assert evidence["evidence"]["provenance"]["quote.price"]["tool_name"] == "get_stock_quote"


@pytest.mark.asyncio
async def test_raw_quote_field_is_removed_when_tool_ledger_did_not_return_it() -> None:
    ledger = (
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {"price": 135.2},
            "error": None,
        },
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(
        _case([]),
        _result(
            ledger=ledger,
            raw_evidence={
                "quote": {"trade_date": "2026-07-24"},
                "provenance": {"quote.trade_date": {"tool_name": "raw"}},
            },
        ),
    )

    assert evidence["evidence"]["quote"] == {"price": 135.2}
    assert "quote.trade_date" not in evidence["evidence"].get("provenance", {})


@pytest.mark.asyncio
async def test_non_stock_quote_case_preserves_unrelated_raw_quote_namespace() -> None:
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(
        _case([]),
        _result(raw_evidence={"quote": {"document_excerpt": "quoted research text"}}),
    )

    assert evidence["evidence"]["quote"] == {"document_excerpt": "quoted research text"}


@pytest.mark.asyncio
async def test_last_successful_quote_call_wins_with_matching_provenance() -> None:
    ledger = (
        *_successful_quote_ledger(),
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {
                "ts_code": "300308.SZ",
                "price": 136.8,
                "change_pct": 3.3,
                "trade_date": "20260725",
            },
            "error": None,
            "idempotency_key": "quote-2",
        },
        {
            "tool_name": "get_stock_quote",
            "arguments": {"ts_code": "300308.SZ"},
            "result": {"price": 500.0},
            "error": "late failure",
            "idempotency_key": "quote-3",
        },
    )
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(_case([]), _result(ledger=ledger))

    assert evidence["evidence"]["quote"]["price"] == 136.8
    assert evidence["evidence"]["quote"]["trade_date"] == "2026-07-25"
    assert evidence["evidence"]["provenance"]["quote.price"]["call_index"] == 2
    assert evidence["evidence"]["provenance"]["quote.trade_date"]["call_index"] == 2


@pytest.mark.asyncio
async def test_conflicting_lookup_and_quote_entities_are_invalid_evidence() -> None:
    ledger = list(_successful_quote_ledger())
    ledger[1]["result"]["ts_code"] = "000001.SZ"
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    with pytest.raises(InvalidEvidenceError, match="conflicting ts_code"):
        await provider.build(_case([]), _result(ledger=tuple(ledger)))


@pytest.mark.asyncio
async def test_only_declared_date_fields_are_normalized() -> None:
    ledger = list(_successful_quote_ledger())
    ledger[1]["result"]["data_mode"] = "20260724"
    provider = BusinessStructuredEvidenceProvider(versions={"model": "fake"}, semantic_judge=None)

    evidence = await provider.build(_case([]), _result(ledger=tuple(ledger)))

    assert evidence["evidence"]["quote"]["trade_date"] == "2026-07-24"
    assert evidence["evidence"]["quote"]["data_mode"] == "20260724"
    assert "normalization" not in evidence["evidence"]["provenance"]["quote.data_mode"]


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


def _catalog_result(
    case_id: str,
    *,
    assistant_text: str,
    ledger: tuple[dict[str, Any], ...],
) -> BusinessTrialResult:
    unchanged = {
        "orders": {"count": 0},
        "watchlist": {"codes": []},
        "memory": {"records": []},
    }
    return BusinessTrialResult(
        case_id=case_id,
        trial_index=0,
        trial_status="valid",
        failure_reason=None,
        observation=BusinessObservation(
            transcript=(
                {"role": "user", "content": "catalog question"},
                {"role": "assistant", "content": assistant_text},
            ),
            tool_ledger=ledger,
            run_state={"status": "completed"},
            evidence={"execution_path": "direct"},
            cost_cny=0.01,
            total_tokens=100,
        ),
        database_before_after={"before": unchanged, "after": unchanged},
        environment_manifest={"database": "isolated"},
        duration_ms=10,
    )


def _passing_judge_for_case(case: ConversationCase, assistant_text: str) -> FakeJudge:
    forbidden_ids = {item.assertion_id for item in case.forbidden_outcomes}
    assertions = [
        *case.required_assertions,
        *case.forbidden_outcomes,
        *case.expected_state_changes,
        *[item for outcome in case.acceptable_outcomes for item in outcome.assertions],
    ]
    return FakeJudge(
        [
            SemanticDecision(
                assertion_id=item.assertion_id,
                condition_met=item.assertion_id not in forbidden_ids,
                rationale="supported by the recorded answer and tool ledger",
                evidence_path="transcript.1.content",
                evidence_quote=assistant_text,
            )
            for item in assertions
            if item.source == "judge"
        ]
    )


@pytest.mark.asyncio
async def test_b1_14_catalog_builds_from_real_quote_ledger_without_synthetic_verdicts() -> None:
    case = load_catalog().by_id("B1-14")
    answer = "只能确认2026-07-24收盘价135.20元、涨2.10%，不是当前盘中价。"
    result = _catalog_result(
        case.case_id,
        assistant_text=answer,
        ledger=_successful_quote_ledger(requested_at="2026-07-27T10:20:00+08:00"),
    )
    provider = BusinessStructuredEvidenceProvider(
        versions={"model": "fake"},
        semantic_judge=_passing_judge_for_case(case, answer),
    )

    evidence = await provider.build(case, result)

    assert evidence["evidence"]["entity"]["ts_code"] == "300308.SZ"
    assert evidence["evidence"]["quote"]["trade_date"] == "2026-07-24"
    assert "business_rules" not in evidence["evidence"]
    assert len(evidence["judge_audit"]) == 8


@pytest.mark.asyncio
async def test_b2_10_catalog_reads_stale_inputs_from_real_tool_ledger() -> None:
    case = load_catalog().by_id("B2-10")
    answer = (
        "工具只返回截止日后发布的年报和2026年估值，不能据此给出入选或回测结论。"
        "需要补齐截至2024-06-30已披露的财报、当时的历史PE和后续行情，再按同一规则复算。"
    )
    result = _catalog_result(
        case.case_id,
        assistant_text=answer,
        ledger=(
            {
                "tool_name": "get_financial_statements",
                "arguments": {
                    "ts_code": "600519.SH",
                    "statement": "income",
                    "end_date": "20231231",
                },
                "result": {
                    "ts_code": "600519.SH",
                    "report_period": "2024-12-31",
                    "published_at": "2025-03-31",
                    "roe": 31.0,
                },
                "error": None,
                "idempotency_key": "financial-1",
            },
            {
                "tool_name": "get_market_indicators",
                "arguments": {
                    "ts_code": "600519.SH",
                    "metric": "daily_basic",
                    "trade_date": "20240628",
                },
                "result": {
                    "ts_code": "600519.SH",
                    "metric": "daily_basic",
                    "trade_date": "2026-06-30",
                    "pe": 24.5,
                },
                "error": None,
                "idempotency_key": "valuation-1",
            },
        ),
    )
    provider = BusinessStructuredEvidenceProvider(
        versions={"model": "fake"},
        semantic_judge=_passing_judge_for_case(case, answer),
    )

    evidence = await provider.build(case, result)

    assert (
        evidence["tools"]["get_financial_statements"]["last_call"]["result"]["published_at"]
        == "2025-03-31"
    )
    assert (
        evidence["tools"]["get_market_indicators"]["last_call"]["result"]["trade_date"]
        == "2026-06-30"
    )
    assert "business_rules" not in evidence["evidence"]
    assert len(evidence["judge_audit"]) == 14


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", ["B1-14", "B2-10"])
async def test_missing_required_tool_call_is_valid_task_failure_not_invalid_evidence(
    case_id: str,
) -> None:
    catalog = load_catalog()
    case = catalog.by_id(case_id)
    answer = "我没有拿到足够的数据，暂时不能给出结论。"
    result = _catalog_result(case_id, assistant_text=answer, ledger=())
    provider = BusinessStructuredEvidenceProvider(
        versions={"model": "fake"},
        semantic_judge=_passing_judge_for_case(case, answer),
    )

    evidence = await provider.build(case, result)
    evaluation = evaluate_trial(
        case,
        observation=evidence,
        policy_registry=PolicyRegistry.default(),
        policy_as_of=catalog.policy_as_of,
        policy_version=catalog.policy_version,
    )

    assert evidence["tools"]["called"] == []
    assert evaluation.trial_status is TrialStatus.VALID
    assert evaluation.task_pass is False
    assert any(
        item.passed is False
        for item in evaluation.required_results
        if item.assertion_id.startswith(f"{case_id}-tool-")
    )
