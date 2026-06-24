"""通过次数 k(共 N 次 rollout) → RL 难度标。

spec: docs/superpowers/specs/2026-06-24-eval-data-distribution-design.md §4.1
丢端点 k∈{0,N}(GRPO 组内 reward 全同 → 优势=0 → 梯度消失),留 k∈{1..N-1},黄金带中心±1。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tag:
    label: str  # too_hard / rl_band / too_easy
    in_rl: bool  # 是否进 RL 候选(丢端点后)
    prime: bool  # 是否黄金带(主喂)


def classify(k: int, *, n: int = 8) -> Tag:
    """通过次数 k(0..n) → Tag。k 越界 raise ValueError。"""
    if not (0 <= k <= n):
        raise ValueError(f"k={k} 越界 [0,{n}]")
    if k == 0:
        return Tag("too_hard", False, False)
    if k == n:
        return Tag("too_easy", False, False)
    mid = n / 2
    prime = abs(k - mid) <= 1
    return Tag("rl_band", True, prime)


__all__ = ["Tag", "classify"]
