"""M5 CompositeJudgeMetric — multi-LLM consensus (spec § 4.3).

3 evaluator LLM 跑同一 rubric prompt, 各 1-10 打分, 取 majority(median)、mean、
disagreement(max - min)。
disagreement > 2 -> needs_audit
mean <= 4         -> low_quality (push 到 dogfood loop)

可重复性 (spec § 7.3): temperature=0 强制, 同 prompt 跑 3 次 majority 决策稳定 > 80%
— 测试在 conftest fixture + 单独 stress test (本 task 不实施, Phase 5 dogfood 时拉)。

partial-failure tolerance: 1 broken judge out of 3 不抛 (covers both client.chat()
exception AND unparseable response), 用 5.0 中性分代替 + parse_failures counter +1.
不同于 M1/M3 raise ValueError 的 silent-fail 防御 — M5 设计上需要 cross-LLM 共识,
失去 1 个 judge 不应整体 fail。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from statistics import median

from eval.dd_report.llm_swapper import EvaluatorClient
from eval.dd_report.metrics.base import MetricInputs, MetricResult

_PROMPT_TEMPLATE = """你是金融研究助手报告的评审员。给定下述 InvestmentDueDiligenceReport 内容,
按以下 5 维综合打 1-10 分(1=极差, 10=完美)。结合 factuality + coverage + structure +
investment thesis 合理性 + risk completeness。

报告标的: {target_name}
报告摘要 (JSON 截断 4000 字符): {report_json}

严格输出一行 JSON: {{"score": <1-10>, "reasoning": "<1 句话>"}}
"""

_DEFAULT_JUDGE_MODELS: tuple[str, ...] = (
    "gpt-4o-2024-05-13",
    "qwen2.5-72b-instruct",
    "deepseek-v3",
)

_DEFAULT_SCORE = 5.0
_AUDIT_THRESHOLD = 2.0
_LOW_QUALITY_THRESHOLD = 4.0


@dataclass
class CompositeJudgeMetric:
    name: str = "m5_composite"
    judge_models: tuple[str, ...] = _DEFAULT_JUDGE_MODELS
    audit_threshold: float = _AUDIT_THRESHOLD
    low_quality_threshold: float = _LOW_QUALITY_THRESHOLD

    def compute(self, inputs: MetricInputs) -> MetricResult:
        # 装配 (model, client) 对; 跳过缺失的 client 但保留正确的 label 配对
        resolved: list[tuple[str, EvaluatorClient]] = []
        for model in self.judge_models:
            client = inputs.evaluator_clients.get(model)
            if client is None:
                continue
            resolved.append((model, client))

        if len(resolved) < 3:
            raise ValueError(
                f"CompositeJudgeMetric needs at least 3 evaluator clients, got {len(resolved)}"
            )

        report_json = json.dumps(inputs.report, ensure_ascii=False)[:4000]
        prompt = _PROMPT_TEMPLATE.format(
            target_name=inputs.case_meta.target_name, report_json=report_json
        )

        raw_scores: list[dict[str, object]] = []
        parse_failures = 0
        scores_only: list[float] = []
        for model, client in resolved:
            try:
                out = client.chat(prompt=prompt)
            except Exception as exc:  # noqa: BLE001 — partial-failure tolerance spec § 4.3
                parse_failures += 1
                scores_only.append(_DEFAULT_SCORE)
                raw_scores.append(
                    {
                        "model": model,
                        "score": None,
                        "raw": f"<exception: {exc!r}>"[:200],
                    }
                )
                continue
            parsed = _parse_score(out)
            if parsed is None:
                parse_failures += 1
                scores_only.append(_DEFAULT_SCORE)
                raw_scores.append({"model": model, "score": None, "raw": out[:200]})
            else:
                scores_only.append(parsed["score"])  # type: ignore[arg-type]
                raw_scores.append(
                    {"model": model, "score": parsed["score"], "reasoning": parsed.get("reasoning")}
                )

        mean_score = sum(scores_only) / len(scores_only)
        majority = float(median(scores_only))
        disagreement_max = max(scores_only) - min(scores_only)

        return MetricResult(
            name=self.name,
            value=mean_score,
            details={
                "mean": mean_score,
                "majority": majority,
                "disagreement_max": disagreement_max,
                "needs_audit": disagreement_max > self.audit_threshold,
                "low_quality": mean_score <= self.low_quality_threshold,
                "per_judge": raw_scores,
                "parse_failures": parse_failures,
            },
        )


_SCORE_RE = re.compile(r'"score"\s*:\s*(\d+(?:\.\d+)?)')


def _parse_score(text: str) -> dict[str, object] | None:
    """从 LLM raw output parse {"score": int, "reasoning": str}, 容忍 markdown 围栏.

    Returns None when text is empty, unparseable, or score field missing —
    M5 caller handles None by treating as neutral 5.0 (不 raise; partial-failure
    tolerance differs from M1/M3 raise pattern).
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", cleaned, flags=re.MULTILINE)
    try:
        d = json.loads(cleaned)
        if isinstance(d, dict) and "score" in d:
            return {"score": float(d["score"]), "reasoning": d.get("reasoning")}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = _SCORE_RE.search(text)
    if m:
        return {"score": float(m.group(1)), "reasoning": None}
    return None
