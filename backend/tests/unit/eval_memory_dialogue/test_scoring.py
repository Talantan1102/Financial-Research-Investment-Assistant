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


def test_wilson_interval_basic() -> None:
    from eval.memory_dialogue.scoring import wilson_interval
    # 全通过但样本小 → 区间宽,下界明显 <1(小样本不该自信)
    lo, hi = wilson_interval(3, 3)
    assert 0.0 <= lo < 1.0 and hi == 1.0 or hi <= 1.0
    assert lo < 0.9  # 3/3 不等于'确定 100%'
    # 大样本全过 → 下界接近 1
    lo2, hi2 = wilson_interval(100, 100)
    assert lo2 > lo  # 样本越大下界越高
    # 空样本安全
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_format_shows_error_bars() -> None:
    from eval.memory_dialogue.read_phase import ProbeResult
    from eval.memory_dialogue.scoring import build_score_table, format_score_table
    from eval.memory_dialogue.script_schema import Probe

    def _pr(dim, tier, ok):
        p = Probe(tier=tier, dimension=dim, q='q', expect_contain=(), expect_not=(), judge_rubric='r')
        return ProbeResult(p, 'a', ok, ok, True, ok, '')

    table = build_score_table([_pr('知识更新', '直球', True), _pr('知识更新', '直球', False)], [])
    out = format_score_table(table)
    # 误差棒:置信区间应出现(方括号或 ± 形式)
    assert '95%' in out or '[' in out
    assert '总分' not in out  # 仍无聚合总分


def test_cluster_se_by_script() -> None:
    """session/脚本级聚类标准误:同脚本多题不是独立样本,按脚本聚类。"""
    from eval.memory_dialogue.scoring import cluster_standard_error
    # 两个脚本,脚本内强相关(一个全过一个全挂)→ 聚类 SE 应明显大于朴素 SE
    clusters = [[True, True, True], [False, False, False]]
    se = cluster_standard_error(clusters)
    assert se > 0.0  # 脚本间方差大
    # 单脚本或空安全
    assert cluster_standard_error([]) == 0.0


def test_separable_distinguishes_clear_gap() -> None:
    from eval.memory_dialogue.scoring import separable
    # 完整版 vs 残废版差距明显 → 可高置信区分
    assert separable(10, 10, 0, 10) is True
    # 接近 + 小样本 → 区间重叠,分不开
    assert separable(5, 10, 6, 10) is False
    # 同分必不可分
    assert separable(7, 10, 7, 10) is False
