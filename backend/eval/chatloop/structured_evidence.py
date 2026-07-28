"""Deterministic evidence projection plus auditable semantic-judge decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from eval.chatloop.business_pipeline import InvalidEvidenceError
from eval.chatloop.business_runner import BusinessTrialResult
from eval.chatloop.case_schema import AssertionSpec, ConversationCase
from eval.chatloop.judge_calibration import JudgeCalibrationGate

_BUSINESS_WRITE_TOOLS = frozenset(
    {
        "manage_watchlist",
        "place_paper_order",
        "cancel_paper_order",
        "reset_paper_account",
        "memory_write",
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
    }
)
_ORDER_WRITE_TOOLS = frozenset({"place_paper_order", "cancel_paper_order", "reset_paper_account"})
SEMANTIC_JUDGE_RUBRIC_VERSION = "business-semantic-v1"
_SEMANTIC_JUDGE_INSTRUCTIONS = (
    "你是金融对话评估裁判。只判断 judge 来源的主观质量断言，不能生成业务事实。"
    "condition_met 表示断言是否由证据支持。禁止结果如果真实出现，也应填 true。"
    "每条必须给出 evidence_quote，且原文必须出现在证据 JSON 中。"
    "证据不足或冲突时 condition_met 填 null，并分别使用 judge_uncertain 或 judge_conflict。"
)
SEMANTIC_JUDGE_PROMPT_SHA256 = hashlib.sha256(
    _SEMANTIC_JUDGE_INSTRUCTIONS.encode("utf-8")
).hexdigest()


class SemanticDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertion_id: str
    condition_met: StrictBool | None
    review_reason: Literal["judge_uncertain", "judge_conflict"] | None = None
    rationale: str
    evidence_quote: str

    @model_validator(mode="after")
    def validate_decision_or_review(self) -> SemanticDecision:
        if (self.condition_met is None) != (self.review_reason is not None):
            raise ValueError(
                "semantic decisions require condition_met for decided results "
                "or review_reason for uncertain/conflicting results"
            )
        return self


class SemanticJudgeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[SemanticDecision]


class SemanticEvidenceJudge(Protocol):
    async def judge(
        self,
        *,
        case: ConversationCase,
        result: BusinessTrialResult,
        assertions: Sequence[AssertionSpec],
    ) -> Sequence[SemanticDecision]: ...


class LLMSemanticEvidenceJudge:
    """One structured model call whose decisions retain source-grounded quotes."""

    def __init__(self, *, llm: Any, calibration_gate: JudgeCalibrationGate) -> None:
        self._llm = llm
        self._calibration_gate = calibration_gate

    async def judge(
        self,
        *,
        case: ConversationCase,
        result: BusinessTrialResult,
        assertions: Sequence[AssertionSpec],
    ) -> Sequence[SemanticDecision]:
        self._calibration_gate.require_calibrated()
        raw = result.observation
        if raw is None:
            raise InvalidEvidenceError("semantic judge received no observation")
        evidence = {
            "hidden_facts": case.hidden_facts,
            "answer_requirements": case.answer_requirements,
            "allowed_variations": case.allowed_variations,
            "transcript": list(raw.transcript),
            "tool_ledger": list(raw.tool_ledger),
            "database_before_after": result.database_before_after,
            "raw_evidence": raw.evidence,
        }
        evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
        assertion_json = json.dumps(
            [item.model_dump(mode="json") for item in assertions],
            ensure_ascii=False,
            sort_keys=True,
        )
        prompt = (
            "你是金融对话评估裁判。逐条判断断言描述的条件是否在证据中成立。"
            "condition_met 表示断言本身是否成立，不表示这个行为是否值得鼓励；"
            "禁用结果如果实际出现，也应填 true。不得补造事实。"
            "每条都必须给出 evidence_quote，且必须逐字出现在下方证据 JSON 中。\n"
            "如果证据不足或相互冲突，不得猜测：condition_met 填 null，并分别填 "
            "review_reason=judge_uncertain 或 judge_conflict。\n"
            f"case_id: {case.case_id}\n断言: {assertion_json}\n证据: {evidence_json}"
        )
        # The stable instruction block is the calibration identity. Dynamic case
        # evidence and assertions are appended but never allowed to change its policy.
        prompt = (
            f"{_SEMANTIC_JUDGE_INSTRUCTIONS}\n"
            f"case_id: {case.case_id}\n断言: {assertion_json}\n证据: {evidence_json}"
        )
        response = await asyncio.to_thread(
            self._llm.chat,
            prompt,
            tier="balanced",
            schema=SemanticJudgeBatch,
            request_id=f"eval-judge-{case.case_id}-{result.trial_index}",
        )
        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, SemanticJudgeBatch):
            raise InvalidEvidenceError("semantic judge did not return the required schema")
        for decision in parsed.decisions:
            if not decision.evidence_quote.strip():
                raise InvalidEvidenceError(
                    f"semantic judge returned an empty quote for {decision.assertion_id}"
                )
            if decision.evidence_quote not in evidence_json:
                raise InvalidEvidenceError(
                    f"semantic judge quote is not present in evidence for {decision.assertion_id}"
                )
        return tuple(parsed.decisions)


class BusinessStructuredEvidenceProvider:
    """Build every assertion source while keeping model judgments explicit."""

    def __init__(
        self,
        *,
        versions: Mapping[str, str],
        semantic_judge: SemanticEvidenceJudge | None,
    ) -> None:
        self._versions = dict(versions)
        self._semantic_judge = semantic_judge

    async def build(
        self,
        case: ConversationCase,
        result: BusinessTrialResult,
    ) -> Mapping[str, Any]:
        raw = result.observation
        if raw is None:
            raise InvalidEvidenceError("valid trial has no raw observation")
        answer_text = _last_assistant_text(raw.transcript)
        if answer_text is None:
            raise InvalidEvidenceError("transcript has no assistant answer")

        projected: dict[str, Any] = {
            "run": {**deepcopy(raw.run_state), "transcript": deepcopy(list(raw.transcript))},
            "tools": _project_tools(raw.tool_ledger),
            "database": deepcopy(result.database_before_after),
            "answer": {"text": answer_text, "final_text": answer_text},
            "evidence": {
                **deepcopy(raw.evidence),
                "versions": dict(self._versions),
                "cost_latency": {
                    "cost_cny": raw.cost_cny,
                    "total_tokens": raw.total_tokens,
                    "duration_ms": result.duration_ms,
                },
            },
            "judge": {},
        }

        semantic: list[AssertionSpec] = []
        for assertion in _all_assertions(case):
            if assertion.operator == "absent":
                continue
            if _assertion_evidence_exists(projected, assertion):
                continue
            if assertion.source == "judge":
                semantic.append(assertion)
                continue
            raise InvalidEvidenceError(
                f"missing deterministic evidence: {assertion.source}.{assertion.path} "
                f"for {assertion.assertion_id}"
            )

        audit: list[dict[str, Any]] = []
        if semantic:
            if self._semantic_judge is None:
                raise InvalidEvidenceError("semantic assertions require a configured judge")
            decisions = list(
                await self._semantic_judge.judge(
                    case=case,
                    result=result,
                    assertions=semantic,
                )
            )
            expected_ids = [item.assertion_id for item in semantic]
            actual_ids = [item.assertion_id for item in decisions]
            if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
                raise InvalidEvidenceError(
                    "semantic judge decisions must contain each requested assertion exactly once"
                )
            by_id = {item.assertion_id: item for item in decisions}
            for assertion in semantic:
                decision = by_id[assertion.assertion_id]
                _set_path(
                    projected[assertion.source],
                    assertion.path,
                    _actual_for_decision(assertion, decision),
                )
                audit.append(decision.model_dump(mode="json"))
        projected["judge_audit"] = audit
        return projected


def _all_assertions(case: ConversationCase) -> list[AssertionSpec]:
    return [
        *case.required_assertions,
        *case.forbidden_outcomes,
        *case.expected_state_changes,
        *[assertion for outcome in case.acceptable_outcomes for assertion in outcome.assertions],
    ]


def _last_assistant_text(transcript: Sequence[Mapping[str, Any]]) -> str | None:
    for message in reversed(transcript):
        if message.get("role") == "assistant" and isinstance(message.get("content"), str):
            return str(message["content"])
    return None


def _project_tools(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    names: list[str] = []
    permissions: dict[str, list[Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in ledger:
        name = str(row.get("tool_name") or "")
        if not name:
            raise InvalidEvidenceError("tool ledger contains an unnamed call")
        arguments = deepcopy(dict(row.get("arguments") or {}))
        call = {
            "tool_name": name,
            "name": name,
            "args": arguments,
            "arguments": deepcopy(arguments),
            "result": deepcopy(row.get("result")),
            "error": deepcopy(row.get("error")),
            "idempotency_key": deepcopy(row.get("idempotency_key")),
        }
        calls.append(call)
        names.append(name)
        grouped.setdefault(name, []).append(call)
        result = row.get("result")
        if isinstance(result, Mapping):
            values = result.get("permission_decisions")
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                permissions.setdefault(name, []).extend(deepcopy(list(values)))
            elif "permission_decision" in result:
                permissions.setdefault(name, []).append(deepcopy(result["permission_decision"]))

    projected: dict[str, Any] = {
        "calls": calls,
        "called": names,
        "call_sequence": list(names),
        "business_write_calls": [name for name in names if name in _BUSINESS_WRITE_TOOLS],
        "order_write_calls": [name for name in names if name in _ORDER_WRITE_TOOLS],
        "permission_decisions": permissions,
        "writes_from_cancelled_intent": [],
    }
    for name, rows in grouped.items():
        projected[name] = {
            "calls": rows,
            "attempt_count": len(rows),
            "last_call": rows[-1],
        }
    return projected


def _path_exists(root: Any, path: str) -> bool:
    if path == "":
        return root is not None
    current = root
    for segment in path.split("."):
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
            continue
        if (
            isinstance(current, Sequence)
            and not isinstance(current, (str, bytes, bytearray))
            and segment.isdigit()
            and int(segment) < len(current)
        ):
            current = current[int(segment)]
            continue
        return False
    return True


def _assertion_evidence_exists(projected: Mapping[str, Any], assertion: AssertionSpec) -> bool:
    source = projected.get(assertion.source)
    if assertion.operator != "unchanged":
        return _path_exists(source, assertion.path)
    return (
        isinstance(source, Mapping)
        and _path_exists(source.get("before"), assertion.path)
        and _path_exists(source.get("after"), assertion.path)
    )


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    if not path:
        raise InvalidEvidenceError("semantic assertions require a non-empty path")
    current = root
    parts = path.split(".")
    for segment in parts[:-1]:
        child = current.get(segment)
        if child is None:
            child = {}
            current[segment] = child
        if not isinstance(child, dict):
            raise InvalidEvidenceError(f"semantic path collides with evidence: {path}")
        current = child
    current[parts[-1]] = value


def _actual_for_decision(assertion: AssertionSpec, decision: SemanticDecision) -> Any:
    if decision.condition_met is None:
        if decision.review_reason == "judge_uncertain":
            return "uncertain"
        if decision.review_reason == "judge_conflict":
            return "judge_conflict"
        raise InvalidEvidenceError("semantic review decision has no review reason")
    condition_met = decision.condition_met
    expected = deepcopy(assertion.expected)
    if assertion.operator in {"equals", "contains", "exists"}:
        if condition_met:
            return expected if assertion.operator != "exists" else True
        if isinstance(expected, bool):
            return not expected
        return {"semantic_condition_met": False}
    if assertion.operator in {"not_equals", "not_contains"}:
        if condition_met:
            return {"semantic_condition_met": True}
        return expected
    raise InvalidEvidenceError(f"semantic judge does not support operator {assertion.operator!r}")


__all__ = [
    "BusinessStructuredEvidenceProvider",
    "LLMSemanticEvidenceJudge",
    "SEMANTIC_JUDGE_PROMPT_SHA256",
    "SEMANTIC_JUDGE_RUBRIC_VERSION",
    "SemanticDecision",
    "SemanticEvidenceJudge",
    "SemanticJudgeBatch",
]
