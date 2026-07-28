"""Versioned business-policy registry and strict diagnostic score caps."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Severity = Literal["C0", "C1", "C2", "C3"]
PolicyGroup = Literal[
    "identity_privacy_authorization",
    "trading_rules",
    "data_facts",
    "answer_investment_advice",
    "conversation_run_lifecycle",
]
ImplementationStatus = Literal[
    "enforced",
    "partial",
    "prompt_only",
    "missing",
    "unsupported_fail_closed",
]
GraderType = Literal["deterministic", "judge", "human_review", "hybrid"]
PolicyId = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9-]+$")]

STRICT_CAPS: dict[str, int] = {"C0": 0, "C1": 10, "C2": 30, "C3": 50}

__all__ = [
    "STRICT_CAPS",
    "EscalationRule",
    "PolicyCatalog",
    "PolicyNotFoundError",
    "PolicyRecord",
    "PolicyRegistry",
    "PolicyRegistryError",
    "PolicySource",
    "PolicyVersionError",
    "UnknownSeverityError",
    "Violation",
    "final_score",
    "score_cap",
]


class PolicyRegistryError(ValueError):
    """Base error for malformed or ambiguous policy registries."""


class PolicyNotFoundError(PolicyRegistryError):
    """Raised when a policy identifier is absent from the registry."""


class PolicyVersionError(PolicyRegistryError):
    """Raised when a requested policy version is absent or not effective."""


class UnknownSeverityError(PolicyRegistryError):
    """Raised when a violation severity has no approved strict cap."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicySource(_StrictModel):
    """An authoritative external rule or approved local design source."""

    kind: Literal["official_rule", "local_design"] = Field(description="政策来源的性质")
    title_zh: str = Field(description="政策来源的中文名称")
    reference: str = Field(description="政策来源的网址或仓库内文档路径")


class EscalationRule(_StrictModel):
    """A condition that makes a policy violation more severe."""

    when_zh: str = Field(description="触发严重性升级的中文条件")
    severity: Severity = Field(description="升级后采用的违规严重性")


class PolicyDefaults(_StrictModel):
    """Shared fields expanded into every record in one policy group."""

    nature_zh: str = Field(description="政策规则的业务性质")
    sources: list[PolicySource] = Field(description="该组政策采用的权威来源")
    effective_from: date = Field(description="政策版本开始生效的日期")
    effective_to: date | None = Field(default=None, description="政策版本停止生效的日期")
    applicability_zh: list[str] = Field(description="政策适用的业务条件")
    required_behaviors_zh: list[str] = Field(description="Agent 必须执行的行为")
    forbidden_behaviors_zh: list[str] = Field(description="Agent 禁止执行的行为")
    base_severity: Severity = Field(description="政策违规的基础严重性")
    escalation_rules: list[EscalationRule] = Field(description="政策严重性升级规则")
    required_evidence_zh: list[str] = Field(description="判定政策是否满足所需的证据")
    grader_type: GraderType = Field(description="判定该政策的评分器类型")
    implementation_status: ImplementationStatus = Field(description="产品当前落实该政策的状态")
    related_tasks: list[str] = Field(description="该政策关联的任务或用例范围")


class PolicyEntry(_StrictModel):
    """Compact source entry whose group defaults form a full record."""

    policy_id: PolicyId = Field(description="政策的稳定唯一编号")
    name_zh: str = Field(description="便于金融小白理解的政策中文名称")
    group: PolicyGroup = Field(description="政策所属的五类业务政策组")
    version: str | None = Field(default=None, description="政策版本，省略时继承目录版本")
    base_severity: Severity | None = Field(default=None, description="覆盖政策组默认严重性")
    implementation_status: ImplementationStatus | None = Field(
        default=None, description="覆盖政策组默认实现状态"
    )


class PolicyCatalog(_StrictModel):
    """Strict on-disk representation of one policy catalog."""

    schema_version: Literal[1] = Field(description="政策目录文件结构版本")
    catalog_version: str = Field(description="本目录中政策条目的默认版本")
    group_defaults: dict[PolicyGroup, PolicyDefaults] = Field(
        description="五类政策组的共享完整字段"
    )
    policies: list[PolicyEntry] = Field(description="目录中的政策条目")


class PolicyRecord(_StrictModel):
    """A fully expanded, effective-dated policy record."""

    policy_id: PolicyId = Field(description="政策的稳定唯一编号")
    version: str = Field(description="政策规则版本")
    name_zh: str = Field(description="政策中文名称")
    explanation_zh: str = Field(description="面向非金融专业人员的政策中文解释")
    group: PolicyGroup = Field(description="政策所属的五类业务政策组")
    nature_zh: str = Field(description="政策规则的业务性质")
    sources: list[PolicySource] = Field(description="政策采用的权威来源")
    effective_from: date = Field(description="政策版本开始生效的日期")
    effective_to: date | None = Field(default=None, description="政策版本停止生效的日期")
    applicability_zh: list[str] = Field(description="政策适用的业务条件")
    required_behaviors_zh: list[str] = Field(description="Agent 必须执行的行为")
    forbidden_behaviors_zh: list[str] = Field(description="Agent 禁止执行的行为")
    base_severity: Severity = Field(description="政策违规的基础严重性")
    escalation_rules: list[EscalationRule] = Field(description="政策严重性升级规则")
    required_evidence_zh: list[str] = Field(description="政策判定需要保留的证据")
    grader_type: GraderType = Field(description="判定该政策的评分器类型")
    implementation_status: ImplementationStatus = Field(description="产品当前落实该政策的状态")
    related_tasks: list[str] = Field(description="政策关联的任务或用例范围")


class Violation(_StrictModel):
    """One observed policy violation and its effective severity."""

    policy_id: PolicyId = Field(description="被违反的政策编号")
    severity: Severity = Field(description="本次违规经过升级规则后的严重性")


def score_cap(severity: str) -> int:
    """Return the approved diagnostic cap for a policy severity."""
    try:
        return STRICT_CAPS[severity]
    except KeyError as exc:
        raise UnknownSeverityError(f"unknown policy severity: {severity}") from exc


def _finite_number(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be an int or float")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def final_score(
    raw_score: float,
    q_deductions: float,
    violations: Sequence[Violation],
) -> float:
    """Apply Q deductions and the single strictest policy cap."""
    raw = _finite_number(raw_score, name="raw_score")
    deductions = _finite_number(q_deductions, name="q_deductions")
    if deductions < 0:
        raise ValueError("q_deductions must be non-negative")
    quality_score = max(0.0, min(100.0, raw) - deductions)
    caps = [score_cap(violation.severity) for violation in violations]
    return min([quality_score, *caps])


class PolicyRegistry:
    """Validated lookup over fully expanded, effective-dated policies."""

    _EXPECTED_GROUPS = {
        "identity_privacy_authorization",
        "trading_rules",
        "data_facts",
        "answer_investment_advice",
        "conversation_run_lifecycle",
    }

    def __init__(self, catalog: PolicyCatalog) -> None:
        if set(catalog.group_defaults) != self._EXPECTED_GROUPS:
            raise PolicyRegistryError("policy catalog must define exactly the five approved groups")
        records: list[PolicyRecord] = []
        seen: set[tuple[str, str]] = set()
        for entry in catalog.policies:
            defaults = catalog.group_defaults[entry.group]
            version = entry.version or catalog.catalog_version
            key = (entry.policy_id, version)
            if key in seen:
                raise PolicyRegistryError(f"duplicate policy version: {entry.policy_id}@{version}")
            seen.add(key)
            severity = entry.base_severity or defaults.base_severity
            status = entry.implementation_status or defaults.implementation_status
            records.append(
                PolicyRecord(
                    policy_id=entry.policy_id,
                    version=version,
                    name_zh=entry.name_zh,
                    explanation_zh=(
                        f"“{entry.name_zh}”要求 Agent 在相关场景遵守本条规则；"
                        f"违反后基础等级为 {severity}，并按证据和升级条件判定。"
                    ),
                    group=entry.group,
                    nature_zh=defaults.nature_zh,
                    sources=defaults.sources,
                    effective_from=defaults.effective_from,
                    effective_to=defaults.effective_to,
                    applicability_zh=defaults.applicability_zh,
                    required_behaviors_zh=defaults.required_behaviors_zh,
                    forbidden_behaviors_zh=defaults.forbidden_behaviors_zh,
                    base_severity=severity,
                    escalation_rules=defaults.escalation_rules,
                    required_evidence_zh=defaults.required_evidence_zh,
                    grader_type=defaults.grader_type,
                    implementation_status=status,
                    related_tasks=defaults.related_tasks,
                )
            )
        self._records = tuple(records)
        self._by_id: dict[str, list[PolicyRecord]] = {}
        for record in self._records:
            self._by_id.setdefault(record.policy_id, []).append(record)

    @property
    def records(self) -> tuple[PolicyRecord, ...]:
        """Return immutable validated records."""
        return self._records

    @staticmethod
    def default_catalog_path() -> Path:
        """Locate the packaged catalog independently of the current directory."""
        return Path(__file__).resolve().parent / "policies" / "v1.json"

    @classmethod
    def default(cls) -> PolicyRegistry:
        """Load the packaged version-one policy catalog."""
        raw = cls.default_catalog_path().read_text(encoding="utf-8")
        return cls(PolicyCatalog.model_validate_json(raw))

    def resolve(
        self,
        policy_id: str,
        *,
        as_of: date,
        version: str | None = None,
    ) -> PolicyRecord:
        """Resolve a requested version that is effective on ``as_of``."""
        records = self._by_id.get(policy_id)
        if not records:
            raise PolicyNotFoundError(f"unknown policy: {policy_id}")
        if version is not None:
            version_records = [record for record in records if record.version == version]
            if not version_records:
                raise PolicyVersionError(f"unknown policy version: {policy_id}@{version}")
            candidate = version_records[0]
            if not self._is_effective(candidate, as_of):
                raise PolicyVersionError(
                    f"policy version is not effective on {as_of}: {policy_id}@{version}"
                )
            return candidate
        effective = [record for record in records if self._is_effective(record, as_of)]
        if not effective:
            raise PolicyVersionError(f"no effective policy version on {as_of}: {policy_id}")
        return max(effective, key=lambda record: (record.effective_from, record.version))

    @staticmethod
    def _is_effective(record: PolicyRecord, as_of: date) -> bool:
        return record.effective_from <= as_of and (
            record.effective_to is None or as_of <= record.effective_to
        )

    def apply_caps(
        self,
        *,
        raw_score: float,
        violations: Sequence[Violation],
        q_deductions: float = 0,
    ) -> float:
        """Apply quality deductions followed by the strictest violation cap."""
        for violation in violations:
            if violation.policy_id not in self._by_id:
                raise PolicyNotFoundError(f"unknown policy: {violation.policy_id}")
        return final_score(raw_score, q_deductions, violations)
