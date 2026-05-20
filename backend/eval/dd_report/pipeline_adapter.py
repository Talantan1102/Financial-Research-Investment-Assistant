"""DDReportPipelineAdapter — 桥接 Phase 1 PipelineProtocol 和生产 ResearchAgent.

设计:
  pipeline_factory(tushare_adapter, kb_adapter, evaluator_client) -> Callable
  这个 Callable 接受 (target_name, target_ts_code) 并返回 InvestmentDueDiligenceReport。

为什么这样设计:
  - factory 让生产 ResearchAgent / writer / critic / orchestration 可以在装配阶段把
    swapped dependency (backtest adapter + evaluator client) 注入闭包, 而 run-time
    入口只接 case-level 参数 (target_name)。
  - 兼容 v0.8.5 现有形态: ResearchAgent 一般在 app.orchestration.* 里 build_graph(),
    factory 模式让 backtest 不重写 build_graph()。

T2.11 implementer note:
  - 生产入口: app/orchestration/research_graph.py::build_research_graph()
    接受 (planner, collector, analyst, writer, critic, *, checkpointer)。
  - InvestmentDueDiligenceReport 写回 app/router/research.py 的内存 cache (line ~267)
    并在 ResearchState.investment_report 中流转
    (app/orchestration/critic_subgraph.py, app/agents/writer.py)。
  - 真实 production_factory 应建在 app/eval/dd_report_production_factory.py,
    接受 tushare_adapter / kb_adapter / evaluator_client 并返回 runner callable。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.investment_dd_schema import InvestmentDueDiligenceReport


class _ProductionRunner(Protocol):
    def __call__(self, target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport: ...


class _PipelineFactoryProtocol(Protocol):
    def __call__(
        self, *, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any
    ) -> _ProductionRunner: ...


@dataclass
class DDReportPipelineAdapter:
    """Wrap 生产 pipeline factory 成 BacktestRunner.PipelineProtocol."""

    pipeline_factory: _PipelineFactoryProtocol

    def run(
        self,
        *,
        target_name: str,
        ts_code: str,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
    ) -> dict[str, Any]:
        runner = self.pipeline_factory(
            tushare_adapter=tushare_adapter,
            kb_adapter=kb_adapter,
            evaluator_client=evaluator_client,
        )
        report = runner(target_name=target_name, target_ts_code=ts_code)
        if not isinstance(report, InvestmentDueDiligenceReport):
            raise TypeError(f"expected InvestmentDueDiligenceReport, got {type(report).__name__}")
        return report.model_dump(mode="json")
