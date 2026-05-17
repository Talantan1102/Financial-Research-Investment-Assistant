"""M3 RiskPairingMetric — summarization LLM judge (spec § 4.2).

逻辑:
1. 遍历 RiskAssessment 4 桶 (market/growth/event/valuation)
2. 每个 RiskItem 检查 mitigations 非空 (paired)
3. 对 paired 的, LLM judge 判 mitigation 是否有效 (valid)
4. score = valid / total

注: vacuous case (total=0) returns 1.0. 同 M1 / M2, V1/V2 ablation stripped reports
缺 risk_assessment section 会 vacuous score; details["total"] 提供 traceability。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from eval.dd_report.metrics.base import MetricInputs, MetricResult


class PairingJudgeProtocol(Protocol):
    def is_valid_mitigation(
        self, risk_title: str, risk_desc: str, mitigations: list[str]
    ) -> bool: ...


_RISK_BUCKETS: tuple[str, ...] = (
    "market_risk",
    "growth_risk",
    "event_risk",
    "valuation_risk",
)


@dataclass
class RiskPairingMetric:
    name: str = "m3_risk_pairing"
    judge: PairingJudgeProtocol | None = None
    section_path: str = "risk_assessment"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if self.judge is None:
            raise ValueError("RiskPairingMetric requires a judge")
        sec = inputs.report.get(self.section_path)
        if not isinstance(sec, dict):
            return MetricResult(
                name=self.name,
                value=1.0,
                details={"total": 0, "paired": 0, "valid": 0, "unpaired": 0},
            )

        total = 0
        paired = 0
        valid = 0
        invalid_log: list[dict[str, Any]] = []
        unpaired_log: list[str] = []

        for bucket in _RISK_BUCKETS:
            for item in sec.get(bucket, []) or []:
                if not isinstance(item, dict):
                    continue
                total += 1
                title = item.get("title", "")
                desc = item.get("description", "")
                mits: list[str] = item.get("mitigations", []) or []
                if not mits:
                    unpaired_log.append(f"{bucket}:{title}")
                    continue
                paired += 1
                if self.judge.is_valid_mitigation(title, desc, mits):
                    valid += 1
                else:
                    invalid_log.append({"bucket": bucket, "title": title, "mits": mits})

        score = valid / total if total else 1.0
        return MetricResult(
            name=self.name,
            value=score,
            details={
                "total": total,
                "paired": paired,
                "valid": valid,
                "unpaired": total - paired,
                "invalid_mitigations": invalid_log[:10],
                "unpaired_risks": unpaired_log[:10],
            },
        )


class _EvaluatorPairingJudge:
    """Wraps EvaluatorClient.chat into PairingJudgeProtocol.

    Exported for T2.7 wire + T2.11 dogfood factory. Same pattern as
    citation_metric._EvaluatorJudge (T2.2 refactor sediment).
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def is_valid_mitigation(self, risk_title: str, risk_desc: str, mitigations: list[str]) -> bool:
        prompt = (
            f"判断下述风险的 mitigation 是否真能缓释该风险。\n\n"
            f"风险标题: {risk_title}\n风险描述: {risk_desc}\n"
            f"mitigation: {mitigations}\n\n"
            f'严格输出一行 JSON: {{"valid": true}} 或 {{"valid": false}}'
        )
        out = self._client.chat(prompt=prompt)
        return _parse_valid(out)


def _parse_valid(text: str) -> bool:
    """Parse {"valid": bool} JSON, fallback to substring match for robustness."""
    if not text:
        return False
    try:
        d = json.loads(text.strip())
        if isinstance(d, dict) and "valid" in d:
            return bool(d["valid"])
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    lo = text.lower()
    return '"valid": true' in lo or '"valid":true' in lo
