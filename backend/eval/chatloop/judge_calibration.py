"""Calibration gate for the business-semantic LLM judge.

Each JSONL row is an independently labeled sample bound to the exact judge
model, prompt hash, and rubric version that produced its judge label. The human
label must be assigned without seeing the judge label. This module validates
the file contract and measures the resulting three-class agreement; it does not
generate labels.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Self

MIN_SAMPLE_COUNT: Final = 30
MIN_COHEN_KAPPA: Final = 0.6
MIN_AGREEMENT: Final = 0.8

_IDENTITY_FIELDS = frozenset({"judge_model", "judge_prompt_sha256", "rubric_version"})
_REQUIRED_FIELDS = frozenset({"id", "human_label", "judge_label"}) | _IDENTITY_FIELDS


class CalibrationLabel(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class CalibrationDataError(ValueError):
    """Raised when calibration data violates the strict input contract."""


class JudgeNotCalibratedError(RuntimeError):
    """Raised when a semantic judge is used before its gate opens."""


@dataclass(frozen=True)
class CalibrationIdentity:
    judge_model: str
    judge_prompt_sha256: str
    rubric_version: str

    def __post_init__(self) -> None:
        for field in ("judge_model", "rubric_version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise CalibrationDataError(f"{field} must be a non-empty string")
        if (
            not isinstance(self.judge_prompt_sha256, str)
            or len(self.judge_prompt_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.judge_prompt_sha256)
        ):
            raise CalibrationDataError("judge_prompt_sha256 must be 64 lowercase hex characters")


@dataclass(frozen=True)
class JudgeCalibrationItem:
    """One independently human-labeled sample paired with a judge label."""

    id: str
    human_label: CalibrationLabel
    judge_label: CalibrationLabel
    judge_model: str
    judge_prompt_sha256: str
    rubric_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id or self.id != self.id.strip():
            raise CalibrationDataError("id must be a non-empty string without edge whitespace")
        if not isinstance(self.human_label, CalibrationLabel):
            raise CalibrationDataError("human_label must be pass, fail, or unknown")
        if not isinstance(self.judge_label, CalibrationLabel):
            raise CalibrationDataError("judge_label must be pass, fail, or unknown")
        CalibrationIdentity(
            judge_model=self.judge_model,
            judge_prompt_sha256=self.judge_prompt_sha256,
            rubric_version=self.rubric_version,
        )

    @property
    def identity(self) -> CalibrationIdentity:
        return CalibrationIdentity(
            judge_model=self.judge_model,
            judge_prompt_sha256=self.judge_prompt_sha256,
            rubric_version=self.rubric_version,
        )


@dataclass(frozen=True)
class JudgeCalibrationResult:
    sample_count: int
    agreement: float
    cohen_kappa: float | None
    calibrated: bool
    review_items: tuple[JudgeCalibrationItem, ...]
    failure_reasons: tuple[str, ...]
    identity: CalibrationIdentity | None
    minimum_sample_count: int = MIN_SAMPLE_COUNT
    minimum_cohen_kappa: float = MIN_COHEN_KAPPA
    minimum_agreement: float = MIN_AGREEMENT


@dataclass(frozen=True)
class JudgeCalibrationGate:
    """Small integration boundary for ``LLMSemanticEvidenceJudge`` callers."""

    result: JudgeCalibrationResult
    expected_identity: CalibrationIdentity | None = None

    @classmethod
    def from_items(
        cls,
        items: Sequence[JudgeCalibrationItem],
        *,
        expected_identity: Mapping[str, str] | CalibrationIdentity | None = None,
    ) -> Self:
        return cls(
            result=evaluate_calibration(items),
            expected_identity=_coerce_identity(expected_identity),
        )

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        *,
        expected_identity: Mapping[str, str] | CalibrationIdentity | None = None,
    ) -> Self:
        return cls.from_items(
            load_calibration_jsonl(path),
            expected_identity=expected_identity,
        )

    @property
    def calibrated(self) -> bool:
        return self.result.calibrated and (
            self.expected_identity is None or self.expected_identity == self.result.identity
        )

    def require_calibrated(self) -> None:
        """Fail closed before constructing or invoking the semantic judge."""

        if self.calibrated:
            return
        failure_reasons = list(self.result.failure_reasons)
        if self.expected_identity is not None and self.expected_identity != self.result.identity:
            failure_reasons.append("identity_mismatch")
        reasons = ", ".join(failure_reasons)
        raise JudgeNotCalibratedError(f"business semantic judge is not calibrated: {reasons}")


def load_calibration_jsonl(path: str | Path) -> tuple[JudgeCalibrationItem, ...]:
    """Load calibration rows while rejecting malformed or ambiguous input."""

    rows: list[JudgeCalibrationItem] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise CalibrationDataError(f"line {line_number}: blank lines are not allowed")
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CalibrationDataError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(raw, Mapping):
            raise CalibrationDataError(f"line {line_number}: row must be a JSON object")

        item = _parse_item(raw, line_number=line_number)
        if item.id in seen_ids:
            raise CalibrationDataError(f"line {line_number}: duplicate id {item.id!r}")
        seen_ids.add(item.id)
        rows.append(item)
    return tuple(rows)


def evaluate_calibration(
    items: Sequence[JudgeCalibrationItem],
) -> JudgeCalibrationResult:
    """Compute agreement and multiclass Cohen's kappa, then apply the gate."""

    rows = tuple(items)
    _reject_duplicate_ids(rows)
    agreement, kappa = _agreement_and_kappa(rows)
    review_items = tuple(
        item
        for item in rows
        if item.human_label != item.judge_label
        or CalibrationLabel.UNKNOWN in (item.human_label, item.judge_label)
    )
    has_unknown = any(
        CalibrationLabel.UNKNOWN in (item.human_label, item.judge_label) for item in rows
    )

    failure_reasons: list[str] = []
    identities = {item.identity for item in rows}
    identity = next(iter(identities)) if len(identities) == 1 else None
    if len(identities) > 1:
        failure_reasons.append("calibration_identity_inconsistent")
    if len(rows) < MIN_SAMPLE_COUNT:
        failure_reasons.append("sample_count_below_minimum")
    if kappa is None:
        failure_reasons.append("cohen_kappa_undefined")
    elif kappa < MIN_COHEN_KAPPA:
        failure_reasons.append("cohen_kappa_below_minimum")
    if agreement < MIN_AGREEMENT:
        failure_reasons.append("agreement_below_minimum")
    if has_unknown:
        failure_reasons.append("unknown_labels_present")

    return JudgeCalibrationResult(
        sample_count=len(rows),
        agreement=agreement,
        cohen_kappa=kappa,
        calibrated=not failure_reasons,
        review_items=review_items,
        failure_reasons=tuple(failure_reasons),
        identity=identity,
    )


def _parse_item(raw: Mapping[object, object], *, line_number: int) -> JudgeCalibrationItem:
    fields = set(raw)
    missing = _REQUIRED_FIELDS.difference(fields)
    if missing:
        names = ", ".join(sorted(missing))
        raise CalibrationDataError(f"line {line_number}: missing fields: {names}")
    unknown = fields.difference(_REQUIRED_FIELDS)
    if unknown:
        names = ", ".join(sorted(str(field) for field in unknown))
        raise CalibrationDataError(f"line {line_number}: unknown fields: {names}")

    identifier = raw["id"]
    if not isinstance(identifier, str):
        raise CalibrationDataError(f"line {line_number}: id must be a string")
    return JudgeCalibrationItem(
        id=identifier,
        human_label=_parse_label(raw["human_label"], "human_label", line_number),
        judge_label=_parse_label(raw["judge_label"], "judge_label", line_number),
        judge_model=_parse_identity_text(raw["judge_model"], "judge_model", line_number),
        judge_prompt_sha256=_parse_identity_text(
            raw["judge_prompt_sha256"], "judge_prompt_sha256", line_number
        ),
        rubric_version=_parse_identity_text(raw["rubric_version"], "rubric_version", line_number),
    )


def _parse_identity_text(value: object, field: str, line_number: int) -> str:
    if not isinstance(value, str):
        raise CalibrationDataError(f"line {line_number}: {field} must be a string")
    return value


def _coerce_identity(
    value: Mapping[str, str] | CalibrationIdentity | None,
) -> CalibrationIdentity | None:
    if value is None or isinstance(value, CalibrationIdentity):
        return value
    fields = set(value)
    if fields != _IDENTITY_FIELDS:
        raise CalibrationDataError(
            "expected identity must contain judge_model, judge_prompt_sha256, and rubric_version"
        )
    return CalibrationIdentity(
        judge_model=value["judge_model"],
        judge_prompt_sha256=value["judge_prompt_sha256"],
        rubric_version=value["rubric_version"],
    )


def _parse_label(value: object, field: str, line_number: int) -> CalibrationLabel:
    if not isinstance(value, str):
        raise CalibrationDataError(f"line {line_number}: invalid {field}: {value!r}")
    try:
        return CalibrationLabel(value)
    except ValueError as exc:
        raise CalibrationDataError(
            f"line {line_number}: invalid {field}: {value!r}; expected pass, fail, or unknown"
        ) from exc


def _reject_duplicate_ids(items: Sequence[JudgeCalibrationItem]) -> None:
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise CalibrationDataError(f"duplicate id {item.id!r}")
        seen.add(item.id)


def _agreement_and_kappa(items: Sequence[JudgeCalibrationItem]) -> tuple[float, float | None]:
    sample_count = len(items)
    if sample_count == 0:
        return 0.0, None

    agreement = sum(item.human_label == item.judge_label for item in items) / sample_count
    expected_agreement = sum(
        sum(item.human_label == label for item in items)
        * sum(item.judge_label == label for item in items)
        for label in CalibrationLabel
    ) / (sample_count * sample_count)
    if expected_agreement == 1.0:
        return agreement, None
    kappa = (agreement - expected_agreement) / (1.0 - expected_agreement)
    return agreement, kappa


__all__ = [
    "MIN_AGREEMENT",
    "MIN_COHEN_KAPPA",
    "MIN_SAMPLE_COUNT",
    "CalibrationDataError",
    "CalibrationIdentity",
    "CalibrationLabel",
    "JudgeCalibrationGate",
    "JudgeCalibrationItem",
    "JudgeCalibrationResult",
    "JudgeNotCalibratedError",
    "evaluate_calibration",
    "load_calibration_jsonl",
]
