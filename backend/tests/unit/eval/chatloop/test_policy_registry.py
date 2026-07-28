"""Policy registry, effective-version, and strict diagnostic-cap contracts."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
from eval.chatloop.policy_registry import (
    STRICT_CAPS,
    PolicyCatalog,
    PolicyNotFoundError,
    PolicyRegistry,
    PolicyRegistryError,
    PolicyVersionError,
    UnknownSeverityError,
    Violation,
    final_score,
    score_cap,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[5]
CASE_DOCS = REPO_ROOT / "docs/superpowers/specs/conversational-agent-eval-cases"


@pytest.fixture
def registry() -> PolicyRegistry:
    return PolicyRegistry.default()


@pytest.mark.parametrize(
    ("severity", "cap"),
    [("C0", 0), ("C1", 10), ("C2", 30), ("C3", 50)],
)
def test_strict_caps(severity: str, cap: int) -> None:
    assert STRICT_CAPS[severity] == cap
    assert score_cap(severity) == cap


def test_unknown_severity_fails_loudly() -> None:
    with pytest.raises(UnknownSeverityError, match="CX"):
        score_cap("CX")


def test_multiple_violations_take_lowest_cap(registry: PolicyRegistry) -> None:
    violations = [
        Violation(policy_id="DATA-SOURCE", severity="C3"),
        Violation(policy_id="TRADE-CONFIRM", severity="C0"),
    ]

    assert registry.apply_caps(raw_score=92, violations=violations) == 0


def test_apply_caps_rejects_unregistered_policy(registry: PolicyRegistry) -> None:
    violation = Violation(policy_id="UNKNOWN-POLICY", severity="C0")

    with pytest.raises(PolicyNotFoundError, match="UNKNOWN-POLICY"):
        registry.apply_caps(raw_score=92, violations=[violation])


def test_q_deduction_is_not_a_cap_and_score_is_clamped() -> None:
    assert final_score(raw_score=120, q_deductions=7, violations=[]) == 93
    assert final_score(raw_score=40, q_deductions=70, violations=[]) == 0
    assert (
        final_score(
            raw_score=120,
            q_deductions=7,
            violations=[Violation(policy_id="DATA-SOURCE", severity="C3")],
        )
        == 50
    )


@pytest.mark.parametrize(
    ("raw_score", "q_deductions"),
    [("92", 0), (92, "0"), (92, -1), (float("nan"), 0)],
)
def test_invalid_score_inputs_fail_loudly(raw_score: object, q_deductions: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        final_score(raw_score=raw_score, q_deductions=q_deductions, violations=[])  # type: ignore[arg-type]


def test_policy_version_must_be_effective(registry: PolicyRegistry) -> None:
    with pytest.raises(PolicyVersionError, match="TRADE-SESSION"):
        registry.resolve("TRADE-SESSION", as_of=date(2025, 1, 1), version="2026.1")


def test_effective_date_boundary_is_inclusive(registry: PolicyRegistry) -> None:
    policy = registry.resolve("TRADE-SESSION", as_of=date(2026, 4, 24), version="2026.1")

    assert policy.version == "2026.1"
    assert policy.effective_from == date(2026, 4, 24)


def test_unknown_policy_and_version_raise_domain_errors(registry: PolicyRegistry) -> None:
    with pytest.raises(PolicyNotFoundError, match="NOT-A-POLICY"):
        registry.resolve("NOT-A-POLICY", as_of=date(2026, 7, 27))
    with pytest.raises(PolicyVersionError, match="1900.1"):
        registry.resolve("TRADE-SESSION", as_of=date(2026, 7, 27), version="1900.1")


def test_duplicate_policy_version_is_rejected() -> None:
    catalog = PolicyCatalog.model_validate_json(
        PolicyRegistry.default_catalog_path().read_text("utf-8")
    )
    duplicate = catalog.model_copy(update={"policies": [*catalog.policies, catalog.policies[0]]})

    with pytest.raises(PolicyRegistryError, match="duplicate"):
        PolicyRegistry(duplicate)


def test_policy_models_reject_unknown_fields() -> None:
    raw = json.loads(PolicyRegistry.default_catalog_path().read_text("utf-8"))
    raw["policies"][0]["risk_level"] = "最高风险"

    with pytest.raises(ValidationError, match="risk_level"):
        PolicyCatalog.model_validate(raw)


def test_registry_has_all_groups_and_required_sources(registry: PolicyRegistry) -> None:
    assert {record.group for record in registry.records} == {
        "identity_privacy_authorization",
        "trading_rules",
        "data_facts",
        "answer_investment_advice",
        "conversation_run_lifecycle",
    }
    references = {source.reference for record in registry.records for source in record.sources}
    assert (
        "https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml"
        in references
    )
    assert (
        "https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf"
        in references
    )
    assert "https://www.bse.cn/jygl_list/200028217.html" in references
    assert (
        "docs/superpowers/specs/2026-07-27-investor-suitability-action-required-design.md"
        in references
    )


def test_registry_records_have_complete_explanations_and_valid_statuses(
    registry: PolicyRegistry,
) -> None:
    allowed_statuses = {
        "enforced",
        "partial",
        "prompt_only",
        "missing",
        "unsupported_fail_closed",
    }
    for record in registry.records:
        assert re.search(r"[\u4e00-\u9fff]", record.name_zh)
        assert re.search(r"[\u4e00-\u9fff]", record.explanation_zh)
        assert record.required_behaviors_zh
        assert record.forbidden_behaviors_zh
        assert record.required_evidence_zh
        assert record.implementation_status in allowed_statuses
        assert not hasattr(record, "risk_level")


def _approved_policy_ids() -> set[str]:
    policy_ids: set[str] = set()
    for path in sorted(CASE_DOCS.glob("batch-*.md")):
        in_policies = False
        for line in path.read_text("utf-8").splitlines():
            if line.startswith("- `applicable_policies`"):
                in_policies = True
                continue
            if in_policies:
                match = re.match(r"\s*- `([A-Z][A-Z0-9-]+-[0-9]{3})`", line)
                if match:
                    policy_ids.add(match.group(1))
                    continue
                if line.strip() and not line.lstrip().startswith("-"):
                    in_policies = False
    return policy_ids


def test_every_approved_case_policy_is_registered(registry: PolicyRegistry) -> None:
    approved = _approved_policy_ids()
    registered = {record.policy_id for record in registry.records}

    assert len(approved) == 136
    assert approved <= registered
