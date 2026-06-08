"""分数表:能力维度 × 难度档,无聚合总分;写管线断言通过率单列。"""

from __future__ import annotations

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.scoring import build_score_table, format_score_table
from eval.memory_dialogue.script_schema import Probe
from eval.memory_dialogue.write_phase import SessionCheckResult


def _pr(dim: str, tier: str, passed: bool) -> ProbeResult:
    p = Probe(
        tier=tier,
        dimension=dim,
        q="q",
        expect_contain=(),
        expect_not=(),
        judge_rubric="r",
    )
    return ProbeResult(p, "a", passed, passed, True, passed, "")


def test_table_groups_by_dimension_and_tier() -> None:
    table = build_score_table(
        probe_results=[
            _pr("知识更新", "直球", True),
            _pr("知识更新", "直球", True),
            _pr("知识更新", "对抗", False),
            _pr("克制弃答", "自然难", True),
        ],
        write_results=[
            SessionCheckResult(1, "fact_active", True, ""),
            SessionCheckResult(3, "old_invalidated", False, "红"),
        ],
    )
    assert table.cell("知识更新", "直球") == (2, 2)
    assert table.cell("知识更新", "对抗") == (0, 1)
    assert table.cell("克制弃答", "自然难") == (1, 1)
    assert table.db_assertion_rate == (1, 2)


def test_format_contains_no_aggregate_total() -> None:
    table = build_score_table([_pr("知识更新", "直球", True)], [])
    out = format_score_table(table)
    assert "知识更新" in out and "直球" in out
    assert "总分" not in out  # 设计决策:无聚合总分
