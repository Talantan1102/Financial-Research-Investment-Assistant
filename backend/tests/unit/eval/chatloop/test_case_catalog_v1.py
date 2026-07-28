"""Machine-readable 120-case catalog parity and safety audits."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from eval.chatloop.case_loader import CaseCatalog, CaseCatalogError, load_catalog
from eval.chatloop.case_schema import AssertionSpec, SuiteType
from eval.chatloop.policy_registry import PolicyRegistry, score_cap

EXPECTED = {1: 22, 2: 14, 3: 10, 4: 15, 5: 12, 6: 18, 7: 17, 8: 12}
APPROVED_SCORE_VECTORS = {
    "B5-01": [20, 30, 20, 30],
    "B5-02": [15, 35, 20, 15, 15],
    "B5-03": [20, 20, 25, 20, 15],
    "B5-04": [20, 35, 20, 15, 10],
    "B5-05": [30, 30, 20, 20],
    "B5-06": [40, 30, 20, 10],
    "B5-07": [40, 30, 30],
    "B5-08": [60, 30, 10],
    "B5-09": [50, 25, 15, 10],
    "B5-10": [25, 30, 25, 20],
    "B5-12": [30, 40, 30],
    "B6-02": [20, 20, 25, 25, 10],
    "B6-03": [20, 25, 40, 15],
    "B6-04": [25, 25, 30, 20],
    "B6-05": [50, 35, 15],
}
APPROVED_COMPONENT_NAMES = {
    "B5-01": ["工具参数", "本人集合", "字段展示", "隔离与口径"],
    "B5-02": ["实体", "新增写入", "备注", "监控", "审计"],
    "B5-03": ["名称", "备注", "保留字段", "审计", "回答"],
    "B5-04": ["监控意图", "状态更新", "保留字段", "说明", "审计"],
    "B5-05": ["删除", "持仓不变", "审计", "说明"],
    "B5-06": ["幂等", "字段保持", "审计", "回答"],
    "B5-07": ["发现歧义", "候选展示", "无写入"],
    "B5-08": ["无写入", "研究回答", "表达"],
    "B5-09": ["最终字段", "无丢失更新", "审计", "回答"],
    "B5-10": ["未知结果处理", "终态读取", "幂等", "回答"],
    "B5-12": ["识别市场", "安全失败", "说明"],
    "B6-02": ["资格", "预览", "确认", "订单", "表达"],
    "B6-03": ["差异保存", "二次校验", "执行参数", "回答"],
    "B6-04": ["市场覆盖", "状态", "动作区分", "表达"],
    "B6-05": ["资格检查", "无写入", "表达"],
}
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


def test_reviewed_partial_credit_vectors_match_the_approved_markdown(
    catalog: CaseCatalog,
) -> None:
    for case_id, expected in APPROVED_SCORE_VECTORS.items():
        actual = [item.points for item in catalog.by_id(case_id).partial_credit if item.points]
        assert actual == expected, case_id


def test_reviewed_partial_credit_components_keep_explainable_chinese_names(
    catalog: CaseCatalog,
) -> None:
    for case_id, expected in APPROVED_COMPONENT_NAMES.items():
        actual = [item.name_zh for item in catalog.by_id(case_id).partial_credit if item.points]
        assert actual == expected, case_id


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
        grader_references = [item for grader in case.graders for item in grader.assertion_ids]
        grader_counts = Counter(grader_references)
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
        assert set(grader_counts) == known, case.case_id
        assert all(count == 1 for count in grader_counts.values()), case.case_id
        assert score_ids == positive_score_ids, case.case_id
        assert all(component.assertion_ids for component in case.partial_credit), case.case_id
        assert sum(component.points for component in case.partial_credit) <= 100
        assert set(case.violation_caps) == set(case.applicable_policies), case.case_id
        for assertion in assertions:
            if assertion.policy_id is not None:
                assert assertion.policy_id in case.applicable_policies, case.case_id
                assert assertion.severity == case.violation_caps[assertion.policy_id], case.case_id
        assert all(
            assertion.policy_id is None and assertion.severity is None
            for outcome in case.acceptable_outcomes
            for assertion in outcome.assertions
        ), case.case_id
        source_by_id = {item.assertion_id: item.source for item in assertions}
        for grader in case.graders:
            assert all(
                (source_by_id[assertion_id] == "judge") == (grader.type == "judge")
                for assertion_id in grader.assertion_ids
            ), case.case_id


def test_tool_name_membership_assertions_never_use_raw_call_objects(
    catalog: CaseCatalog,
) -> None:
    name_list_paths = {"called", "call_sequence", "order_write_calls"}
    invalid = [
        (case.case_id, assertion.assertion_id, assertion.path)
        for case in catalog.cases
        for assertion in _all_assertions(case)
        if assertion.source == "tools"
        and assertion.operator in {"contains", "not_contains"}
        and isinstance(assertion.expected, str)
        and assertion.path not in name_list_paths
    ]

    assert invalid == []


def test_retail_dialogue_lint(catalog: CaseCatalog) -> None:
    complete_conversations: set[tuple[str, ...]] = set()
    colloquial_or_noisy = re.compile(
        r"(?:啊|呀|呢|吧|呗|咋|啥|先别|能不能|没|哈|嘛|！！|？？|!!|\?\?)"
    )
    noisy_cases = 0
    blemish_patterns = {
        "typo": re.compile(r"(?:现再|今天张几个点|备注写等年报把|，在买)"),
        "repetition": re.compile(r"(?:我我|这个这个|来点，来点)"),
        "punctuation": re.compile(r"[？！!?]{2,}"),
        "spacing": re.compile(r"\s{2,}"),
        "filler_or_correction": re.compile(r"(?:^那个|^呃|不是，我是说)"),
    }
    blemished_cases: set[str] = set()
    blemish_category_counts = dict.fromkeys(blemish_patterns, 0)

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
        for category, pattern in blemish_patterns.items():
            if any(pattern.search(message) for message in case.user_messages):
                blemished_cases.add(case.case_id)
                blemish_category_counts[category] += 1

    assert noisy_cases >= 20
    assert len(blemished_cases) >= 20
    assert sum(count > 0 for count in blemish_category_counts.values()) >= 4
    assert max(blemish_category_counts.values()) <= 10


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


def test_reviewed_catalog_risk_cases_have_executable_guards(catalog: CaseCatalog) -> None:
    b501 = catalog.by_id("B5-01")
    assert any(
        item.source == "database"
        and item.operator == "count_equals"
        and item.path == "after.watchlist.codes"
        and item.expected == 2
        for item in b501.required_assertions
    )
    b501_paths = {item.path for item in b501.required_assertions}
    assert {
        "after.watchlist.by_code.600519_SH.name",
        "after.watchlist.by_code.600519_SH.note",
        "after.watchlist.by_code.600519_SH.monitoring_enabled",
        "after.watchlist.by_code.600036_SH.name",
        "after.watchlist.by_code.600036_SH.monitoring_enabled",
    } <= b501_paths
    assert {
        "claims.watchlist.by_code.600519_SH.name",
        "claims.watchlist.by_code.600519_SH.note",
        "claims.watchlist.by_code.600519_SH.monitoring_enabled",
        "claims.watchlist.by_code.600036_SH.name",
        "claims.watchlist.by_code.600036_SH.note",
        "claims.watchlist.by_code.600036_SH.monitoring_enabled",
    } <= b501_paths

    b508 = catalog.by_id("B5-08")
    b508_guards = {
        (item.source, item.operator, item.path, str(item.expected))
        for item in b508.required_assertions
    }
    assert ("tools", "contains", "call_sequence", "research_quote") in b508_guards
    assert ("answer", "contains", "text", "宁德时代") in b508_guards
    assert ("judge", "equals", "research_answer_relevant", "True") in b508_guards

    b507 = catalog.by_id("B5-07")
    assert any(
        item.path == "conversation.assistant_question_count" for item in b507.required_assertions
    )
    b509 = catalog.by_id("B5-09")
    assert any(item.path == "concurrency.lost_update_count" for item in b509.required_assertions)

    b601 = catalog.by_id("B6-01")
    required_paths = {item.path for item in b601.required_assertions}
    assert {
        "pause.payload.ts_code",
        "pause.payload.side",
        "pause.payload.quantity",
        "pause.payload.order_type",
        "pause.payload.quote_as_of",
        "pause.payload.estimated_amount",
        "pause.payload.estimated_fee",
        "idempotency.replay_effect_count",
        "idempotency.replay_call_count",
        "idempotency.same_key_replayed",
        "after.funds.freeze_events",
    } <= required_paths
    assert b601.fault_injection

    b606 = catalog.by_id("B6-06")
    assert any(
        item.assertion_id == "b606_outcome_link"
        and item.policy_id == "RUN-ACTION-REQUIRED-001"
        and item.severity == "C1"
        for item in b606.required_assertions
    )

    b604 = catalog.by_id("B6-04")
    expected_markets = {
        item.expected
        for item in b604.required_assertions
        if item.source == "answer" and item.operator == "contains"
    }
    assert {"主板", "创业板", "科创板", "北交所"} <= expected_markets

    b604_paths = {item.path for item in b604.required_assertions}
    for market in ("main_board", "gem", "star_market", "bse"):
        assert {
            f"claims.entitlements.{market}.status",
            f"claims.entitlements.{market}.can_buy",
            f"claims.entitlements.{market}.can_sell",
            f"claims.entitlements.{market}.can_subscribe",
        } <= b604_paths

    b808 = catalog.by_id("B8-08")
    schedule = b808.initial_state.business_state["turn_schedule"]
    assert schedule[2]["actor_id"] == "user-b"
    assert schedule[2]["run_id"] == "run-b8-08-b"


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


def test_loader_rejects_incomplete_source_spec_manifest(tmp_path: Path) -> None:
    source_dir = CaseCatalog.default_root()
    copied = tmp_path / "v1"
    copied.mkdir()
    for source in source_dir.glob("*"):
        (copied / source.name).write_bytes(source.read_bytes())
    manifest_path = copied / "catalog.json"
    manifest = manifest_path.read_text("utf-8")
    start = manifest.index('  "source_specs": [')
    end = manifest.index("  ],", start) + len("  ],")
    manifest_path.write_text(
        manifest[:start] + '  "source_specs": [],' + manifest[end:],
        encoding="utf-8",
    )

    with pytest.raises(CaseCatalogError, match="source_specs"):
        load_catalog(manifest_path)


def test_loader_rejects_assertion_owned_by_multiple_graders(tmp_path: Path) -> None:
    source_dir = CaseCatalog.default_root()
    copied = tmp_path / "v1"
    copied.mkdir()
    for source in source_dir.glob("*"):
        (copied / source.name).write_bytes(source.read_bytes())

    batch_path = copied / "batch-1.jsonl"
    records = [json.loads(line) for line in batch_path.read_text("utf-8").splitlines()]
    case = next(record for record in records if record["case_id"] == "B1-01")
    duplicate_id = case["graders"][0]["assertion_ids"][0]
    case["graders"][0]["assertion_ids"].append(duplicate_id)
    batch_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseCatalogError, match="exactly one grader"):
        load_catalog(copied / "catalog.json")
