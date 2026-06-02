"""v1.x A5a: cross-check consistency analyzer.

变异系数 CV = std / mean:
  CV < 15%   → consistent (lens 信号一致,narrative 可简明)
  15-30%     → moderate   (narrative 需解释偏离)
  > 30%      → severe     (触发 OutlierDiagnosisAgent + Writer 必须显式引用)

输入 dict[str, float] 形如 {"pe": 1500, "pb": 1550, "ev_ebitda": 1480, "dcf_base": 1600};
0 值(EV/EBITDA clamp 后)/ NaN / inf 在 values 中 → 忽略该 entry(不污染 mean/std)。
有效条目 < 2 或 mean == 0 → 返 None(无 cross-check 信号)。

spec ref: 2026-05-16-v1.x-multi-valuation-cross-check-design.md § 7
"""

from __future__ import annotations

import math
from typing import Literal

__all__ = ["analyze_consistency", "ConsistencyLevel"]

ConsistencyLevel = Literal["consistent", "moderate", "severe"]

# CV thresholds(spec § 7;calibrate post-dogfood)
_CV_CONSISTENT_THRESHOLD = 0.15
_CV_MODERATE_THRESHOLD = 0.30


def analyze_consistency(valuations: dict[str, float]) -> ConsistencyLevel | None:
    """单 lens / 空 / 全 0 → None;多 lens → severity by CV."""
    # 剔除 0 / NaN / inf / negative(防上游 helper bug 透传)
    valid = [v for v in valuations.values() if v > 0 and math.isfinite(v)]
    if len(valid) < 2:
        return None

    mean = sum(valid) / len(valid)
    if mean == 0:
        return None

    # C23: 使用样本方差 (n-1)，与金融学 CV 标准一致；
    # len(valid) >= 2 已由上方 guard 保证，故 denominator >= 1。
    variance = sum((v - mean) ** 2 for v in valid) / (len(valid) - 1)
    std = math.sqrt(variance)
    cv = std / mean

    if cv < _CV_CONSISTENT_THRESHOLD:
        return "consistent"
    if cv < _CV_MODERATE_THRESHOLD:
        return "moderate"
    return "severe"
