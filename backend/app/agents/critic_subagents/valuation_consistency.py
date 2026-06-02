"""v1.x A5a: Critic 第 7 维 — valuation_consistency rule-based scorer.

Rule-based(不调 LLM, deterministic)。评分根据 (valuation_consistency, outlier_diagnosis,
report_markdown) 三元决定:
  - None             → 10.0 skip
  - consistent       → 9.0 mention / 8.0 not mention
  - moderate         → 8.0 explanation / 4.0 not
  - severe + diag    → 9.0 referenced / 3.0 not
  - severe + no diag → 7.0 flagged / 4.0 not

阈值 < 7.0 触发 writer retry(Task 17 wire 进 graph)。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 9.2
"""

from __future__ import annotations

from typing import Literal

from app.agents.base import Agent
from app.agents.investment_dd_schema import OutlierDiagnosis
from app.agents.schemas import CriticDimension, CriticDimensionScore, ResearchState, StepResult
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

__all__ = ["ValuationConsistencyScorer"]


_CONSISTENT_KEYWORDS = ("一致", "吻合", "趋同", "接近")
_DIVERGENCE_KEYWORDS = ("偏离", "差异", "偏低", "偏高", "不一致")
_UNCERTAINTY_KEYWORDS = ("无法诊断", "不确定")


class ValuationConsistencyScorer(Agent):
    """Critic 第 7 维 scorer. Rule-based, sync API。

    本期不调 LLM(规则即可表达"narrative 是否反映 cross-check 信号");LLM DI
    接口预留(未来若需 LLM-as-judge 可换实现而不破契约)。

    Wire pattern(与其它 6 scorer 一致):
      - 继承 Agent (name + model_tier + step(state) -> StepResult)
      - step() 从 state.valuation_analysis 提取 (consistency, diagnosis),
        report_markdown 从 state.report_markdown,转发到内部 score(...) 方法
      - 内部 score(...) 公共签名保留供 10 个 unit test 直接调用(不破契约)
    """

    name = "ValuationConsistencyScorer"
    dimension: CriticDimension = "valuation_consistency"
    state_field = "valuation_consistency_score"
    # rule-based, 不调 LLM;Tier 字段仅满足 Agent ABC 契约
    model_tier: Tier = "fast"

    def __init__(self, *, llm: LLMService) -> None:
        # LLM kept for DI consistency with other scorers; not used in v1.x A5a
        super().__init__(llm)

    def step(self, state: ResearchState) -> StepResult:  # type: ignore[override]
        """Adapter for critic_subgraph fan-out.

        Reads multi-model cross-check signals from state.valuation_analysis
        (Analyst writes there; Writer post_process 拷到
        report.financial_analysis.valuation_analysis). 用 state.valuation_analysis
        而不是 investment_report.financial_analysis.valuation_analysis 是因为
        critic_subgraph 跑在 Writer 之后但用的是 ResearchState 不是 InvestmentDDReport,
        且 Analyst 写入的 state.valuation_analysis 是 Python 决定论 single
        source of truth。
        """
        va = state.valuation_analysis
        consistency = va.valuation_consistency if va is not None else None
        diagnosis = va.outlier_diagnosis if va is not None else None
        score = self.score(
            report_markdown=state.report_markdown or "",
            valuation_consistency=consistency,
            outlier_diagnosis=diagnosis,
            request_id=state.request_id,
        )
        return StepResult(
            state_update={self.state_field: score},
            span_metadata={
                "agent": self.name,
                "dimension": self.dimension,
                "consistency": consistency or "none",
                "has_diagnosis": diagnosis is not None,
            },
        )

    def score(
        self,
        *,
        report_markdown: str,
        valuation_consistency: Literal["consistent", "moderate", "severe"] | None,
        outlier_diagnosis: OutlierDiagnosis | None,
        request_id: str,
    ) -> CriticDimensionScore:
        if valuation_consistency is None:
            return CriticDimensionScore(
                dimension=self.dimension,
                score=10.0,
                evidence="single-lens skip (no cross-check applicable)",
                sub_agent_request_id=request_id,
                is_skip=True,  # C18: excluded from overall_score
            )

        if valuation_consistency == "consistent":
            mentioned = any(kw in report_markdown for kw in _CONSISTENT_KEYWORDS)
            return CriticDimensionScore(
                dimension=self.dimension,
                score=9.0 if mentioned else 8.0,
                evidence=(
                    "consistent + narrative 提及一致性"
                    if mentioned
                    else "consistent (narrative 未显式提一致性)"
                ),
                sub_agent_request_id=request_id,
            )

        if valuation_consistency == "moderate":
            mentioned = any(kw in report_markdown for kw in _DIVERGENCE_KEYWORDS)
            return CriticDimensionScore(
                dimension=self.dimension,
                score=8.0 if mentioned else 4.0,
                evidence=(
                    "moderate + narrative 解释偏离"
                    if mentioned
                    else "moderate (narrative 未提偏离原因)"
                ),
                sub_agent_request_id=request_id,
            )

        # severe
        if outlier_diagnosis is None:
            flagged = any(kw in report_markdown for kw in _UNCERTAINTY_KEYWORDS)
            return CriticDimensionScore(
                dimension=self.dimension,
                score=7.0 if flagged else 4.0,
                evidence=(
                    "severe + diagnosis 缺失,narrative flag 不确定"
                    if flagged
                    else "severe + diagnosis 缺失,narrative 也未 flag"
                ),
                sub_agent_request_id=request_id,
            )

        # severe + diagnosis exists
        referenced = outlier_diagnosis.narrative in report_markdown
        return CriticDimensionScore(
            dimension=self.dimension,
            score=9.0 if referenced else 3.0,
            evidence=(
                "severe + narrative 显式引用 diagnosis"
                if referenced
                else "severe + narrative 未引用 diagnosis (掩盖打架信号)"
            ),
            sub_agent_request_id=request_id,
        )
