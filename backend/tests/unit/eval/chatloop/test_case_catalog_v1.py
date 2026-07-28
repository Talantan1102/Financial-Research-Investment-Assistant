"""Machine-readable 120-case catalog parity and safety audits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from eval.chatloop.case_loader import CaseCatalog, CaseCatalogError, load_catalog
from eval.chatloop.case_schema import AssertionSpec, SuiteType
from eval.chatloop.policy_registry import PolicyRegistry, score_cap

EXPECTED = {1: 22, 2: 14, 3: 10, 4: 15, 5: 12, 6: 18, 7: 17, 8: 12}
REPO_ROOT = Path(__file__).resolve().parents[5]
DESIGN_DIR = REPO_ROOT / "docs/superpowers/specs/conversational-agent-eval-cases"
FORMAL_USER_PREFIXES = (
    "综上所述",
    "基于以上分析",
    "我想咨询一下",
    "请从以下几个方面",
    "请全面分析",
)
LEAKED_INTERNAL_TOKENS = (
    "required_assertions",
    "forbidden_outcomes",
    "hidden_facts",
    "violation_caps",
    "task_pass",
    "action_required 状态断言",
)


@pytest.fixture(scope="module")
def catalog() -> CaseCatalog:
    return load_catalog()


def ids_from_design_markdown() -> set[str]:
    ids: set[str] = set()
    for path in sorted(DESIGN_DIR.glob("batch-*.md")):
        ids.update(re.findall(r"^## (B\d+-\d{2})\b", path.read_text("utf-8"), re.MULTILINE))
    return ids


def _all_assertions(case: object) -> list[AssertionSpec]:
    assertions = [
        *case.required_assertions,  # type: ignore[attr-defined]
        *case.forbidden_outcomes,  # type: ignore[attr-defined]
        *case.expected_state_changes,  # type: ignore[attr-defined]
    ]
    for outcome in case.acceptable_outcomes:  # type: ignore[attr-defined]
        assertions.extend(outcome.assertions)
    return assertions


def test_catalog_has_exactly_120_unique_cases(catalog: CaseCatalog) -> None:
    assert catalog.batch_counts == EXPECTED
    assert len(catalog.cases) == 120
    assert len({case.case_id for case in catalog.cases}) == 120


def test_markdown_and_jsonl_ids_match(catalog: CaseCatalog) -> None:
    assert set(catalog.case_ids) == ids_from_design_markdown()


def test_all_new_cases_start_as_capability(catalog: CaseCatalog) -> None:
    assert {case.suite_type for case in catalog.cases} == {SuiteType.CAPABILITY}
    assert {case.trial_count for case in catalog.cases} == {1}
    assert all(
        case.trial_status is None
        and case.task_pass is None
        and case.task_score is None
        and case.failure_reason is None
        for case in catalog.cases
    )


def test_catalog_covers_all_environment_axes(catalog: CaseCatalog) -> None:
    covered = {axis for case in catalog.cases for axis in case.initial_state.axes}
    assert covered == {f"E{i}" for i in range(1, 15)}


def test_all_policy_references_are_canonical_and_resolve(catalog: CaseCatalog) -> None:
    registry = PolicyRegistry.default()
    aliases = set(registry.aliases)
    for case in catalog.cases:
        trigger_assertions = [
            *case.required_assertions,
            *case.forbidden_outcomes,
            *case.expected_state_changes,
        ]
        assertion_policies = {
            assertion.policy_id
            for assertion in trigger_assertions
            if assertion.policy_id is not None
        }
        assert not aliases.intersection(case.applicable_policies)
        assert set(case.applicable_policies) <= assertion_policies, case.case_id
        for policy_id in case.applicable_policies:
            policy = registry.resolve(
                policy_id,
                as_of=catalog.policy_as_of,
                version=catalog.policy_version,
            )
            assert policy.policy_id == policy_id
            assert score_cap(case.violation_caps[policy_id]) <= score_cap(policy.base_severity)


def test_assertion_ids_and_references_are_valid(catalog: CaseCatalog) -> None:
    for case in catalog.cases:
        assertions = _all_assertions(case)
        assertion_ids = [assertion.assertion_id for assertion in assertions]
        assert len(assertion_ids) == len(set(assertion_ids)), case.case_id
        known = set(assertion_ids)
        grader_ids = {item for grader in case.graders for item in grader.assertion_ids}
        score_ids = {item for component in case.partial_credit for item in component.assertion_ids}
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
        assert grader_ids == known, case.case_id
        assert score_ids == positive_score_ids, case.case_id
        assert all(component.assertion_ids for component in case.partial_credit), case.case_id
        assert sum(component.points for component in case.partial_credit) <= 100
        assert set(case.violation_caps) == set(case.applicable_policies), case.case_id
        for assertion in assertions:
            if assertion.policy_id is not None:
                assert assertion.policy_id in case.applicable_policies, case.case_id
                assert assertion.severity == case.violation_caps[assertion.policy_id], case.case_id


def test_retail_dialogue_lint(catalog: CaseCatalog) -> None:
    complete_conversations: set[tuple[str, ...]] = set()
    colloquial_or_noisy = re.compile(
        r"(?:啊|呀|呢|吧|呗|咋|啥|先别|能不能|没|哈|嘛|！！|？？|!!|\?\?)"
    )
    noisy_cases = 0

    for case in catalog.cases:
        assert case.user_messages
        assert all(message.strip() for message in case.user_messages)
        schedule = case.initial_state.business_state.get("turn_schedule", [])
        actor_by_message = {
            item["message_index"]: item["actor_id"]
            for item in schedule
            if isinstance(item, dict)
            and isinstance(item.get("message_index"), int)
            and isinstance(item.get("actor_id"), str)
        }
        for index, (left, right) in enumerate(
            zip(case.user_messages, case.user_messages[1:]), start=1
        ):
            assert left != right or (
                actor_by_message.get(index) is not None
                and actor_by_message.get(index) != actor_by_message.get(index + 1)
            ), case.case_id
        conversation = tuple(case.user_messages)
        assert conversation not in complete_conversations, case.case_id
        complete_conversations.add(conversation)
        for message in case.user_messages:
            assert not message.startswith(FORMAL_USER_PREFIXES), (case.case_id, message)
            assert not any(token in message for token in LEAKED_INTERNAL_TOKENS)
            assert not re.search(r"(?:PRIV|TRADE|TRD|DATA|RUN|WRITE)-[A-Z0-9-]+-001", message)
        if any(colloquial_or_noisy.search(message) for message in case.user_messages):
            noisy_cases += 1

    assert noisy_cases >= 20


def test_b6_18_suspended_security_fails_closed(catalog: CaseCatalog) -> None:
    case = catalog.by_id("B6-18")
    facts = case.hidden_facts
    assert facts["trading_status"] == "suspended"
    assert facts["accept_new_order"] is False
    assertions = {
        (item.source, item.operator, item.path, item.expected) for item in _all_assertions(case)
    }
    assert ("database", "equals", "after.orders.count", 0) in assertions
    assert ("database", "equals", "after.funds.frozen_cash", 0.0) in assertions
    assert ("database", "equals", "after.permission_links.count", 0) in assertions


def test_b8_05_external_permission_flow_ends_current_run(catalog: CaseCatalog) -> None:
    case = catalog.by_id("B8-05")
    assertions = _all_assertions(case)

    def has_assertion(source: str, operator: str, path: str, expected: object) -> bool:
        return any(
            item.source == source
            and item.operator == operator
            and item.path == path
            and item.expected == expected
            for item in assertions
        )

    assert has_assertion("run", "equals", "status", "completed")
    assert has_assertion("run", "equals", "outcome", "action_required")
    assert has_assertion("database", "equals", "after.orders.count", 0)
    assert has_assertion(
        "run",
        "equals",
        "follow_up_contract.only_600519_starts_new_run",
        True,
    )


def test_loader_fails_loudly_when_manifest_count_is_tampered(tmp_path: Path) -> None:
    source_dir = CaseCatalog.default_root()
    copied = tmp_path / "v1"
    copied.mkdir()
    for source in source_dir.glob("*"):
        (copied / source.name).write_bytes(source.read_bytes())
    manifest = (
        (copied / "catalog.json")
        .read_text("utf-8")
        .replace('"total_count": 120', '"total_count": 119')
    )
    (copied / "catalog.json").write_text(manifest, encoding="utf-8")

    with pytest.raises(CaseCatalogError, match="total_count"):
        load_catalog(copied / "catalog.json")
