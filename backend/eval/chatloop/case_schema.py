"""Strict, versioned contracts for conversational business evaluation cases."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StrictBool, model_validator

__all__ = [
    "AcceptableOutcome",
    "ActorSpec",
    "AssertionSpec",
    "ConversationCase",
    "EnvironmentInput",
    "EvidenceRequirements",
    "FaultSpec",
    "GraderSpec",
    "ScoreComponent",
    "SuiteType",
    "validate_approval_delay_fault",
    "validate_approval_pause_fault",
    "validate_order_alias",
    "validate_suspended_quote_fault",
]


_ORDER_ALIAS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_TS_CODE_PATTERN = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")


def validate_approval_delay_fault(target: Any, payload: Any) -> int:
    if target != "run_resume":
        raise ValueError("approval_delay target must be run_resume")
    if type(payload) is not dict or set(payload) != {"elapsed_seconds"}:
        raise ValueError("approval_delay payload must contain exactly elapsed_seconds")
    elapsed_seconds = payload["elapsed_seconds"]
    if type(elapsed_seconds) is not int or elapsed_seconds <= 0:
        raise ValueError("approval_delay elapsed_seconds must be a positive strict integer")
    return elapsed_seconds


def validate_suspended_quote_fault(target: Any, payload: Any) -> str:
    if target != "paper_quote_provider":
        raise ValueError("suspended_quote target must be paper_quote_provider")
    if type(payload) is not dict or set(payload) != {"ts_code"}:
        raise ValueError("suspended_quote payload must contain exactly ts_code")
    ts_code = payload["ts_code"]
    if type(ts_code) is not str or _TS_CODE_PATTERN.fullmatch(ts_code) is None:
        raise ValueError("suspended_quote ts_code must be a canonical security code")
    return ts_code


def validate_order_alias(value: Any) -> str:
    if type(value) is not str or _ORDER_ALIAS_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "order alias must be 1-64 ASCII letters, digits, dots, underscores, or hyphens"
        )
    return value


def validate_approval_pause_fault(
    target: Any,
    payload: Any,
) -> tuple[str, int]:
    if target != "paper_settlement":
        raise ValueError("approval_pause target must be paper_settlement")
    if type(payload) is not dict or set(payload) != {"order_alias", "fill_quantity"}:
        raise ValueError(
            "approval_pause payload must contain exactly order_alias and fill_quantity"
        )
    try:
        alias = validate_order_alias(payload["order_alias"])
    except ValueError as exc:
        raise ValueError(f"approval_pause {exc}") from exc
    quantity = payload["fill_quantity"]
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("approval_pause fill_quantity must be a positive strict integer")
    return alias, quantity


class _StrictModel(BaseModel):
    """Base contract that rejects undeclared catalog fields."""

    model_config = ConfigDict(extra="forbid")


class AssertionSpec(_StrictModel):
    """A machine-checkable assertion over trial evidence."""

    assertion_id: str = Field(description="断言的唯一标识，用于评分器和证据关联")
    source: Literal["run", "tools", "database", "answer", "evidence", "judge"] = Field(
        description="执行断言时读取的数据来源"
    )
    operator: Literal[
        "equals",
        "not_equals",
        "exists",
        "absent",
        "unchanged",
        "contains",
        "not_contains",
        "count_equals",
        "greater_than",
        "ordered_subsequence",
        "subset",
    ] = Field(description="对实际值和期望值执行的比较操作")
    path: str = Field(default="", description="在断言数据来源中定位目标值的路径")
    expected: Any = Field(default=None, description="断言成立时应满足的期望值")
    policy_id: str | None = Field(default=None, description="断言关联的业务或安全策略标识")
    severity: Literal["C0", "C1", "C2", "C3", "Q"] | None = Field(
        default=None, description="断言失败时记录的违规级别或质量级别"
    )
    escalation_rule_ids: list[str] = Field(
        default_factory=list,
        description="该断言违规时确定触发的政策严重性升级规则编号列表",
    )

    @model_validator(mode="after")
    def validate_semantic_judge_path(self) -> AssertionSpec:
        if self.source == "judge" and self.operator != "absent" and not self.path.strip():
            raise ValueError("judge assertion path must be non-empty")
        return self


class ActorSpec(_StrictModel):
    """An actor participating in a trial."""

    role: Literal["creator", "other_user", "tenant_admin", "anonymous"] = Field(
        description="参与者在评估场景中的身份角色"
    )
    tenant_scope: Literal["same", "other", "none"] = Field(
        default="same", description="参与者与目标业务数据的租户关系"
    )


class FaultSpec(_StrictModel):
    """A controlled fault injected only by evaluation infrastructure."""

    target: str = Field(description="需要注入故障的工具、服务或传输目标")
    mode: Literal[
        "timeout",
        "error",
        "stale",
        "conflict",
        "approval_pause",
        "approval_delay",
        "suspended_quote",
        "response_lost_after_commit",
        "duplicate_approval_resume",
    ] = Field(description="评估环境注入的故障模式")
    payload: dict[str, Any] = Field(default_factory=dict, description="故障模式所需的附加参数")

    @model_validator(mode="after")
    def validate_approval_pause(self) -> FaultSpec:
        if self.mode == "approval_pause":
            validate_approval_pause_fault(self.target, self.payload)
        elif self.mode == "approval_delay":
            validate_approval_delay_fault(self.target, self.payload)
        elif self.mode == "suspended_quote":
            validate_suspended_quote_fault(self.target, self.payload)
        return self


class GraderSpec(_StrictModel):
    """A grader and the assertions assigned to it."""

    type: Literal["deterministic", "judge", "human_review"] = Field(
        description="评分方式，分别表示确定性规则、模型裁判或人工复核"
    )
    assertion_ids: list[str] = Field(description="由该评分器负责判定的断言标识列表")
    rubric_id: str | None = Field(default=None, description="模型裁判或人工复核使用的评分规则标识")


class ScoreComponent(_StrictModel):
    """A partial-credit component in a case score."""

    name_zh: str = Field(description="部分得分项的中文名称")
    points: int = Field(strict=True, ge=0, le=100, description="该得分项分值，范围为零到一百分")
    assertion_ids: list[str] = Field(
        default_factory=list, description="决定该得分项是否获得的断言标识列表"
    )


class EvidenceRequirements(_StrictModel):
    """Evidence artifacts that a valid trial must preserve."""

    transcript: StrictBool = Field(description="是否必须保存完整对话记录")
    tool_ledger: StrictBool = Field(description="是否必须保存工具调用账本")
    database_before_after: StrictBool = Field(description="是否必须保存数据库前后状态快照")
    versions: StrictBool = Field(description="是否必须保存模型、代码和策略版本信息")
    cost_latency: StrictBool = Field(default=True, description="是否必须保存成本和延迟数据")


_AxisName = Literal[
    "E1",
    "E2",
    "E3",
    "E4",
    "E5",
    "E6",
    "E7",
    "E8",
    "E9",
    "E10",
    "E11",
    "E12",
    "E13",
    "E14",
]


class EnvironmentInput(_StrictModel):
    """Initial environment and business state for one catalog case."""

    execution_mode: Literal["direct", "durable"] = Field(
        description="场景使用直接执行还是持久化任务执行模式"
    )
    actors: dict[str, ActorSpec] = Field(description="按场景内名称索引的参与者配置")
    axes: dict[_AxisName, Any] = Field(description="场景在 E1 到 E14 评估维度上的取值")
    business_state: dict[str, Any] = Field(description="试验开始前需要准备的业务状态")


class AcceptableOutcome(_StrictModel):
    """One acceptable way for the Agent to complete a case."""

    name_zh: str = Field(description="可接受结果的中文名称")
    assertions: list[AssertionSpec] = Field(description="证明该结果可接受的断言列表")


class SuiteType(StrEnum):
    """Lifecycle stage of an evaluation case."""

    CAPABILITY = "Capability"
    REGRESSION = "Regression"


class ConversationCase(_StrictModel):
    """Source-of-truth schema for a version-one conversational business case."""

    schema_version: Literal[1] = Field(description="业务评估用例格式版本，当前固定为一")
    case_id: str = Field(description="业务评估用例的唯一标识")
    title_zh: str = Field(description="便于评审人员阅读的用例中文标题")
    task_type: str = Field(description="用例覆盖的业务任务类型")
    suite_type: SuiteType = Field(
        default=SuiteType.CAPABILITY, description="用例所属的能力集或回归集"
    )
    risk_level: Literal["低风险", "中风险", "高风险", "最高风险"] = Field(
        description="用例描述的中文业务风险等级，不代表违规分数上限"
    )
    user_goal: str = Field(description="用户希望通过本次对话完成的真实业务目标")
    user_messages: list[str] = Field(description="按发送顺序排列的用户消息列表")
    initial_state: EnvironmentInput = Field(description="试验开始前的环境和业务输入")
    hidden_facts: dict[str, Any] = Field(description="评估器知道但不会直接告诉 Agent 的标准事实")
    available_tools: list[str] = Field(description="本用例允许向 Agent 暴露的工具名称列表")
    fault_injection: list[FaultSpec] = Field(description="本用例要求注入的可控故障列表")
    applicable_policies: list[str] = Field(description="本用例需要遵守的策略标识列表")
    acceptable_outcomes: list[AcceptableOutcome] = Field(
        description="业务上可以接受的结果及其断言列表"
    )
    required_assertions: list[AssertionSpec] = Field(description="任务通过必须满足的断言列表")
    forbidden_outcomes: list[AssertionSpec] = Field(
        description="任何情况下都不得出现的结果断言列表"
    )
    expected_state_changes: list[AssertionSpec] = Field(
        description="任务完成后预期发生或保持不变的状态断言列表"
    )
    answer_requirements: list[str] = Field(description="最终回答必须满足的内容要求列表")
    allowed_variations: list[str] = Field(description="不影响任务通过的允许变化列表")
    graders: list[GraderSpec] = Field(description="本用例使用的评分器配置列表")
    partial_credit: list[ScoreComponent] = Field(description="任务未完全通过时的部分得分规则")
    violation_caps: dict[str, Literal["C0", "C1", "C2", "C3"]] = Field(
        description="按策略标识配置的违规得分上限"
    )
    trial_count: PositiveInt = Field(
        default=1, strict=True, description="该用例计划重复执行的正整数次数"
    )
    trial_status: None = Field(default=None, description="目录中固定为空的试验有效性结果字段")
    task_pass: None = Field(default=None, description="目录中固定为空的任务通过结果字段")
    task_score: None = Field(default=None, description="目录中固定为空的任务得分结果字段")
    failure_reason: None = Field(default=None, description="目录中固定为空的任务失败原因字段")
    evidence: EvidenceRequirements = Field(description="有效试验必须保存的证据要求")

    @model_validator(mode="after")
    def validate_policy_branches_and_grader_sources(self) -> ConversationCase:
        if any(
            assertion.policy_id is not None or assertion.severity is not None
            for outcome in self.acceptable_outcomes
            for assertion in outcome.assertions
        ):
            raise ValueError(
                "acceptable_outcomes cannot carry policy caps; "
                "move common policy assertions to required or expected assertions"
            )

        assertions = [
            *self.required_assertions,
            *self.forbidden_outcomes,
            *self.expected_state_changes,
            *[
                assertion
                for outcome in self.acceptable_outcomes
                for assertion in outcome.assertions
            ],
        ]
        source_by_id = {assertion.assertion_id: assertion.source for assertion in assertions}
        for grader in self.graders:
            for assertion_id in grader.assertion_ids:
                source = source_by_id.get(assertion_id)
                if source is None:
                    continue
                if (source == "judge") != (grader.type == "judge"):
                    raise ValueError(
                        "judge assertions must be owned only by judge graders, "
                        f"but {assertion_id!r} uses source={source!r} "
                        f"with grader={grader.type!r}"
                    )
        return self

    @model_validator(mode="after")
    def validate_approval_pause_case_scope(self) -> ConversationCase:
        for mode in ("approval_pause", "approval_delay", "suspended_quote"):
            dedicated = [fault for fault in self.fault_injection if fault.mode == mode]
            if len(dedicated) > 1:
                raise ValueError(f"at most one {mode} fault is allowed per case")
            if dedicated and self.initial_state.execution_mode != "durable":
                raise ValueError(f"{mode} requires execution_mode=durable")
        return self
