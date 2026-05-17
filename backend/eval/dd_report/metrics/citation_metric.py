"""M1 CitationMetric — extraction precision/recall (spec § 4.2).

precision = chunks that LOOK UP + SUPPORT claim / total cited chunks
recall    = sections with non-empty evidence / total sections evaluated
value     = F1(precision, recall)

简化(spec § 4.2 v0):
- claim = section.narrative 整体 (atomic claim 拆解推到 v1.x)
- supports 判断 = LLM judge (本 metric 用小模型, 通过 SupportsJudgeProtocol 注入)
- 多 section micro avg (跨 section 累加 supports / total cited)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eval.dd_report.metrics.base import MetricInputs, MetricResult


class SupportsJudgeProtocol(Protocol):
    """小 LLM judge: chunk text 是否支持 claim."""

    def supports(self, claim: str, chunk_text: str) -> bool: ...


# 默认 6 section 路径 (InvestmentDueDiligenceReport)
DEFAULT_SECTION_PATHS: tuple[str, ...] = (
    "target_overview",
    "legal_qualification",
    "financial_analysis",
    "industry_analysis",
    "risk_assessment",
    "investment_recommendation",
)


@dataclass
class CitationMetric:
    name: str = "m1_citation"
    judge: SupportsJudgeProtocol | None = None
    section_paths: tuple[str, ...] = DEFAULT_SECTION_PATHS

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if self.judge is None:
            raise ValueError("CitationMetric requires a judge (SupportsJudgeProtocol)")
        if inputs.kb_lookup is None:
            raise ValueError("CitationMetric requires kb_lookup")

        total_cited = 0
        supports = 0
        lookup_failures = 0
        sections_with_evidence = 0
        failed_cite_log: list[str] = []
        unsupported_log: list[str] = []

        for path in self.section_paths:
            sec = inputs.report.get(path)
            if not isinstance(sec, dict):
                continue
            evidence: list[str] = sec.get("evidence") or []
            claim: str = sec.get("narrative", "")
            if evidence:
                sections_with_evidence += 1
            for chunk_id in evidence:
                total_cited += 1
                chunk: dict[str, Any] | None = inputs.kb_lookup(chunk_id)
                if chunk is None:
                    lookup_failures += 1
                    failed_cite_log.append(f"{path}:{chunk_id}")
                    continue
                if self.judge.supports(claim, chunk.get("text", "")):
                    supports += 1
                else:
                    unsupported_log.append(f"{path}:{chunk_id}")

        n_sections = sum(1 for p in self.section_paths if isinstance(inputs.report.get(p), dict))
        precision = supports / total_cited if total_cited else 1.0
        recall = sections_with_evidence / n_sections if n_sections else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return MetricResult(
            name=self.name,
            value=f1,
            details={
                "precision": precision,
                "recall": recall,
                "total_cited": total_cited,
                "supports": supports,
                "lookup_failures": lookup_failures,
                "sections_with_evidence": sections_with_evidence,
                "n_sections": n_sections,
                "failed_cites": failed_cite_log[:20],
                "unsupported_cites": unsupported_log[:20],
            },
        )
