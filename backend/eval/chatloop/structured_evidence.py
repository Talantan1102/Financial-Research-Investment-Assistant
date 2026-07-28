"""Deterministic evidence projection plus auditable semantic-judge decisions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from eval.chatloop.business_pipeline import InvalidEvidenceError
from eval.chatloop.business_runner import BusinessTrialResult
from eval.chatloop.case_schema import AssertionSpec, ConversationCase
from eval.chatloop.judge_calibration import JudgeCalibrationGate, JudgeNotCalibratedError

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
_QUOTE_EVIDENCE_FIELDS = (
    "ts_code",
    "price",
    "change_pct",
    "volume",
    "trade_date",
    "requested_at",
    "data_mode",
    "source",
)
SEMANTIC_JUDGE_RUBRIC_VERSION = "business-semantic-v1"
_SEMANTIC_JUDGE_INSTRUCTIONS = (
    "你是金融对话评估裁判。只判断 judge 来源的主观质量断言，不能生成业务事实。"
    "condition_met 表示断言是否由证据支持。禁止结果如果真实出现，也应填 true。"
    "每条必须给出 evidence_quote，且原文必须出现在证据 JSON 中。"
    "证据不足或冲突时 condition_met 填 null，并分别使用 judge_uncertain 或 judge_conflict。"
)
_SEMANTIC_JUDGE_EVIDENCE_BOUNDARY_INSTRUCTIONS = (
    "The prompt has two explicitly separated sections: reference_context and "
    "observed_evidence. reference_context contains expected/reference material and "
    "must never be treated as proof. Every decision must provide a non-empty evidence_path "
    "to an original string leaf inside observed_evidence. Every evidence_quote must be "
    "non-empty and copied verbatim from that exact string leaf. JSON structure or escaping, "
    "and content found only in reference_context or assertion criteria, are invalid evidence."
)
_SEMANTIC_JUDGE_CALIBRATION_INSTRUCTIONS = (
    f"{_SEMANTIC_JUDGE_INSTRUCTIONS}\n{_SEMANTIC_JUDGE_EVIDENCE_BOUNDARY_INSTRUCTIONS}"
)
SEMANTIC_JUDGE_PROMPT_SHA256 = hashlib.sha256(
    _SEMANTIC_JUDGE_CALIBRATION_INSTRUCTIONS.encode("utf-8")
).hexdigest()


class SemanticDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertion_id: str
    condition_met: StrictBool | None
    review_reason: Literal["judge_uncertain", "judge_conflict"] | None = None
    rationale: str
    evidence_path: str
    evidence_quote: str

    @model_validator(mode="after")
    def validate_decision_or_review(self) -> SemanticDecision:
        if not self.evidence_path.strip():
            raise ValueError("semantic decisions require a non-empty evidence_path")
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

    def __init__(
        self,
        *,
        llm: Any,
        judge_model: str,
        calibration_gate: JudgeCalibrationGate,
    ) -> None:
        self._llm = llm
        self._judge_model = judge_model
        self._calibration_gate = calibration_gate

    async def judge(
        self,
        *,
        case: ConversationCase,
        result: BusinessTrialResult,
        assertions: Sequence[AssertionSpec],
    ) -> Sequence[SemanticDecision]:
        expected_identity = self._calibration_gate.expected_identity
        if expected_identity is None:
            raise JudgeNotCalibratedError(
                "business semantic judge is not calibrated: expected identity is required"
            )
        if expected_identity.judge_model != self._judge_model:
            raise JudgeNotCalibratedError(
                "business semantic judge is not calibrated: expected identity judge model "
                "does not match requested judge model"
            )
        if expected_identity.judge_prompt_sha256 != SEMANTIC_JUDGE_PROMPT_SHA256:
            raise JudgeNotCalibratedError(
                "business semantic judge is not calibrated: expected identity has a stale prompt"
            )
        if expected_identity.rubric_version != SEMANTIC_JUDGE_RUBRIC_VERSION:
            raise JudgeNotCalibratedError(
                "business semantic judge is not calibrated: expected identity has a stale rubric"
            )
        self._calibration_gate.require_calibrated()
        raw = result.observation
        if raw is None:
            raise InvalidEvidenceError("semantic judge received no observation")
        reference_context = {
            "hidden_facts": case.hidden_facts,
            "answer_requirements": case.answer_requirements,
            "allowed_variations": case.allowed_variations,
            "assertion_criteria": [item.model_dump(mode="json") for item in assertions],
        }
        observed_evidence = {
            "transcript": list(raw.transcript),
            "tool_ledger": list(raw.tool_ledger),
            "database_before_after": result.database_before_after,
            "raw_evidence": raw.evidence,
            "run_state": raw.run_state,
        }
        reference_context_json = json.dumps(
            reference_context,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        observed_evidence_json = json.dumps(
            observed_evidence,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        # The stable instruction block is the calibration identity. Dynamic case
        # evidence and assertions are appended but never allowed to change its policy.
        prompt = (
            f"{_SEMANTIC_JUDGE_CALIBRATION_INSTRUCTIONS}\n"
            f"case_id: {case.case_id}\n"
            f"reference_context: {reference_context_json}\n"
            f"observed_evidence: {observed_evidence_json}"
        )
        response = await asyncio.to_thread(
            self._llm.chat,
            prompt,
            tier="balanced",
            model=self._judge_model,
            schema=SemanticJudgeBatch,
            request_id=f"eval-judge-{case.case_id}-{result.trial_index}",
        )
        response_model = getattr(response, "model", None)
        if response_model != self._judge_model:
            raise InvalidEvidenceError(
                "semantic judge response model does not match requested judge model"
            )
        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, SemanticJudgeBatch):
            raise InvalidEvidenceError("semantic judge did not return the required schema")
        for decision in parsed.decisions:
            if not decision.evidence_quote.strip():
                raise InvalidEvidenceError(
                    f"semantic judge returned an empty quote for {decision.assertion_id}"
                )
            evidence_leaf = _resolve_path(observed_evidence, decision.evidence_path)
            if evidence_leaf is _MISSING:
                raise InvalidEvidenceError(
                    "semantic judge evidence path is not present in observed evidence for "
                    f"{decision.assertion_id}"
                )
            if not isinstance(evidence_leaf, str):
                raise InvalidEvidenceError(
                    f"semantic judge evidence path is not a string leaf for {decision.assertion_id}"
                )
            if decision.evidence_quote not in evidence_leaf:
                raise InvalidEvidenceError(
                    "semantic judge quote is not present at its observed evidence path for "
                    f"{decision.assertion_id}"
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

        domain_evidence = _project_market_evidence(raw.tool_ledger)
        projects_stock_quote = "get_stock_quote" in case.available_tools or any(
            row.get("tool_name") == "get_stock_quote" for row in raw.tool_ledger
        )
        evidence = (
            _without_unproven_market_facts(raw.evidence)
            if projects_stock_quote
            else deepcopy(raw.evidence)
        )
        _merge_mapping(evidence, domain_evidence)

        projected: dict[str, Any] = {
            "run": {**deepcopy(raw.run_state), "transcript": deepcopy(list(raw.transcript))},
            "tools": _project_tools(raw.tool_ledger),
            "database": deepcopy(result.database_before_after),
            "answer": {"text": answer_text, "final_text": answer_text},
            "evidence": {
                **evidence,
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
            if _is_unexecuted_available_tool_assertion(case, projected, assertion):
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


def _project_market_evidence(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    resolved_ts_code: Any = None

    lookup = _last_successful_call(ledger, "lookup_ts_code")
    if lookup is not None:
        call_index, row, result = lookup
        ts_code = result.get("ts_code")
        if ts_code is not None:
            resolved_ts_code = ts_code
            evidence["entity"] = {"ts_code": deepcopy(ts_code)}
            provenance["entity.ts_code"] = _field_provenance(
                tool_name="lookup_ts_code",
                call_index=call_index,
                result_field="ts_code",
                fault_injection=row.get("fault_injection"),
            )

    quote = _last_successful_call(ledger, "get_stock_quote")
    if quote is not None:
        call_index, row, result = quote
        quote_ts_code = result.get("ts_code")
        if (
            resolved_ts_code is not None
            and quote_ts_code is not None
            and quote_ts_code != resolved_ts_code
        ):
            raise InvalidEvidenceError(
                "conflicting ts_code between lookup_ts_code and get_stock_quote"
            )
        quote_values: dict[str, Any] = {}
        for field in _QUOTE_EVIDENCE_FIELDS:
            value = result.get(field)
            if value is None:
                continue
            normalized = _normalize_compact_date(value) if field == "trade_date" else value
            quote_values[field] = deepcopy(normalized)
            field_provenance = _field_provenance(
                tool_name="get_stock_quote",
                call_index=call_index,
                result_field=field,
                fault_injection=row.get("fault_injection"),
            )
            if normalized != value:
                field_provenance["normalization"] = "YYYYMMDD->YYYY-MM-DD"
            provenance[f"quote.{field}"] = field_provenance
        if quote_values:
            evidence["quote"] = quote_values

    if provenance:
        evidence["provenance"] = provenance
    return evidence


def _without_unproven_market_facts(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Drop market facts that did not originate in the captured tool ledger."""
    evidence = deepcopy(dict(raw))
    evidence.pop("quote", None)

    entity = evidence.get("entity")
    if isinstance(entity, dict):
        entity.pop("ts_code", None)
        if not entity:
            evidence.pop("entity", None)

    provenance = evidence.get("provenance")
    if isinstance(provenance, dict):
        for path in list(provenance):
            if path == "entity.ts_code" or str(path).startswith("quote."):
                provenance.pop(path, None)
        if not provenance:
            evidence.pop("provenance", None)
    return evidence


def _last_successful_call(
    ledger: Sequence[Mapping[str, Any]],
    tool_name: str,
) -> tuple[int, Mapping[str, Any], Mapping[str, Any]] | None:
    for call_index in range(len(ledger) - 1, -1, -1):
        row = ledger[call_index]
        if row.get("tool_name") != tool_name or row.get("error") is not None:
            continue
        result = row.get("result")
        if isinstance(result, Mapping):
            return call_index, row, result
    return None


def _field_provenance(
    *,
    tool_name: str,
    call_index: int,
    result_field: str,
    fault_injection: Any = None,
) -> dict[str, Any]:
    provenance = {
        "tool_name": tool_name,
        "call_index": call_index,
        "result_path": f"result.{result_field}",
    }
    if isinstance(fault_injection, Mapping):
        provenance["fault_injection"] = deepcopy(dict(fault_injection))
    return provenance


def _normalize_compact_date(value: Any) -> Any:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return value
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return value


def _merge_mapping(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Recursively merge source into target, with projected source values winning."""
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _merge_mapping(existing, value)
        else:
            target[key] = deepcopy(value)


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
            "idempotency_key": deepcopy(row.get("idempotency_key")),
            "fault_injection": deepcopy(row.get("fault_injection")),
        }
        for field_name in ("result", "error", "status", "error_code", "error_message"):
            if field_name in row:
                call[field_name] = deepcopy(row[field_name])
        calls.append(call)
        names.append(name)
        grouped.setdefault(name, []).append(call)
        values = row.get("permission_decisions")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            permissions.setdefault(name, []).extend(deepcopy(list(values)))
        elif "permission_decision" in row:
            permissions.setdefault(name, []).append(deepcopy(row["permission_decision"]))
        else:
            result = row.get("result")
            if isinstance(result, Mapping):
                legacy_values = result.get("permission_decisions")
                if isinstance(legacy_values, Sequence) and not isinstance(
                    legacy_values, (str, bytes, bytearray)
                ):
                    permissions.setdefault(name, []).extend(deepcopy(list(legacy_values)))
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


_MISSING = object()


def _is_unexecuted_available_tool_assertion(
    case: ConversationCase,
    projected: Mapping[str, Any],
    assertion: AssertionSpec,
) -> bool:
    """Treat a provably unexecuted available tool as valid negative evidence.

    A missing nested result remains invalid for a completed call. Total absence,
    an approval-pending call with an explicit null result, or a fully described
    failed/cancelled/timeout call is instead observed negative evidence that
    outcome assertions need to score as a task failure.
    """
    if assertion.source != "tools" or not assertion.path:
        return False
    segments = assertion.path.split(".")
    if any(not segment for segment in segments) or len(segments) < 2:
        return False
    tool_name, tail = segments[0], segments[1:]
    if not _is_supported_per_tool_path(tail):
        return False
    tools = projected.get("tools")
    if tool_name not in case.available_tools or not isinstance(tools, Mapping):
        return False
    tool = tools.get(tool_name)
    if tool is None:
        return True
    if not isinstance(tool, Mapping):
        return False

    call, call_tail, provably_absent = _resolve_asserted_tool_call(tool, tail)
    if provably_absent:
        return True
    if call is _MISSING:
        return False
    if not isinstance(call, Mapping) or call_tail[:1] != ["result"]:
        return False
    if call.get("status") == "approval_required":
        return "result" in call and call["result"] is None
    if call.get("status") not in {"failed", "cancelled", "timeout"}:
        return False
    return (
        "result" in call
        and call["result"] is None
        and all(field_name in call for field_name in ("error", "error_code", "error_message"))
        and any(call[field_name] for field_name in ("error", "error_code", "error_message"))
    )


def _is_supported_per_tool_path(tail: list[str]) -> bool:
    if tail == ["attempt_count"]:
        return True
    if len(tail) >= 2 and tail[0] == "last_call":
        return True
    return len(tail) >= 3 and tail[0] == "calls" and tail[1].isdigit()


def _resolve_asserted_tool_call(
    tool: Mapping[str, Any],
    tail: list[str],
) -> tuple[Any, list[str], bool]:
    if tail[0] == "last_call":
        return tool.get("last_call", _MISSING), tail[1:], False
    if tail[0] != "calls" or len(tail) < 3 or not tail[1].isdigit():
        return _MISSING, [], False
    calls = tool.get("calls")
    if not isinstance(calls, Sequence) or isinstance(calls, (str, bytes, bytearray)):
        return _MISSING, [], False
    index = int(tail[1])
    if index >= len(calls):
        return _MISSING, tail[2:], True
    return calls[index], tail[2:], False


def _resolve_path(root: Any, path: str) -> Any:
    if not path:
        return _MISSING
    current = root
    for segment in path.split("."):
        if not segment:
            return _MISSING
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
        return _MISSING
    return current


def _path_exists(root: Any, path: str) -> bool:
    if path == "":
        return root is not None
    return _resolve_path(root, path) is not _MISSING


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
