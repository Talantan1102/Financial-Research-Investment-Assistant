"""M1 CitationMetric — extraction precision / citation_coverage (spec § 4.2).

precision         = chunks that look up AND judge confirms supports claim / total cited
citation_coverage = sections with non-empty evidence / total sections required
value             = F1(precision, citation_coverage)

NOTE on naming: spec § 4.2 calls the right-hand component "recall", but
implementation-wise it is a citation-coverage signal (only checks evidence list
is non-empty, does NOT invoke the judge), not IR-recall (would require atomic
claim decomposition + per-claim judge). The BacktestMetricScores schema field
is still named `m1_citation_recall` for spec consistency; T2.7 wires
`details["citation_coverage"]` into that field.

简化(spec § 4.2 v0):
- claim = section.narrative 整体 (atomic claim 拆解推到 v1.x)
- supports 判断 = LLM judge (本 metric 用小模型, 通过 SupportsJudgeProtocol 注入)
- 多 section micro avg (跨 section 累加 supports / total cited)
"""

from __future__ import annotations

import json
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
        judge_failures = 0
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
                try:
                    is_supported = self.judge.supports(claim, chunk.get("text", ""))
                except ValueError as e:
                    judge_failures += 1
                    unsupported_log.append(f"{path}:{chunk_id}:judge_error={str(e)[:80]}")
                    continue
                if is_supported:
                    supports += 1
                else:
                    unsupported_log.append(f"{path}:{chunk_id}")

        n_sections_present = sum(
            1 for p in self.section_paths if isinstance(inputs.report.get(p), dict)
        )
        n_sections_required = len(self.section_paths)
        precision = supports / total_cited if total_cited else 1.0
        citation_coverage = (
            sections_with_evidence / n_sections_required if n_sections_required else 1.0
        )
        f1 = (
            2 * precision * citation_coverage / (precision + citation_coverage)
            if (precision + citation_coverage) > 0
            else 0.0
        )

        return MetricResult(
            name=self.name,
            value=f1,
            details={
                "precision": precision,
                # T2.7 wire: m1_citation_recall = m1.details.get("citation_coverage", 1.0)
                "citation_coverage": citation_coverage,
                "total_cited": total_cited,
                "supports": supports,
                "lookup_failures": lookup_failures,
                "judge_failures": judge_failures,
                "sections_with_evidence": sections_with_evidence,
                "n_sections_present": n_sections_present,
                "n_sections_required": n_sections_required,
                "failed_cites": failed_cite_log[:20],
                "unsupported_cites": unsupported_log[:20],
            },
        )


class EvaluatorJudge:
    """Wraps EvaluatorClient.chat into SupportsJudgeProtocol.

    Exported for T2.7 wire + T2.11 dogfood factory. The prompt is intentionally
    minimal — the supports judgement is a simple binary classification.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def supports(self, claim: str, chunk_text: str) -> bool:
        prompt = (
            f"判断下述 chunk 内容是否支持声明。chunk 必须明确陈述声明的事实"
            f"或紧密相关的事实, 才算 'supports'。\n\n"
            f"声明: {claim}\n\nchunk: {chunk_text}\n\n"
            f'严格输出一行 JSON: {{"supports": true}} 或 {{"supports": false}}'
        )
        out = self._client.chat(prompt=prompt)
        return _parse_supports(out)


def _parse_supports(text: str) -> bool:
    """Parse {"supports": bool} JSON, fallback to substring match for robustness."""
    if not text:
        raise ValueError(
            "LLM judge returned empty response — likely auth/rate-limit/network failure"
        )
    try:
        d = json.loads(text.strip())
        if isinstance(d, dict) and "supports" in d:
            return bool(d["supports"])
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    lo = text.lower()
    return '"supports": true' in lo or '"supports":true' in lo
