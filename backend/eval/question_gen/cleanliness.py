"""SFT 第二道闸:轨迹过程是否干净。

spec: docs/superpowers/specs/2026-06-24-eval-data-distribution-design.md §4.2
承 RL substrate spec §2b:halt_reason==natural ∧ 步数≤桶理想(撞闸/熔断/打转的不收)。
轨迹结构 = runner collect 的 trajectories_raw.jsonl 行 {case_id, model, messages, n_steps, halt_reason}。
"""

from __future__ import annotations


def is_clean(traj: dict, *, ideal_steps: int) -> bool:
    """轨迹是否过程干净:halt 自然 ∧ 步数≤理想。"""
    if traj.get("halt_reason") != "natural":
        return False
    n = traj.get("n_steps")
    return not (n is None or n > ideal_steps)


__all__ = ["is_clean"]
