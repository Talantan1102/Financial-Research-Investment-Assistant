"""分数聚合 — 能力维度 × 难度档通过率表。无门控、无聚合总分(解读交给人)。

误差棒(元评估落地第二项):每个 cell 配 Wilson 置信区间——没有误差棒的分差
表等于没结论(3/3 不是"确定 100%")。对话流评估同脚本多题不独立,另提供
session/脚本级聚类标准误(朴素标准误会低估 3 倍以上)。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.script_schema import VALID_DIMENSIONS, VALID_TIERS
from eval.memory_dialogue.write_phase import SessionCheckResult

_Z95 = 1.96


def wilson_interval(passed: int, total: int, z: float = _Z95) -> tuple[float, float]:
    """二项比例的 Wilson 95% 置信区间(小样本也不失真,优于正态近似)。"""
    if total <= 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (max(0.0, center - half), min(1.0, center + half))


def separable(a_passed: int, a_total: int, b_passed: int, b_total: int, z: float = _Z95) -> bool:
    """两个版本的通过率能否被高置信区分(Wilson 区间不重叠)。

    区分度(separability)的逐对判定:消融实验里完整版 vs 削弱版,区间不重叠
    才能说"评估真把好坏拉开了"。区间重叠=噪声盖过差距,评估区分力不足。
    """
    a_lo, a_hi = wilson_interval(a_passed, a_total, z)
    b_lo, b_hi = wilson_interval(b_passed, b_total, z)
    return a_hi < b_lo or b_hi < a_lo


def cluster_standard_error(clusters: list[list[bool]]) -> float:
    """脚本/session 级聚类标准误:随机化单元是脚本,不是题。

    同脚本多题共享命运(一段脚本写管线整体失败→全红),按题算方差会严重低估。
    用脚本级通过率的样本标准差 / sqrt(脚本数) 作聚类 SE。
    """
    rates = [sum(c) / len(c) for c in clusters if c]
    m = len(rates)
    if m <= 1:
        return 0.0
    mean = sum(rates) / m
    var = sum((r - mean) ** 2 for r in rates) / (m - 1)
    return math.sqrt(var / m)


@dataclass
class ScoreTable:
    cells: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)
    db_assertion_rate: tuple[int, int] = (0, 0)

    def cell(self, dimension: str, tier: str) -> tuple[int, int]:
        return self.cells.get((dimension, tier), (0, 0))


def build_score_table(
    probe_results: list[ProbeResult],
    write_results: list[SessionCheckResult],
) -> ScoreTable:
    agg: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in probe_results:
        agg[(r.probe.dimension, r.probe.tier)].append(r.final_passed)
    cells = {k: (sum(v), len(v)) for k, v in agg.items()}
    db_pass = sum(1 for w in write_results if w.passed)
    return ScoreTable(cells=cells, db_assertion_rate=(db_pass, len(write_results)))


def format_score_table(table: ScoreTable) -> str:
    lines = ["能力维度 × 难度档(通过/总数)", "=" * 48]
    header = f"{'维度':<10}" + "".join(f"{t:>10}" for t in VALID_TIERS)
    lines.append(header)
    for dim in VALID_DIMENSIONS:
        row_cells = [table.cell(dim, t) for t in VALID_TIERS]
        if all(total == 0 for _, total in row_cells):
            continue

        def _fmt(p: int, t: int) -> str:
            if not t:
                return "—"
            lo, hi = wilson_interval(p, t)
            return f"{p}/{t}[{lo:.2f}-{hi:.2f}]"

        row = f"{dim:<10}" + "".join(f"{_fmt(p, t):>18}" for p, t in row_cells)
        lines.append(row)
    db_p, db_t = table.db_assertion_rate
    db_lo, db_hi = wilson_interval(db_p, db_t)
    lines.append("-" * 48)
    lines.append(f"写管线数据库断言: {db_p}/{db_t} (Wilson 95% [{db_lo:.2f}-{db_hi:.2f}])")
    lines.append("(误差棒=Wilson 95% 区间;区间重叠的两版本不能下'谁更好'的结论)")
    lines.append("(直球档当金丝雀:大面积红先怀疑评估 harness 自身)")
    return "\n".join(lines)
