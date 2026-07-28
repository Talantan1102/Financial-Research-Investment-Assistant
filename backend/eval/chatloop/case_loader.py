"""Strict loader and structural audits for versioned conversational cases."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from eval.chatloop.case_schema import AssertionSpec, ConversationCase
from eval.chatloop.policy_registry import (
    PolicyRegistry,
    PolicyRegistryError,
    Severity,
    Violation,
    score_cap,
)

__all__ = [
    "BatchManifest",
    "CaseCatalog",
    "CaseCatalogError",
    "CatalogManifest",
    "load_catalog",
]

_CASE_ID = re.compile(r"^B(?P<batch>[1-8])-(?P<number>\d{2})$")
_EXPECTED_SOURCE_SPECS = tuple(
    f"docs/superpowers/specs/conversational-agent-eval-cases/batch-{batch}-{slug}.md"
    for batch, slug in (
        (1, "foundations"),
        (2, "research-calculation"),
        (3, "investment-judgment"),
        (4, "personal-context"),
        (5, "watchlist"),
        (6, "trading-entitlements"),
        (7, "order-lifecycle"),
        (8, "cross-task-pressure"),
    )
)


class CaseCatalogError(ValueError):
    """Raised when catalog data is malformed, incomplete, or ambiguous."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchManifest(_StrictModel):
    """One JSONL file and its expected case count."""

    batch: PositiveInt = Field(strict=True, description="批次编号")
    file: str = Field(description="相对于目录文件的 JSONL 文件名")
    count: PositiveInt = Field(strict=True, description="该批次必须包含的用例数")


class CatalogManifest(_StrictModel):
    """Version and provenance contract for the case catalog."""

    schema_version: Literal[1] = Field(description="目录文件结构版本")
    catalog_version: str = Field(description="120 条业务用例的目录版本")
    policy_version: str = Field(description="评估时固定使用的政策版本")
    policy_as_of: date = Field(description="判断政策是否生效的固定日期")
    source_specs: list[str] = Field(description="人工设计源文档的仓库相对路径")
    source_spec_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="所有设计源文档规范化内容的摘要"
    )
    total_count: PositiveInt = Field(strict=True, description="目录预期用例总数")
    batches: list[BatchManifest] = Field(description="八个批次文件及预期数量")


@dataclass(frozen=True, slots=True)
class CaseCatalog:
    """A fully validated in-memory business-case catalog."""

    root: Path
    manifest: CatalogManifest
    cases: tuple[ConversationCase, ...]

    @staticmethod
    def default_root() -> Path:
        """Locate packaged v1 data independently of the current directory."""
        return Path(__file__).resolve().parent / "cases" / "v1"

    @property
    def batch_counts(self) -> dict[int, int]:
        """Return actual case counts by batch."""
        counts: dict[int, int] = {}
        for case in self.cases:
            match = _CASE_ID.fullmatch(case.case_id)
            if match is None:  # guarded by the loader, retained for type safety
                continue
            batch = int(match.group("batch"))
            counts[batch] = counts.get(batch, 0) + 1
        return counts

    @property
    def case_ids(self) -> tuple[str, ...]:
        """Return case identifiers in deterministic batch-file order."""
        return tuple(case.case_id for case in self.cases)

    @property
    def policy_version(self) -> str:
        return self.manifest.policy_version

    @property
    def policy_as_of(self) -> date:
        return self.manifest.policy_as_of

    def by_id(self, case_id: str) -> ConversationCase:
        """Return one case or fail with a domain-specific error."""
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise CaseCatalogError(f"unknown case_id: {case_id}")


def load_catalog(manifest_path: Path | str | None = None) -> CaseCatalog:
    """Load all batches, verify provenance, and audit cross-record references."""
    path = Path(manifest_path) if manifest_path is not None else CaseCatalog.default_root()
    if path.is_dir():
        path = path / "catalog.json"
    root = path.resolve().parent
    manifest = _load_manifest(path)
    expected_batches = {item.batch for item in manifest.batches}
    if expected_batches != set(range(1, 9)) or len(manifest.batches) != 8:
        raise CaseCatalogError("catalog must declare each batch 1 through 8 exactly once")
    expected_files = {batch: f"batch-{batch}.jsonl" for batch in range(1, 9)}
    if {item.batch: item.file for item in manifest.batches} != expected_files:
        raise CaseCatalogError("catalog must use the eight canonical batch JSONL paths")
    if tuple(manifest.source_specs) != _EXPECTED_SOURCE_SPECS:
        raise CaseCatalogError("source_specs must list the eight canonical design documents")

    registry = PolicyRegistry.default()
    aliases = set(registry.aliases)
    cases: list[ConversationCase] = []
    seen_ids: set[str] = set()
    actual_counts: dict[int, int] = {}
    for batch in sorted(manifest.batches, key=lambda item: item.batch):
        batch_path = root / batch.file
        batch_cases = _load_jsonl(batch_path)
        if len(batch_cases) != batch.count:
            raise CaseCatalogError(
                f"batch {batch.batch} count mismatch: expected {batch.count}, got {len(batch_cases)}"
            )
        actual_counts[batch.batch] = len(batch_cases)
        for case in batch_cases:
            match = _CASE_ID.fullmatch(case.case_id)
            if match is None or int(match.group("batch")) != batch.batch:
                raise CaseCatalogError(
                    f"case_id does not belong to batch {batch.batch}: {case.case_id}"
                )
            if case.case_id in seen_ids:
                raise CaseCatalogError(f"duplicate case_id: {case.case_id}")
            seen_ids.add(case.case_id)
            _audit_case(case, registry, aliases, manifest)
            cases.append(case)

    if len(cases) != manifest.total_count:
        raise CaseCatalogError(
            f"total_count mismatch: expected {manifest.total_count}, got {len(cases)}"
        )
    expected_counts = {item.batch: item.count for item in manifest.batches}
    if actual_counts != expected_counts:
        raise CaseCatalogError("manifest batch counts do not match loaded cases")
    _verify_source_hash(root, manifest)
    return CaseCatalog(root=root, manifest=manifest, cases=tuple(cases))


def _load_manifest(path: Path) -> CatalogManifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseCatalogError(f"cannot read catalog manifest: {path}") from exc
    try:
        data = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
        return CatalogManifest.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CaseCatalogError(f"invalid catalog manifest: {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[ConversationCase]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CaseCatalogError(f"cannot read case batch: {path}") from exc
    if not lines:
        raise CaseCatalogError(f"empty case batch: {path}")
    cases: list[ConversationCase] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise CaseCatalogError(f"blank JSONL record: {path}:{line_number}")
        try:
            data = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            cases.append(ConversationCase.model_validate(data))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise CaseCatalogError(f"invalid case record: {path}:{line_number}: {exc}") from exc
    return cases


def _audit_case(
    case: ConversationCase,
    registry: PolicyRegistry,
    aliases: set[str],
    manifest: CatalogManifest,
) -> None:
    if any(
        assertion.policy_id is not None or assertion.severity is not None
        for outcome in case.acceptable_outcomes
        for assertion in outcome.assertions
    ):
        raise CaseCatalogError(
            f"acceptable_outcomes cannot trigger policy caps in {case.case_id}; "
            "move common policy assertions to required or expected assertions"
        )
    assertions = _all_assertions(case)
    assertion_ids = [assertion.assertion_id for assertion in assertions]
    if len(assertion_ids) != len(set(assertion_ids)):
        raise CaseCatalogError(f"duplicate assertion_id in {case.case_id}")
    known = set(assertion_ids)
    grader_references = [item for grader in case.graders for item in grader.assertion_ids]
    grader_counts = Counter(grader_references)
    score_ids = {item for component in case.partial_credit for item in component.assertion_ids}
    if set(grader_counts) != known:
        raise CaseCatalogError(f"graders must cover every assertion in {case.case_id}")
    duplicate_grader_ids = sorted(
        assertion_id for assertion_id, count in grader_counts.items() if count != 1
    )
    if duplicate_grader_ids:
        raise CaseCatalogError(
            f"each assertion must belong to exactly one grader in {case.case_id}: "
            f"{', '.join(duplicate_grader_ids)}"
        )
    positive_score_ids = {
        assertion.assertion_id
        for assertion in [
            *case.required_assertions,
            *case.expected_state_changes,
            *[
                assertion
                for outcome in case.acceptable_outcomes
                for assertion in outcome.assertions
            ],
        ]
    }
    if score_ids != positive_score_ids:
        raise CaseCatalogError(
            f"partial_credit must cover every positive assertion and no forbidden assertion "
            f"in {case.case_id}"
        )
    if any(not component.assertion_ids for component in case.partial_credit):
        raise CaseCatalogError(f"partial-credit component has no assertions in {case.case_id}")
    if sum(component.points for component in case.partial_credit) > 100:
        raise CaseCatalogError(f"partial_credit exceeds 100 in {case.case_id}")
    if set(case.violation_caps) != set(case.applicable_policies):
        raise CaseCatalogError(
            f"violation_caps must cover every applicable policy in {case.case_id}"
        )
    if aliases.intersection(case.applicable_policies):
        raise CaseCatalogError(f"catalog case uses short policy alias: {case.case_id}")
    trigger_assertions = [
        *case.required_assertions,
        *case.forbidden_outcomes,
        *case.expected_state_changes,
    ]
    assertion_policies = {
        assertion.policy_id for assertion in trigger_assertions if assertion.policy_id is not None
    }
    missing_policy_assertions = set(case.applicable_policies) - assertion_policies
    if missing_policy_assertions:
        missing_text = ", ".join(sorted(missing_policy_assertions))
        raise CaseCatalogError(
            f"applicable policy has no executable assertion in {case.case_id}: {missing_text}"
        )
    for policy_id in case.applicable_policies:
        try:
            policy = registry.resolve(
                policy_id,
                as_of=manifest.policy_as_of,
                version=manifest.policy_version,
            )
        except PolicyRegistryError as exc:
            raise CaseCatalogError(f"unresolved policy in {case.case_id}: {policy_id}") from exc
        if score_cap(case.violation_caps[policy_id]) > score_cap(policy.base_severity):
            raise CaseCatalogError(
                f"violation cap is looser than policy base severity in {case.case_id}: {policy_id}"
            )
    for assertion in assertions:
        if assertion.policy_id is not None and assertion.policy_id not in case.applicable_policies:
            raise CaseCatalogError(
                f"assertion policy is not applicable in {case.case_id}: {assertion.policy_id}"
            )
        if assertion.policy_id is not None and (
            assertion.severity != case.violation_caps[assertion.policy_id]
        ):
            raise CaseCatalogError(
                f"assertion severity does not match violation cap in {case.case_id}: "
                f"{assertion.assertion_id}"
            )
        if assertion.policy_id is not None:
            if assertion.severity not in {"C0", "C1", "C2", "C3"}:
                raise CaseCatalogError(
                    f"policy assertion must declare a cap severity in {case.case_id}: "
                    f"{assertion.assertion_id}"
                )
            try:
                registry.effective_severity(
                    Violation(
                        policy_id=assertion.policy_id,
                        severity=cast(Severity, assertion.severity),
                        triggered_escalations=assertion.escalation_rule_ids,
                    ),
                    as_of=manifest.policy_as_of,
                    version=manifest.policy_version,
                )
            except PolicyRegistryError as exc:
                raise CaseCatalogError(
                    f"invalid assertion escalation in {case.case_id}: {assertion.assertion_id}"
                ) from exc


def _all_assertions(case: ConversationCase) -> list[AssertionSpec]:
    assertions = [
        *case.required_assertions,
        *case.forbidden_outcomes,
        *case.expected_state_changes,
    ]
    for outcome in case.acceptable_outcomes:
        assertions.extend(outcome.assertions)
    return assertions


def _verify_source_hash(root: Path, manifest: CatalogManifest) -> None:
    repo_root = _find_repo_root(root)
    digest = hashlib.sha256()
    for relative in manifest.source_specs:
        source = repo_root / relative
        if not source.is_file():
            raise CaseCatalogError(f"missing source spec: {relative}")
        normalized = "\n".join(source.read_text(encoding="utf-8").splitlines()) + "\n"
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(normalized.encode("utf-8"))
        digest.update(b"\0")
    if digest.hexdigest() != manifest.source_spec_sha256:
        raise CaseCatalogError("source_spec_sha256 does not match approved Markdown inputs")


def _find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "docs/superpowers/specs/conversational-agent-eval-cases").is_dir():
            return candidate
    raise CaseCatalogError("cannot locate repository root for source-spec verification")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaseCatalogError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
