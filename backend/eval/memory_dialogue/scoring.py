"""分数聚合 — 能力维度 × 难度档通过率表。无门控、无聚合总分(解读交给人)。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.script_schema import VALID_DIMENSIONS, VALID_TIERS
from eval.memory_dialogue.write_phase import SessionCheckResult


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
        row = f"{dim:<10}" + "".join(f"{f'{p}/{t}' if t else '—':>10}" for p, t in row_cells)
        lines.append(row)
    db_p, db_t = table.db_assertion_rate
    lines.append("-" * 48)
    lines.append(f"写管线数据库断言: {db_p}/{db_t}")
    lines.append("(直球档当金丝雀:大面积红先怀疑评估 harness 自身)")
    return "\n".join(lines)
