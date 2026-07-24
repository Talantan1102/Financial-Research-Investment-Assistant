"""场景规格 schema + loader(blueprint § 5.1)。

扩 ``eval.tool_selection._core.GoldenCase`` 的字段语义,补 blueprint 承重项:
difficulty(难度档)/ persona(用户风格)/ policy_refs(挂的政策)/ expected_answer
(grounding 用:expect_abstain + must_ground_on)。

``Scenario.to_ts_case()`` 投影回 tool_selection.GoldenCase —— 行为①②③ 直接复用
tool_selection 的确定性 scorer,零重写。

jsonl 行格式(``//`` 注释行跳过):
    {"case_id": "cl-001", "category": "single_tool",
     "user_input": "茅台现在多少钱啊", "expected": {"first_tool": "get_stock_quote",
     "args_contains": {"ts_code": "600519.SH"}}, "bucket": "金融数据",
     "difficulty": "直球", "persona": "...", "policy_refs": ["路由公开"],
     "expected_answer": {"expect_abstain": false, "must_ground_on": ["现价"]}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from eval.tool_selection._core import _EXPECTED_KEYS, VALID_BUCKETS, GoldenCase

VALID_DIFFICULTY: tuple[str, ...] = ("直球", "自然难", "对抗")


@dataclass(frozen=True)
class Scenario:
    """单条评测场景。expected 至少含一键(行为①②③);expected_answer 可选(行为④)。"""

    case_id: str
    category: str
    user_input: str
    expected: dict[str, Any]
    bucket: str
    difficulty: str
    persona: str | None = None
    policy_refs: list[str] = field(default_factory=list)
    expected_answer: dict[str, Any] | None = None
    intent_goal: str | None = None  # 多轮:模拟用户的总目标(逐轮挤牙膏达成)
    interaction: dict[str, Any] | None = None

    @property
    def outcome(self) -> dict[str, Any] | None:
        value = self.expected.get("outcome")
        return value if isinstance(value, dict) else None

    def to_ts_case(self) -> GoldenCase:
        """投影成 tool_selection.GoldenCase —— 复用其 score_case(行为①②③)。"""
        return GoldenCase(
            case_id=self.case_id,
            category=self.category,
            user_input=self.user_input,
            expected=self.expected,
            bucket=self.bucket,
            skill=None,
        )

    @property
    def expects_abstain_answer(self) -> bool:
        """grounding 维度:本例期望回答弃答(无证据/假前提)。"""
        return bool(self.expected_answer and self.expected_answer.get("expect_abstain"))

    @property
    def is_grounding_case(self) -> bool:
        return self.expected_answer is not None


def _fail(msg: str) -> NoReturn:
    raise ValueError(f"chatloop 场景校验失败: {msg}")


def _validate(raw: dict[str, Any], seen: set[str]) -> Scenario:
    for key in ("case_id", "category", "user_input", "expected", "bucket", "difficulty"):
        if key not in raw:
            _fail(f"缺失必填字段 {key!r}: {raw!r}")

    case_id = raw["case_id"]
    if not isinstance(case_id, str) or not case_id.strip():
        _fail(f"case_id 须为非空字符串: {raw!r}")
    if case_id in seen:
        _fail(f"case_id 重复: {case_id!r}")

    expected = raw["expected"]
    if not isinstance(expected, dict) or not [k for k in _EXPECTED_KEYS if k in expected]:
        _fail(f"{case_id}: expected 须为对象且至少含一键 {_EXPECTED_KEYS!r}")

    if raw["bucket"] not in VALID_BUCKETS:
        _fail(f"{case_id}: bucket {raw['bucket']!r} 不在枚举 {VALID_BUCKETS!r}")
    if raw["difficulty"] not in VALID_DIFFICULTY:
        _fail(f"{case_id}: difficulty {raw['difficulty']!r} 不在枚举 {VALID_DIFFICULTY!r}")
    if not isinstance(raw["user_input"], str) or not raw["user_input"].strip():
        _fail(f"{case_id}: user_input 须为非空字符串")

    ea = raw.get("expected_answer")
    if ea is not None and not isinstance(ea, dict):
        _fail(f"{case_id}: expected_answer 须为对象或省略")
    outcome = expected.get("outcome")
    interaction = raw.get("interaction")
    if outcome is not None:
        _validate_outcome(case_id, outcome, interaction)

    seen.add(case_id)
    return Scenario(
        case_id=case_id,
        category=str(raw["category"]),
        user_input=raw["user_input"],
        expected=expected,
        bucket=raw["bucket"],
        difficulty=raw["difficulty"],
        persona=raw.get("persona"),
        policy_refs=list(raw.get("policy_refs") or []),
        expected_answer=ea,
        intent_goal=raw.get("intent_goal"),
        interaction=interaction,
    )


def _validate_outcome(case_id: str, outcome: Any, interaction: Any) -> None:
    if not isinstance(outcome, dict):
        _fail(f"{case_id}: outcome 须为对象")
    if outcome.get("version") != 1:
        _fail(f"{case_id}: outcome.version 只支持 1")
    if outcome.get("type") not in {"paper_trading", "watchlist"}:
        _fail(f"{case_id}: outcome.type 非法")
    required = (
        "expected_tools",
        "tool_args_contains",
        "risk_levels",
        "permission_decisions",
        "call_counts",
        "run",
        "database_assertions",
    )
    missing = [key for key in required if key not in outcome]
    if missing:
        _fail(f"{case_id}: outcome 缺失 {missing}")
    expected_tools = outcome["expected_tools"]
    tool_args = outcome["tool_args_contains"]
    risk_levels = outcome["risk_levels"]
    permission_decisions = outcome["permission_decisions"]
    call_counts = outcome["call_counts"]
    run = outcome["run"]
    database_assertions = outcome["database_assertions"]
    if not isinstance(expected_tools, list) or not expected_tools:
        _fail(f"{case_id}: outcome.expected_tools 须为非空数组")
    if not isinstance(tool_args, dict) or any(
        tool not in tool_args or not isinstance(tool_args[tool], dict)
        for tool in expected_tools
    ):
        _fail(f"{case_id}: outcome.tool_args_contains 必须覆盖 expected_tools")
    if not isinstance(risk_levels, dict) or any(tool not in risk_levels for tool in expected_tools):
        _fail(f"{case_id}: outcome.risk_levels 必须覆盖 expected_tools")
    if any(risk_levels[tool] not in {"low", "high"} for tool in expected_tools):
        _fail(f"{case_id}: outcome.risk_levels 仅支持 low/high")
    known_decisions = {"direct", "approval_required", "approved", "rejected"}
    if not isinstance(permission_decisions, dict) or any(
        tool not in permission_decisions
        or not isinstance(permission_decisions[tool], list)
        or not permission_decisions[tool]
        or any(
            not isinstance(decision, str) or decision not in known_decisions
            for decision in permission_decisions[tool]
        )
        for tool in expected_tools
    ):
        _fail(f"{case_id}: outcome.permission_decisions 必须覆盖 expected_tools")
    for tool in expected_tools:
        trajectory = permission_decisions[tool]
        if risk_levels[tool] == "low" and trajectory != ["direct"]:
            _fail(f"{case_id}: LOW 工具权限轨迹必须为 direct")
        if risk_levels[tool] == "high":
            decision = run.get("decision") if isinstance(run, dict) else None
            terminal = (
                "approved"
                if decision == "approved"
                else "rejected"
                if decision == "rejected"
                else None
            )
            if terminal is None or trajectory != ["approval_required", terminal]:
                _fail(f"{case_id}: HIGH 工具权限轨迹必须覆盖审批终态")
    write_tools = {
        "place_paper_order",
        "cancel_paper_order",
        "reset_paper_account",
        "manage_watchlist",
    }
    if not isinstance(call_counts, dict) or any(
        tool not in call_counts
        or not isinstance(call_counts[tool], dict)
        or type(call_counts[tool].get("min")) is not int
        or type(call_counts[tool].get("max")) is not int
        or not 1 <= call_counts[tool]["min"] <= call_counts[tool]["max"]
        or (
            tool in write_tools
            and not call_counts[tool]["min"] == call_counts[tool]["max"] == 1
        )
        for tool in expected_tools
    ):
        _fail(f"{case_id}: outcome.call_counts 必须覆盖工具并限制写工具为精确一次")
    if (
        not isinstance(run, dict)
        or "pause_type" not in run
        or "resumed" not in run
        or "status" not in run
        or run["pause_type"] not in {None, "input", "approval"}
        or type(run["resumed"]) is not bool
    ):
        _fail(f"{case_id}: outcome.run 必须明确 pause_type/resumed/status")
    if not isinstance(database_assertions, dict) or not database_assertions:
        _fail(f"{case_id}: outcome.database_assertions 须为非空对象")
    if run["pause_type"] == "approval":
        if not isinstance(interaction, dict):
            _fail(f"{case_id}: approval outcome 缺失 interaction")
        if interaction.get("pause_decision") not in {"approve", "reject"}:
            _fail(f"{case_id}: interaction.pause_decision 非法")
        expected_decision = {
            "approve": "approved",
            "reject": "rejected",
        }[interaction["pause_decision"]]
        if run.get("decision") != expected_decision:
            _fail(f"{case_id}: outcome.run.decision 与 interaction 不一致")
        edits = interaction.get("edited_arguments", {})
        if not isinstance(edits, dict):
            _fail(f"{case_id}: interaction.edited_arguments 须为对象")
        if interaction["pause_decision"] == "reject" and edits:
            _fail(f"{case_id}: reject interaction 不得编辑参数")


def load_scenarios(path: Path) -> list[Scenario]:
    """读 jsonl(``//`` 注释跳过),逐行 fail-loud。空集报错。"""
    if not path.exists():
        _fail(f"场景文件不存在: {path}")
    out: list[Scenario] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            _fail(f"第 {lineno} 行不是合法 JSON: {e}")
        if not isinstance(raw, dict):
            _fail(f"第 {lineno} 行须为对象")
        out.append(_validate(raw, seen))
    if not out:
        _fail(f"场景文件无有效 case: {path}")
    return out


__all__ = ["Scenario", "load_scenarios", "VALID_DIFFICULTY"]
