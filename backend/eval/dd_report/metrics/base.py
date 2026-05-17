"""MetricProtocol + MetricInputs + MetricRegistry — Phase 2 T2.0.

每个 metric 是个 stateless 对象, 实现 MetricProtocol.compute(inputs) -> MetricResult。
所有 metric 共享同一个 MetricInputs (报告 + case 元数据 + 各种依赖注入)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader
from eval.dd_report.llm_swapper import EvaluatorClient
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


@dataclass(frozen=True)
class MetricResult:
    """单个 metric 计算结果."""

    name: str
    value: float | None  # 0-1 主指标 (M5 可能 0-10)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseMeta:
    case_id: str
    ts_code: str
    target_name: str
    cut_off_date: date


@dataclass
class MetricInputs:
    """所有 metric 共享的输入 bundle (依赖注入).

    None 字段表示该 metric 不需要这个依赖时可以传 None。
    """

    report: dict[str, Any]  # InvestmentDueDiligenceReport.model_dump() 形态
    case_meta: CaseMeta
    ground_truth: GroundTruthLoader | None
    tushare_adapter: TushareBacktestAdapter | None
    kb_lookup: Callable[[str], dict[str, Any] | None] | None  # chunk_id -> chunk
    evaluator_clients: dict[str, EvaluatorClient]  # "gpt-4o-2024-05-13": client, ...


class MetricProtocol(Protocol):
    """A metric: name + compute(inputs)."""

    name: str

    def compute(self, inputs: MetricInputs) -> MetricResult: ...


@dataclass
class MetricRegistry:
    """串行执行注册的 metric, 返回 MetricResult list."""

    metrics: list[MetricProtocol]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for m in self.metrics:
            if m.name in seen:
                raise ValueError(f"duplicate metric name {m.name!r}")
            seen.add(m.name)

    def compute_all(self, inputs: MetricInputs) -> list[MetricResult]:
        """Compute all metrics; callers MUST filter MetricResult.value is None before aggregating (M4 returns None when post-cut-off data is absent)."""
        return [m.compute(inputs) for m in self.metrics]
