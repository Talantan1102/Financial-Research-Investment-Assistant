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

from app.agents.investment_dd_schema import OutlierDiagnosis
from app.agents.schemas import CriticDimension, CriticDimensionScore
from app.services.llm_service import LLMService

__all__ = ["ValuationConsistencyScorer"]


_CONSISTENT_KEYWORDS = ("一致", "吻合", "趋同", "接近")
_DIVERGENCE_KEYWORDS = ("偏离", "差异", "偏低", "偏高", "不一致")
_UNCERTAINTY_KEYWORDS = ("无法诊断", "不确定")


class ValuationConsistencyScorer:
    """Critic 第 7 维 scorer. Rule-based, sync API。

    本期不调 LLM(规则即可表达"narrative 是否反映 cross-check 信号");LLM DI
    接口预留(未来若需 LLM-as-judge 可换实现而不破契约)。
    """

    dimension: CriticDimension = "valuation_consistency"

    def __init__(self, *, llm: LLMService) -> None:
        # LLM kept for DI consistency with other scorers; not used in v1.x A5a
        self._llm = llm

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
