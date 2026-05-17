"""AblationRunner — 跑 4 variant × cases 矩阵 (spec § 4.7)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval.dd_report.ablation.variants import (
    AblationVariant,
    build_pipeline_for_variant,
)
from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner, CaseType
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.metrics.base import MetricRegistry


@dataclass
class AblationRunResult:
    """单个 (variant × case) 的运行结果."""

    variant: str
    case_id: str
    run_id: str
    status: str  # "completed" | "failed"
    error: str | None = None


@dataclass
class AblationRunner:
    """跑 4 variant × cases 矩阵, 每 (variant, case) 一次 backtest run."""

    swapper: LLMSwapper
    tushare_inner: Any
    kb_inner: Any
    db_path: Path
    production_factory: Callable[..., Any]
    metric_registry: MetricRegistry = field(default_factory=lambda: MetricRegistry([]))
    ground_truth_loader: Any | None = None
    kb_lookup: Any | None = None
    enable_leak_detection: bool = False

    def run_ablation(
        self,
        cases: list[BacktestCase],
        variants: list[AblationVariant],
        evaluator_llm: str,
        git_sha: str,
        case_type: CaseType = "backtest",
    ) -> list[AblationRunResult]:
        """跑笛卡尔积 variant × case, 每次 BacktestRunner 用对应 variant 装配 pipeline.

        失败 (variant, case) 不中断后续 case — error 记录在 AblationRunResult.error,
        BacktestRunner 内部已写 status=failed 行到 backtest_runs (per T2.7 finally).
        """
        results: list[AblationRunResult] = []
        for variant in variants:
            pipeline_adapter = build_pipeline_for_variant(
                variant,
                production_factory=self.production_factory,
            )
            runner = BacktestRunner(
                swapper=self.swapper,
                tushare_inner=self.tushare_inner,
                kb_inner=self.kb_inner,
                db_path=self.db_path,
                pipeline=pipeline_adapter,
                metric_registry=self.metric_registry,
                ground_truth_loader=self.ground_truth_loader,
                kb_lookup=self.kb_lookup,
                enable_leak_detection=self.enable_leak_detection,
            )
            for case in cases:
                try:
                    run_id = runner.run_one(
                        case=case,
                        evaluator_llm=evaluator_llm,
                        ablation_variant=variant.value,
                        git_sha=git_sha,
                        case_type=case_type,
                    )
                    results.append(
                        AblationRunResult(
                            variant=variant.value,
                            case_id=case.case_id,
                            run_id=run_id,
                            status="completed",
                        )
                    )
                except Exception as e:
                    results.append(
                        AblationRunResult(
                            variant=variant.value,
                            case_id=case.case_id,
                            run_id="-",
                            status="failed",
                            error=str(e)[:200],
                        )
                    )
        return results
