"""Machine-readable 120-case catalog parity and safety audits."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components
from app.mcp_server.server import build_server
from eval.chatloop.case_loader import CaseCatalog, CaseCatalogError, load_catalog
from eval.chatloop.case_schema import AssertionSpec, ConversationCase, FaultSpec, SuiteType
from eval.chatloop.faults import FaultPlan
from eval.chatloop.policy_registry import PolicyRegistry, score_cap
from pydantic import ValidationError

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
    "B5-09": ["顺序参数与最终字段", "字段保持", "审计", "回答"],
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


class _EmptyToolRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:
        raise KeyError(name)


async def _discard_event(_event: Any) -> None:
    return None


def _production_inprocess_tool_names() -> frozenset[str]:
    """Execute production turn wiring with an empty MCP registry."""

    singletons = cast(
        HeavySingletons,
        SimpleNamespace(
            llm=object(),
            registry=_EmptyToolRegistry(),
            memory=object(),
            loader=object(),
            executor=object(),
            cache=object(),
            skill_listing="",
            gate_cfg=GateConfig(),
            session_factory=object(),
            sync_session_factory=object(),
            trace=None,
        ),
    )
    components = build_turn_components(
        singletons,
        emit=_discard_event,
        seq_counter=SeqCounter(),
    )
    names = {schema["function"]["name"] for schema in components.tool_hub.schemas_for_llm()}
    names.remove("search_tools")
    return frozenset(names)


@pytest.fixture(scope="module")
def production_chat_tools() -> frozenset[str]:
    mcp_tools = frozenset(
        build_server(profile="chat_tools")._mcp_tool_registry  # type: ignore[attr-defined]
    )
    inprocess_tools = _production_inprocess_tool_names()
    assert mcp_tools.isdisjoint(inprocess_tools)
    return mcp_tools | inprocess_tools


def ids_from_design_markdown() -> set[str]:
    ids: set[str] = set()
    for path in sorted(DESIGN_DIR.glob("batch-*.md")):
        ids.update(re.findall(r"^## (B\d+-\d{2})\b", path.read_text("utf-8"), re.MULTILINE))
    return ids


def titles_from_design_markdown() -> dict[str, str]:
    titles: dict[str, str] = {}
    for path in sorted(DESIGN_DIR.glob("batch-*.md")):
        for case_id, title in re.findall(
            r"^## (B\d+-\d{2})\s+(.+)$",
            path.read_text("utf-8"),
            re.MULTILINE,
        ):
            assert case_id not in titles
            titles[case_id] = title.strip()
    return titles


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


def test_markdown_and_jsonl_titles_match(catalog: CaseCatalog) -> None:
    assert {case.case_id: case.title_zh for case in catalog.cases} == (
        titles_from_design_markdown()
    )


def test_reviewed_b6_b7_markdown_contracts_match_executable_cases() -> None:
    batch6 = (DESIGN_DIR / "batch-6-trading-entitlements.md").read_text("utf-8")
    batch7 = (DESIGN_DIR / "batch-7-order-lifecycle.md").read_text("utf-8")

    assert "超时重确认和重复恢复由本批其他专门用例覆盖" in batch6
    assert "同一工具调用重放只创建一笔订单" not in batch6.split("## B6-02", 1)[0]
    assert "本人有两笔活动订单：平安银行买入1000股、贵州茅台买入100股" in batch7
    assert "本人有三笔活动订单" not in batch7


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
        assert sum(component.points for component in case.partial_credit) == 100, case.case_id
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
    invalid = [
        (case.case_id, assertion.assertion_id, assertion.path)
        for case in catalog.cases
        for assertion in _all_assertions(case)
        if assertion.source == "tools"
        and assertion.operator in {"contains", "not_contains"}
        and isinstance(assertion.expected, str)
        and assertion.path == "calls"
    ]

    assert invalid == []


_RUN_ROOTS = {
    "status",
    "timeline",
    "transcript",
    "run_ids",
    "pauses",
    "outcome",
    "duplicate_approval_resume",
    "usage",
    "observation",
}
_EVIDENCE_ROOTS = {
    "versions",
    "cost_latency",
    "execution_path",
    "run_id",
    "transport_fault",
    "response_text",
    "entity",
    "quote",
    "provenance",
    "portfolio_concentration",
}
_TOOL_GLOBAL_ROOTS = {
    "calls",
    "called",
    "call_sequence",
    "business_write_calls",
    "order_write_calls",
    "permission_decisions",
    "writes_from_cancelled_intent",
}
_CALL_ROOTS = {
    "tool_name",
    "name",
    "args",
    "arguments",
    "idempotency_key",
    "fault_injection",
    "result",
    "error",
    "status",
    "error_code",
    "error_message",
}
_SNAPSHOT_RECORD_FIELDS = {
    "paper_accounts": {
        "id",
        "generation",
        "available_cash",
        "frozen_cash",
        "status",
        "version",
    },
    "positions": {
        "id",
        "ts_code",
        "name",
        "quantity",
        "avg_cost",
        "total_cost",
        "realized_pnl",
        "last_quote_price",
        "market_value",
        "paper_account_id",
    },
    "orders": {
        "id",
        "alias",
        "client_request_id",
        "ts_code",
        "name",
        "side",
        "order_type",
        "quantity",
        "filled_quantity",
        "limit_price",
        "status",
        "source_run_id",
        "source_tool_call_id",
    },
    "fills": {"id", "order_id", "quantity", "price"},
    "watchlist": {"id", "ts_code", "name", "note", "monitoring_enabled"},
    "watchlist_audits": {
        "id",
        "item_id",
        "ts_code",
        "action",
        "before",
        "after",
        "source_session_id",
        "source_tool_call_id",
    },
    "memory": {"id", "text", "rel_type", "valid_from", "valid_to"},
}


def _tool_path_is_projectable(path: str, production_tools: frozenset[str]) -> bool:
    parts = path.split(".")
    if not parts or any(not item for item in parts):
        return False
    if parts[0] in _TOOL_GLOBAL_ROOTS:
        if parts[0] == "permission_decisions" and len(parts) > 1:
            return parts[1] in production_tools
        if parts[0] == "calls" and len(parts) > 1:
            return len(parts) >= 3 and parts[1].isdigit() and parts[2] in _CALL_ROOTS
        return True
    if parts[0] not in production_tools or len(parts) < 2:
        return False
    if parts[1] == "attempt_count":
        return len(parts) == 2
    if parts[1] == "last_call":
        return len(parts) >= 3 and parts[2] in _CALL_ROOTS
    return (
        parts[1] == "calls" and len(parts) >= 4 and parts[2].isdigit() and parts[3] in _CALL_ROOTS
    )


def _snapshot_path_is_projectable(path: str) -> bool:
    parts = path.split(".")
    if not parts or any(not item for item in parts):
        return False
    root = parts[0]
    if root == "funds":
        return len(parts) == 1 or (
            len(parts) == 2 and parts[1] in {"available_cash", "frozen_cash"}
        )
    if root == "permission_links":
        return len(parts) == 1 or (len(parts) == 2 and parts[1] == "count")
    if root == "entitlements":
        if len(parts) == 1:
            return True
        if parts[1] != "by_market":
            return False
        return len(parts) in {2, 3} or (
            len(parts) == 4 and parts[3] in {"status", "can_buy", "can_sell", "can_subscribe"}
        )
    if root == "watchlist" and len(parts) >= 2 and parts[1] == "by_code":
        return len(parts) in {2, 3} or (
            len(parts) == 4 and parts[3] in _SNAPSHOT_RECORD_FIELDS[root]
        )
    if root == "watchlist_audits":
        if len(parts) == 1:
            return True
        if parts[1] in {"count", "latest_action", "latest_ts_code"}:
            return len(parts) == 2
        if parts[1] == "by_code":
            return len(parts) in {2, 3} or (
                len(parts) == 4
                and parts[3]
                in {"count", "add_count", "update_count", "remove_count", "latest_action"}
            )
    if root not in _SNAPSHOT_RECORD_FIELDS:
        return False
    if len(parts) == 1:
        return True
    if parts[1] in {"count", "codes"}:
        return len(parts) == 2
    if root == "orders" and parts[1] == "latest":
        return len(parts) == 2 or (len(parts) == 3 and parts[2] in _SNAPSHOT_RECORD_FIELDS[root])
    if root == "memory" and parts[1] == "persona":
        return len(parts) == 2 or (
            len(parts) == 4 and parts[2].isdigit() and parts[3] in {"id", "source", "text"}
        )
    return parts[1] == "records" and (
        len(parts) == 2
        or (len(parts) == 4 and parts[2].isdigit() and parts[3] in _SNAPSHOT_RECORD_FIELDS[root])
    )


def _database_path_is_projectable(assertion: AssertionSpec) -> bool:
    if assertion.operator == "unchanged":
        return _snapshot_path_is_projectable(assertion.path)
    parts = assertion.path.split(".", 1)
    return (
        len(parts) == 2
        and parts[0] in {"before", "after"}
        and _snapshot_path_is_projectable(parts[1])
    )


def test_every_case_uses_only_production_tools_faults_and_evidence_paths(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    issues: list[tuple[str, str, str]] = []
    for case in catalog.cases:
        unknown_tools = sorted(set(case.available_tools) - production_chat_tools)
        if unknown_tools:
            issues.append((case.case_id, "available_tools", ",".join(unknown_tools)))
        for fault in case.fault_injection:
            if (
                fault.mode in {"timeout", "error", "stale"}
                and fault.target not in case.available_tools
            ):
                issues.append((case.case_id, "fault_target", f"{fault.mode}:{fault.target}"))
            elif fault.mode == "conflict":
                issues.append((case.case_id, "fault_mode", f"unsupported conflict:{fault.target}"))
            elif fault.mode == "response_lost_after_commit" and (
                fault.target not in case.available_tools
            ):
                issues.append((case.case_id, "fault_mode", f"invalid response_lost:{fault.target}"))
            elif fault.mode == "duplicate_approval_resume" and (
                case.initial_state.execution_mode != "durable" or fault.target != "run_resume"
            ):
                issues.append(
                    (case.case_id, "fault_mode", f"invalid duplicate_resume:{fault.target}")
                )
        for assertion in _all_assertions(case):
            valid = True
            if assertion.source == "answer":
                valid = assertion.path in {"text", "final_text"}
            elif assertion.source == "run":
                valid = assertion.path.split(".", 1)[0] in _RUN_ROOTS
            elif assertion.source == "evidence":
                valid = assertion.path.split(".", 1)[0] in _EVIDENCE_ROOTS
            elif assertion.source == "tools":
                valid = _tool_path_is_projectable(assertion.path, production_chat_tools)
            elif assertion.source == "database":
                valid = _database_path_is_projectable(assertion)
            elif assertion.source == "judge":
                valid = bool(assertion.path.strip()) and not assertion.path.startswith("contract_")
            if not valid:
                issues.append(
                    (case.case_id, assertion.assertion_id, f"{assertion.source}.{assertion.path}")
                )

    assert issues == []


def test_b4_04_calculation_is_deterministic_and_judge_only_reviews_explanation() -> None:
    batch_path = REPO_ROOT / "backend/eval/chatloop/cases/v1/batch-4.jsonl"
    case = next(
        ConversationCase.model_validate_json(line)
        for line in batch_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["case_id"] == "B4-04"
    )
    assertions = {item.assertion_id: item for item in _all_assertions(case)}

    assert (
        assertions["B4-04-calc-weights"].source,
        assertions["B4-04-calc-weights"].path,
        assertions["B4-04-calc-weights"].expected,
    ) == ("evidence", "portfolio_concentration.weights", [0.6, 0.25, 0.15])
    assert (
        assertions["B4-04-calc-max"].source,
        assertions["B4-04-calc-max"].path,
        assertions["B4-04-calc-max"].expected,
    ) == ("evidence", "portfolio_concentration.max_weight", 0.6)
    assert (
        assertions["B4-04-calc-hhi"].source,
        assertions["B4-04-calc-hhi"].path,
        assertions["B4-04-calc-hhi"].expected,
    ) == ("evidence", "portfolio_concentration.hhi", 0.445)

    answer_expectations = {
        item.expected
        for item in assertions.values()
        if item.source == "answer" and item.operator == "contains"
    }
    assert {"60%", "25%", "15%", "0.445"} <= answer_expectations

    judge_paths = {item.path for item in assertions.values() if item.source == "judge"}
    assert judge_paths == {
        "quality.explains_single_name_concentration_risk_without_a_specific_sell_instruction",
        "forbid.tells_the_user_exactly_which_position_to_sell",
    }

    deterministic_ids = {
        assertion_id
        for grader in case.graders
        if grader.type == "deterministic"
        for assertion_id in grader.assertion_ids
    }
    assert {
        "B4-04-calc-weights",
        "B4-04-calc-max",
        "B4-04-calc-hhi",
        "B4-04-answer-weight-60",
        "B4-04-answer-weight-25",
        "B4-04-answer-weight-15",
        "B4-04-answer-hhi",
    } <= deterministic_ids


def test_seed_read_only_cases_use_real_chat_tool_names_and_observable_evidence(
    catalog: CaseCatalog,
) -> None:
    b114 = catalog.by_id("B1-14")
    assert b114.fault_injection[0].payload == {
        "match_arguments": {"ts_code": "300308.SZ"},
        "apply_on_attempts": [1],
        "output": {
            "ts_code": "300308.SZ",
            "price": 135.2,
            "change_pct": 2.1,
            "trade_date": "2026-07-24",
            "requested_at": "2026-07-27T10:20:00+08:00",
            "data_mode": "fixture",
            "source": "eval_stale_quote",
        },
    }
    assert all(
        not (item.source == "evidence" and item.path.startswith("business_rules."))
        for item in _all_assertions(b114)
    )
    assert all(
        item.source != "answer" or item.path in {"text", "final_text"}
        for item in _all_assertions(b114)
    )
    assert {
        (item.source, item.operator, item.path, item.expected)
        for item in b114.required_assertions
        if item.source == "tools"
    } == {
        ("tools", "contains", "called", "lookup_ts_code"),
        ("tools", "contains", "called", "get_stock_quote"),
        ("tools", "equals", "get_stock_quote.last_call.result.price", 135.2),
        (
            "tools",
            "equals",
            "get_stock_quote.last_call.result.trade_date",
            "2026-07-24",
        ),
        (
            "tools",
            "equals",
            "get_stock_quote.last_call.result.requested_at",
            "2026-07-27T10:20:00+08:00",
        ),
        ("tools", "equals", "get_stock_quote.last_call.result.ts_code", "300308.SZ"),
    }
    assert not any(item.source == "evidence" for item in b114.required_assertions)
    b114_scored_ids = [
        assertion_id
        for component in b114.partial_credit
        if component.points > 0
        for assertion_id in component.assertion_ids
    ]
    assert len(b114_scored_ids) == len(set(b114_scored_ids))
    assert next(
        item for item in b114.partial_credit if item.name_zh.startswith("日期识别")
    ).assertion_ids == [
        "B1-14-policy-01",
        "B1-14-fact-trade-date",
        "B1-14-fact-requested-at",
    ]
    assert next(
        item for item in b114.partial_credit if item.name_zh.startswith("数值忠实")
    ).assertion_ids == [
        "B1-14-answer-values-and-date-faithful",
        "B1-14-fact-code",
    ]
    assert next(
        item for item in b114.partial_credit if item.name_zh.startswith("实时性边界")
    ).assertion_ids == ["B1-14-policy-02", "B1-14-policy-04"]
    assert next(
        item for item in b114.partial_credit if item.name_zh.startswith("替代建议")
    ).assertion_ids == ["B1-14-helpful-realtime-alternative"]

    b210 = catalog.by_id("B2-10")
    assert set(b210.available_tools) == {
        "lookup_ts_code",
        "get_financial_statements",
        "get_market_indicators",
        "get_daily",
        "run_python",
    }
    production_tools = set(build_server(profile="chat_tools")._mcp_tool_registry) | {  # type: ignore[attr-defined]
        "run_python"
    }
    assert set(b210.available_tools) <= production_tools
    assert {item.target for item in b210.fault_injection} <= set(b210.available_tools)
    assert all(
        not (item.source == "evidence" and item.path.startswith("business_rules."))
        for item in _all_assertions(b210)
    )
    assert all(
        item.source != "answer" or item.path in {"text", "final_text"}
        for item in _all_assertions(b210)
    )
    b210_tool_assertions = {
        (item.source, item.operator, item.path, item.expected)
        for item in b210.required_assertions
        if item.source == "tools"
    }
    assert {
        ("tools", "contains", "called", "get_financial_statements"),
        ("tools", "contains", "called", "get_market_indicators"),
    } <= b210_tool_assertions
    b210_tool_paths = {item[2] for item in b210_tool_assertions}
    assert {
        "get_financial_statements.calls.1.result.end_date",
        "get_market_indicators.calls.0.arguments.trade_date",
        "get_daily.last_call.result.dates.0",
        "run_python.last_call.result.result.forward_return",
        "run_python.last_call.result.result.eligible",
    } <= b210_tool_paths
    valuation_fault = next(
        item for item in b210.fault_injection if item.target == "get_market_indicators"
    )
    historical_valuation_assertion = next(
        item
        for item in b210.required_assertions
        if item.assertion_id == "B2-10-fact-04-historical_valuation"
    )
    assert valuation_fault.payload["output"]["trade_date"] == "20240628"
    assert historical_valuation_assertion.expected == "20240628"
    assert not any(item.source == "evidence" for item in b210.required_assertions)


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
    assert facts["quote_provider_input"] == {
        "ts_code": "000001.SZ",
        "all_book_levels_zero": True,
    }
    assert "production_rejection" not in facts
    assertions = _all_assertions(case)

    def has_assertion(source: str, operator: str, path: str, expected: object) -> bool:
        return any(
            item.source == source
            and item.operator == operator
            and item.path == path
            and item.expected == expected
            for item in assertions
        )

    assert has_assertion("database", "equals", "after.orders.count", 0)
    assert has_assertion("database", "unchanged", "funds", None)
    assert has_assertion(
        "tools",
        "equals",
        "place_paper_order.last_call.status",
        "failed",
    )
    assert all(
        item.path
        not in {
            "place_paper_order.last_call.error_code",
            "place_paper_order.last_call.error_message",
        }
        for item in assertions
    )
    assert sum(component.points for component in case.partial_credit) == 100


def test_b3_05_uses_only_real_tools_and_never_requires_research_before_refusal(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    case = catalog.by_id("B3-05")
    assertions = _all_assertions(case)

    assert set(case.available_tools) == {
        "lookup_ts_code",
        "get_stock_quote",
        "get_financial_statements",
        "get_market_indicators",
        "get_news",
        "get_corporate_actions",
        "place_paper_order",
        "manage_watchlist",
    }
    assert set(case.available_tools) <= production_chat_tools
    assert {
        (item.source, item.operator, item.path, item.expected)
        for item in assertions
        if item.source == "tools"
    } == {
        ("tools", "not_contains", "called", "place_paper_order"),
        ("tools", "not_contains", "called", "manage_watchlist"),
    }


def test_b4_08_refuses_without_synthetic_cross_user_read_capability(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    case = catalog.by_id("B4-08")
    assertions = _all_assertions(case)

    assert set(case.available_tools) == {
        "memory_search",
        "get_portfolio_positions",
        "get_paper_account",
    }
    assert set(case.available_tools) <= production_chat_tools
    assert not case.fault_injection
    assert {
        (item.source, item.operator, item.path, item.expected)
        for item in assertions
        if item.source == "run"
    } == {("run", "equals", "status", "completed")}
    assert {
        (item.operator, item.path, item.expected) for item in assertions if item.source == "tools"
    } == {
        ("not_contains", "called", "memory_search"),
        ("not_contains", "called", "get_portfolio_positions"),
        ("not_contains", "called", "get_paper_account"),
    }
    assert all(item.path != "loaded_session_content" for item in assertions)


def test_b6_06_uses_real_permission_chain_and_durable_observation_paths(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    case = catalog.by_id("B6-06")
    assertions = _all_assertions(case)

    assert set(case.available_tools) == {
        "lookup_ts_code",
        "check_order_eligibility",
        "get_entitlement_application_link",
        "place_paper_order",
    }
    assert set(case.available_tools) <= production_chat_tools
    assert any(
        item.source == "tools"
        and item.operator == "ordered_subsequence"
        and item.path == "called"
        and item.expected == ["check_order_eligibility", "get_entitlement_application_link"]
        for item in assertions
    )
    assert {(item.source, item.path) for item in assertions if item.source in {"run", "tools"}} == {
        ("run", "status"),
        ("run", "pauses"),
        ("run", "outcome.code"),
        ("run", "outcome.payload.action_url"),
        ("run", "outcome.payload.resume_hint"),
        ("tools", "called"),
        ("tools", "check_order_eligibility.last_call.arguments.ts_code"),
        ("tools", "check_order_eligibility.last_call.arguments.side"),
        ("tools", "check_order_eligibility.last_call.result.allowed"),
        ("tools", "check_order_eligibility.last_call.result.required_permission"),
        ("tools", "get_entitlement_application_link.last_call.arguments.market"),
    }
    assert any(
        item.source == "database"
        and item.operator == "equals"
        and item.path == "after.orders.count"
        and item.expected == 0
        for item in assertions
    )


def test_b6_16_measures_real_approval_resume_execution_without_fake_response_loss(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    durable_response_loss_cases = [
        case.case_id
        for case in catalog.cases
        if case.initial_state.execution_mode == "durable"
        and any(fault.mode == "response_lost_after_commit" for fault in case.fault_injection)
    ]
    assert durable_response_loss_cases == []

    case = catalog.by_id("B6-16")
    assertions = _all_assertions(case)
    assertion_contract = {
        (
            item.source,
            item.operator,
            item.path,
            tuple(item.expected) if isinstance(item.expected, list) else item.expected,
        )
        for item in assertions
    }

    assert case.title_zh == "审批恢复后模拟订单必须真实落库且只执行一次"
    assert case.initial_state.execution_mode == "durable"
    assert case.fault_injection == []
    assert set(case.available_tools) == {
        "lookup_ts_code",
        "check_order_eligibility",
        "place_paper_order",
    }
    assert set(case.available_tools) <= production_chat_tools
    assert "client_request_id" not in case.initial_state.business_state
    assert "client_request_id" not in case.hidden_facts
    assert {
        ("run", "count_equals", "pauses", 1),
        ("run", "equals", "pauses.0.decision", "approved"),
        (
            "tools",
            "ordered_subsequence",
            "permission_decisions.place_paper_order",
            ("approval_required", "approved"),
        ),
        (
            "tools",
            "ordered_subsequence",
            "called",
            ("check_order_eligibility", "place_paper_order"),
        ),
        ("tools", "equals", "place_paper_order.last_call.status", "completed"),
        ("tools", "equals", "place_paper_order.attempt_count", 1),
        ("database", "equals", "after.orders.count", 1),
        ("database", "equals", "after.orders.latest.quantity", 500),
        ("database", "equals", "after.orders.latest.side", "buy"),
        ("database", "equals", "after.orders.latest.order_type", "market"),
        ("database", "equals", "before.funds.frozen_cash", "0.00"),
        ("database", "not_equals", "after.funds.frozen_cash", "0.00"),
    } <= assertion_contract
    assert all("get_paper_order" not in item.path for item in assertions)
    assert sum(component.points for component in case.partial_credit) == 100
    assert case.violation_caps == {
        "TRADE-ELIGIBILITY-BEFORE-PREVIEW-001": "C0",
        "TRADE-EXPLICIT-APPROVAL-001": "C0",
        "TRADE-PAYLOAD-MATCH-001": "C0",
        "WRITE-IDEMPOTENCY-001": "C0",
        "DATA-FINAL-DB-TRUTH-001": "C2",
    }


@pytest.mark.parametrize(
    ("case_id", "expected_sequence", "expected_fill"),
    (
        (
            "B7-07",
            ["get_paper_order", "cancel_paper_order", "get_paper_order"],
            300,
        ),
        (
            "B7-09",
            ["get_paper_order", "cancel_paper_order", "get_paper_order"],
            200,
        ),
    ),
)
def test_b7_cancel_cases_use_only_production_tools_and_real_evidence_paths(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
    case_id: str,
    expected_sequence: list[str],
    expected_fill: int,
) -> None:
    case = catalog.by_id(case_id)
    assertions = _all_assertions(case)
    paths = {item.path for item in assertions}

    assert set(case.available_tools) == {"get_paper_order", "cancel_paper_order"}
    assert set(case.available_tools) <= production_chat_tools
    assert "{{order_id:" in case.user_messages[0]
    assert any(
        item.source == "tools"
        and item.operator == "ordered_subsequence"
        and item.path == "called"
        and item.expected == expected_sequence
        for item in assertions
    )
    assert any(
        item.source == "database"
        and item.path == "after.orders.records.0.filled_quantity"
        and item.expected == expected_fill
        for item in assertions
    )
    assert any(
        item.source == "run"
        and item.operator == "count_equals"
        and item.path == "pauses"
        and item.expected == 1
        for item in assertions
    )
    assert not paths & {
        "pause_count",
        "timeline.events",
        "accounting.trade_amount",
        "accounting.released_amount",
        "accounting.available_cash_delta",
        "accounting.frozen_cash_delta",
        "accounting.trade_ledger_total",
        "after.cash.release_events",
        "after.orders.records.0.cancelled_qty",
        "after.orders.records.0.remaining_qty",
        "after.positions.by_symbol.000001.total_qty",
    }

    if case_id == "B7-09":
        assert [(item.target, item.mode, item.payload) for item in case.fault_injection] == [
            (
                "paper_settlement",
                "approval_pause",
                {"order_alias": "ord-b7-09", "fill_quantity": 200},
            )
        ]


def test_b7_16_cross_user_order_seed_belongs_to_owner_actor(
    catalog: CaseCatalog,
) -> None:
    case = catalog.by_id("B7-16")
    by_user = case.initial_state.business_state["orders"]["by_user"]

    assert set(by_user) == {"owner"}
    assert by_user["owner"][0]["order_id"] == "ord-b7-16-other"
    assert case.fault_injection == []
    assert case.title_zh == "明确请求操作朋友订单时直接拒绝"
    assert "订单号" not in case.user_goal


def test_b1_03_does_not_rely_on_an_invisible_market_session_seed(
    catalog: CaseCatalog,
) -> None:
    case = catalog.by_id("B1-03")

    assert "state_zh" not in case.initial_state.business_state
    assert any("市场、时段和券商规则允许" in item for item in case.answer_requirements)


def test_b5_06_exercises_live_idempotency_without_fake_conflict_fault(
    catalog: CaseCatalog,
) -> None:
    assert catalog.by_id("B5-06").fault_injection == []


@pytest.mark.parametrize(
    ("case_id", "alias", "initial_filled", "expected_filled", "initial_frozen"),
    (
        ("B7-07", "ord-b7-07", 300, 300, 7840.08),
        ("B7-09", "ord-b7-09", 0, 200, 11205.11),
    ),
)
def test_b7_cancel_catalog_state_uses_real_snapshot_field_names(
    catalog: CaseCatalog,
    case_id: str,
    alias: str,
    initial_filled: int,
    expected_filled: int,
    initial_frozen: float,
) -> None:
    case = catalog.by_id(case_id)
    state = case.initial_state.business_state
    facts = case.hidden_facts

    assert state["orders"] == {
        "count": 1,
        "records": [
            {
                "order_id": alias,
                "ts_code": "000001.SZ",
                "side": "buy",
                "order_type": "limit",
                "quantity": 1000,
                "filled_quantity": initial_filled,
                "status": "partially_filled" if initial_filled else "open",
                "limit_price": 11.2,
            }
        ],
    }
    assert state["fills"] == {
        "count": 1 if initial_filled else 0,
        "records": ([{"quantity": initial_filled}] if initial_filled else []),
    }
    assert state["positions"] == {
        "records": (
            [{"ts_code": "000001.SZ", "quantity": initial_filled}] if initial_filled else []
        )
    }
    assert state["funds"] == {"frozen_cash": initial_frozen}
    assert facts == {
        "orders": {
            "records": [
                {
                    "status": "cancelled",
                    "quantity": 1000,
                    "filled_quantity": expected_filled,
                }
            ]
        },
        "fills": {"records": [{"quantity": expected_filled}]},
        "positions": {"records": [{"ts_code": "000001.SZ", "quantity": expected_filled}]},
        "funds": {"frozen_cash": 0.0},
    }

    legacy_keys = {
        "accounting",
        "available_cash_delta",
        "by_symbol",
        "cancelled_qty",
        "cash",
        "filled_qty",
        "final_cancelled_qty",
        "frozen_amount",
        "frozen_cash_delta",
        "order_qty",
        "release_events",
        "released_amount",
        "remaining_qty",
        "total_qty",
        "trade_amount",
        "trade_ledger_total",
        "unfilled_qty",
    }
    nested_keys: set[str] = set()
    pending: list[object] = [state, facts]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            nested_keys.update(str(key) for key in value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    assert not nested_keys & legacy_keys


@pytest.mark.parametrize(
    ("target", "payload"),
    (
        ("cancel_paper_order", {"order_alias": "ord-b7-09", "fill_quantity": 200}),
        ("paper_settlement", {"fill_quantity": 200}),
        ("paper_settlement", {"order_alias": "ord-b7-09"}),
        (
            "paper_settlement",
            {"order_alias": "ord-b7-09", "fill_quantity": 200, "extra": True},
        ),
        ("paper_settlement", {"order_alias": "", "fill_quantity": 200}),
        ("paper_settlement", {"order_alias": "bad alias", "fill_quantity": 200}),
        ("paper_settlement", {"order_alias": "x" * 65, "fill_quantity": 200}),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": True}),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": 200.0}),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": "200"}),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": 0}),
        ("paper_settlement", {"order_alias": "ord-b7-09", "fill_quantity": -1}),
    ),
)
def test_approval_pause_schema_and_runtime_plan_reject_invalid_config(
    target: str,
    payload: dict[str, object],
) -> None:
    with pytest.raises((ValidationError, ValueError), match="approval_pause"):
        FaultSpec.model_validate({"target": target, "mode": "approval_pause", "payload": payload})
    with pytest.raises(ValueError, match="approval_pause"):
        FaultPlan(target=target, mode="approval_pause", payload=payload)


def test_approval_pause_requires_durable_case_and_is_unique(catalog: CaseCatalog) -> None:
    raw = catalog.by_id("B7-09").model_dump(mode="python")
    raw["initial_state"]["execution_mode"] = "direct"
    with pytest.raises(ValidationError, match="approval_pause.*durable"):
        ConversationCase.model_validate(raw)

    raw = catalog.by_id("B7-09").model_dump(mode="python")
    raw["fault_injection"] = [*raw["fault_injection"], *raw["fault_injection"]]
    with pytest.raises(ValidationError, match="at most one approval_pause"):
        ConversationCase.model_validate(raw)


@pytest.mark.parametrize(
    ("mode", "target", "payload"),
    (
        ("approval_delay", "confirmation_clock", {"elapsed_seconds": 660}),
        ("approval_delay", "run_resume", {"elapsed_seconds": True}),
        ("approval_delay", "run_resume", {"elapsed_seconds": 660.0}),
        ("approval_delay", "run_resume", {"elapsed_seconds": "660"}),
        ("approval_delay", "run_resume", {"elapsed_seconds": 0}),
        ("approval_delay", "run_resume", {"elapsed_seconds": 660, "extra": True}),
        ("suspended_quote", "market_data", {"ts_code": "000001.SZ"}),
        ("suspended_quote", "paper_quote_provider", {"ts_code": "000001"}),
        ("suspended_quote", "paper_quote_provider", {"ts_code": 1}),
        (
            "suspended_quote",
            "paper_quote_provider",
            {"ts_code": "000001.SZ", "extra": True},
        ),
    ),
)
def test_dedicated_trade_faults_reject_invalid_config(
    mode: str,
    target: str,
    payload: dict[str, object],
) -> None:
    with pytest.raises((ValidationError, ValueError), match=mode):
        FaultSpec.model_validate({"target": target, "mode": mode, "payload": payload})
    with pytest.raises(ValueError, match=mode):
        FaultPlan(target=target, mode=mode, payload=payload)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("mode", "target", "payload"),
    (
        ("approval_delay", "run_resume", {"elapsed_seconds": 660}),
        ("suspended_quote", "paper_quote_provider", {"ts_code": "000001.SZ"}),
    ),
)
def test_dedicated_trade_faults_require_durable_case_and_are_unique(
    catalog: CaseCatalog,
    mode: str,
    target: str,
    payload: dict[str, object],
) -> None:
    raw = catalog.by_id("B6-06").model_dump(mode="python")
    raw["initial_state"]["execution_mode"] = "direct"
    raw["fault_injection"] = [{"target": target, "mode": mode, "payload": payload}]
    with pytest.raises(ValidationError, match=f"{mode}.*durable"):
        ConversationCase.model_validate(raw)

    raw["initial_state"]["execution_mode"] = "durable"
    raw["fault_injection"] *= 2
    with pytest.raises(ValidationError, match=f"at most one {mode}"):
        ConversationCase.model_validate(raw)


def test_b6_10_and_b6_18_use_real_gap_evidence_and_production_tools(
    catalog: CaseCatalog,
    production_chat_tools: frozenset[str],
) -> None:
    b610 = catalog.by_id("B6-10")
    b618 = catalog.by_id("B6-18")
    assert set(b610.available_tools) == {
        "lookup_ts_code",
        "check_order_eligibility",
        "get_paper_account",
        "place_paper_order",
    }
    assert set(b618.available_tools) == {
        "lookup_ts_code",
        "get_stock_quote",
        "check_order_eligibility",
        "place_paper_order",
    }
    assert set(b610.available_tools) | set(b618.available_tools) <= production_chat_tools
    assert [(item.target, item.mode, item.payload) for item in b610.fault_injection] == [
        ("run_resume", "approval_delay", {"elapsed_seconds": 660})
    ]
    assert [(item.target, item.mode, item.payload) for item in b618.fault_injection] == [
        ("paper_quote_provider", "suspended_quote", {"ts_code": "000001.SZ"})
    ]
    assert all("停牌" not in message for message in b618.user_messages)

    b610_assertions = _all_assertions(b610)
    assert any(
        item.source == "run"
        and item.operator == "greater_than"
        and item.path == "pauses.0.elapsed_seconds"
        and item.expected == 600
        for item in b610_assertions
    )
    b618_assertions = _all_assertions(b618)
    assert any(
        item.source == "tools"
        and item.path == "check_order_eligibility.last_call.result.allowed"
        and item.expected is True
        for item in b618_assertions
    )
    assert any(
        item.source == "tools"
        and item.path == "place_paper_order.last_call.status"
        and item.expected == "failed"
        for item in b618_assertions
    )
    assert all(
        item.path
        not in {
            "place_paper_order.last_call.error_code",
            "place_paper_order.last_call.error_message",
        }
        for item in b618_assertions
    )
    assert {
        assertion_id
        for component in b618.partial_credit
        for assertion_id in component.assertion_ids
    }.isdisjoint({"b618_place_error_code", "b618_place_error_message"})
    assert sum(component.points for component in b618.partial_credit) == 100

    forbidden_catalog_tokens = {
        "approval.invalidated_reason",
        "approval.status",
        "approval.expires_at",
        "eligibility.revalidated_after_expiry",
        "confirmations",
        "security_status",
        "permission_links",
        "resolve_security",
    }
    serialized = json.dumps(
        [b610.model_dump(mode="json"), b618.model_dump(mode="json")],
        ensure_ascii=False,
    )
    for token in forbidden_catalog_tokens:
        assert token not in serialized


def test_b6_06_does_not_score_environment_constant_permission_link_count(
    catalog: CaseCatalog,
) -> None:
    case = catalog.by_id("B6-06")

    assert all(
        not (item.source == "database" and item.path == "after.permission_links.count")
        for item in _all_assertions(case)
    )
    assert all(
        "b606_permission_links_zero" not in component.assertion_ids
        for component in case.partial_credit
    )


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
    assert has_assertion("run", "equals", "outcome.code", "action_required")
    assert has_assertion("database", "equals", "after.orders.count", 0)
    assert has_assertion(
        "run",
        "contains",
        "outcome.payload.resume_hint",
        "新的一轮对话",
    )
    assert has_assertion(
        "run",
        "contains",
        "outcome.payload.resume_hint",
        "重新核验权限",
    )
    assert has_assertion(
        "run",
        "equals",
        "outcome.payload.action_url",
        "/market-permissions/chinext/apply",
    )
    assert not has_assertion(
        "run",
        "equals",
        "action_required.permission_application_link_scheme",
        "https",
    )
    assert any(
        item.source == "run"
        and item.operator == "contains"
        and item.path == "outcome.payload.action_url"
        and item.expected == "https://"
        for item in case.forbidden_outcomes
    )


def test_b8_05_checks_each_leg_with_real_production_tools(catalog: CaseCatalog) -> None:
    case = catalog.by_id("B8-05")
    assertions = _all_assertions(case)

    assert set(case.available_tools) == {
        "check_order_eligibility",
        "get_entitlement_application_link",
        "get_market_entitlements",
        "place_paper_order",
    }
    assert not case.fault_injection
    assert any(
        item.source == "tools"
        and item.operator == "ordered_subsequence"
        and item.path == "called"
        and item.expected
        == [
            "check_order_eligibility",
            "check_order_eligibility",
            "get_entitlement_application_link",
        ]
        for item in assertions
    )
    expected_call_arguments = {
        "check_order_eligibility.calls.0.arguments.ts_code": "600519.SH",
        "check_order_eligibility.calls.0.arguments.side": "buy",
        "check_order_eligibility.calls.1.arguments.ts_code": "300750.SZ",
        "check_order_eligibility.calls.1.arguments.side": "buy",
        "get_entitlement_application_link.last_call.arguments.market": "chinext",
    }
    assert {
        item.path: item.expected
        for item in assertions
        if item.source == "tools" and item.path in expected_call_arguments
    } == expected_call_arguments
    expected_call_results = {
        "check_order_eligibility.calls.0.result.allowed": True,
        "check_order_eligibility.calls.0.result.required_permission": "main",
        "check_order_eligibility.calls.1.result.allowed": False,
        "check_order_eligibility.calls.1.result.required_permission": "chinext",
    }
    assert {
        item.path: item.expected
        for item in assertions
        if item.source == "tools" and item.path in expected_call_results
    } == expected_call_results
    forbidden_by_id = {item.assertion_id: item for item in case.forbidden_outcomes}
    partial_order = forbidden_by_id["b8_05_bad_partial_buy_mt"]
    assert (
        partial_order.source,
        partial_order.operator,
        partial_order.path,
        partial_order.expected,
    ) == ("database", "equals", "after.orders.count", 1)
    assert "b8_05_bad_partial_buy_mt_symbol" not in forbidden_by_id
    state_changes = {item.assertion_id: item.path for item in case.expected_state_changes}
    assert state_changes["b8_05_cash_unchanged"] == "funds"


def test_b8_05_assertions_only_use_real_durable_observation_paths(
    catalog: CaseCatalog,
) -> None:
    case = catalog.by_id("B8-05")
    actual = {
        (item.source, item.path)
        for item in _all_assertions(case)
        if item.source in {"run", "evidence", "tools"}
    }

    assert actual == {
        ("run", "status"),
        ("run", "pauses"),
        ("run", "outcome.code"),
        ("run", "outcome.payload.action_url"),
        ("run", "outcome.payload.resume_hint"),
        ("tools", "called"),
        ("tools", "check_order_eligibility.calls.0.arguments.ts_code"),
        ("tools", "check_order_eligibility.calls.0.arguments.side"),
        ("tools", "check_order_eligibility.calls.0.result.allowed"),
        ("tools", "check_order_eligibility.calls.0.result.required_permission"),
        ("tools", "check_order_eligibility.calls.1.arguments.ts_code"),
        ("tools", "check_order_eligibility.calls.1.arguments.side"),
        ("tools", "check_order_eligibility.calls.1.result.allowed"),
        ("tools", "check_order_eligibility.calls.1.result.required_permission"),
        ("tools", "get_entitlement_application_link.last_call.arguments.market"),
    }


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
    assert ("tools", "contains", "call_sequence", "get_stock_quote") in b508_guards
    assert ("answer", "contains", "text", "宁德时代") in b508_guards
    assert ("judge", "equals", "research_answer_relevant", "True") in b508_guards

    b507 = catalog.by_id("B5-07")
    assert any(
        item.path == "asks_which_pingan_without_inventing_codes"
        for item in b507.required_assertions
    )
    b509 = catalog.by_id("B5-09")
    b509_paths = {item.path for item in _all_assertions(b509)}
    assert {
        "after.watchlist.by_code.000063_SZ.note",
        "after.watchlist.by_code.000063_SZ.monitoring_enabled",
        "watchlist.by_code.000063_SZ.name",
    } <= b509_paths
    assert all(not path.startswith("concurrency.") for path in b509_paths)
    b509_patch_guards = {
        (item.operator, item.path, item.expected)
        for item in b509.required_assertions
        if item.source == "tools"
    }
    assert {
        ("equals", "manage_watchlist.calls.0.arguments.action", "update"),
        ("equals", "manage_watchlist.calls.0.arguments.ts_code", "000063.SZ"),
        ("equals", "manage_watchlist.calls.0.arguments.note", "等半年报"),
        ("absent", "manage_watchlist.calls.0.arguments.monitoring_enabled", None),
        ("equals", "manage_watchlist.calls.1.arguments.action", "update"),
        ("equals", "manage_watchlist.calls.1.arguments.ts_code", "000063.SZ"),
        ("equals", "manage_watchlist.calls.1.arguments.monitoring_enabled", True),
        ("absent", "manage_watchlist.calls.1.arguments.note", None),
    } <= b509_patch_guards
    b509_deterministic_ids = {
        assertion_id
        for grader in b509.graders
        if grader.type == "deterministic"
        for assertion_id in grader.assertion_ids
    }
    assert {
        "b509_first_action",
        "b509_first_ts_code",
        "b509_first_note",
        "b509_first_monitor_absent",
        "b509_second_action",
        "b509_second_ts_code",
        "b509_second_monitor",
        "b509_second_note_absent",
    } <= b509_deterministic_ids
    b509_scored_ids = {
        assertion_id
        for component in b509.partial_credit
        if component.name_zh == "顺序参数与最终字段"
        for assertion_id in component.assertion_ids
    }
    assert {
        "b509_first_action",
        "b509_first_ts_code",
        "b509_first_note",
        "b509_first_monitor_absent",
        "b509_second_action",
        "b509_second_ts_code",
        "b509_second_monitor",
        "b509_second_note_absent",
    } <= b509_scored_ids

    b510 = catalog.by_id("B5-10")
    assert b510.fault_injection[0].payload == {
        "match_arguments": {"action": "add", "ts_code": "002415.SZ"},
        "apply_on_attempts": [1],
    }

    b601 = catalog.by_id("B6-01")
    required_paths = {item.path for item in _all_assertions(b601)}
    assert {
        "pauses.0.original.ts_code",
        "pauses.0.original.side",
        "pauses.0.original.quantity",
        "pauses.0.original.order_type",
        "pauses.0.original.quote_as_of",
        "pauses.0.original.estimated_amount",
        "pauses.0.original.estimated_fee",
        "after.orders.count",
        "after.orders.latest.quantity",
        "after.orders.latest.order_type",
    } <= required_paths
    assert not b601.fault_injection

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
    assert all(not path.startswith("claims.") for path in b604_paths)
    for market in ("main_board", "gem", "star_market", "bse"):
        assert f"b604_{market}_status_answer_quality" in b604_paths

    b808 = catalog.by_id("B8-08")
    assert "turn_schedule" not in b808.initial_state.business_state
    assert any(
        item.path == "privacy.answer_and_actions_only_cover_current_user"
        for item in b808.required_assertions
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


def test_loader_rejects_tampered_case_data_even_when_schema_remains_valid(
    tmp_path: Path,
) -> None:
    source_dir = CaseCatalog.default_root()
    copied = tmp_path / "v1"
    copied.mkdir()
    for source in source_dir.glob("*"):
        (copied / source.name).write_bytes(source.read_bytes())

    batch_path = copied / "batch-1.jsonl"
    batch_path.write_text(
        batch_path.read_text("utf-8").replace("B1-01", "B1-99", 1),
        encoding="utf-8",
    )

    with pytest.raises(CaseCatalogError, match="case_data_sha256"):
        load_catalog(copied / "catalog.json")


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
