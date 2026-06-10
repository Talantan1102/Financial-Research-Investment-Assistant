"""消融区分度报告:完整版 vs 削弱版逐对 separable 判定(元评估第四步实跑核心)。

纯函数层:给定两版的读侧 probe + 写侧断言结果,产出每个 cell 的
(完整版率, 削弱版率, 是否可高置信区分, 方向) —— 验证评估真能把好坏拉开。
"""

from __future__ import annotations

from eval.memory_dialogue.ablation import (
    SeparabilityRow,
    separability_report,
    write_rates_by_check_type,
)
from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.script_schema import Probe
from eval.memory_dialogue.write_phase import SessionCheckResult


def _pr(dim: str, tier: str, passed: bool) -> ProbeResult:
    p = Probe(tier=tier, dimension=dim, q="q", expect_contain=(), expect_not=(), judge_rubric="r")
    return ProbeResult(p, "a", passed, passed, True, passed, "")


def _wc(check_type: str, passed: bool) -> SessionCheckResult:
    return SessionCheckResult(1, check_type, passed, "")


def test_write_rates_by_check_type_buckets() -> None:
    rows = [
        _wc("old_invalidated", True),
        _wc("old_invalidated", False),
        _wc("fact_active", True),
    ]
    rates = write_rates_by_check_type(rows)
    assert rates["old_invalidated"] == (1, 2)
    assert rates["fact_active"] == (1, 1)


def test_report_flags_separable_read_dimension() -> None:
    """读侧消融:完整版召回全过、削弱版(空检索)全挂 → 该维度可区分。"""
    full_probes = [_pr("单跳召回", "直球", True) for _ in range(10)]
    ablated_probes = [_pr("单跳召回", "直球", False) for _ in range(10)]
    report = separability_report(full_probes, [], ablated_probes, [])
    row = next(r for r in report if "单跳召回" in r.label)
    assert isinstance(row, SeparabilityRow)
    assert row.full == (10, 10)
    assert row.ablated == (0, 10)
    assert row.separable is True
    assert "完整版" in row.note  # 方向:完整版更高(预期)


def test_report_flags_write_check_separable() -> None:
    """写侧消融:无冲突消解 → old_invalidated 从全过掉到全挂,可区分。"""
    full_writes = [_wc("old_invalidated", True) for _ in range(8)]
    ablated_writes = [_wc("old_invalidated", False) for _ in range(8)]
    report = separability_report([], full_writes, [], ablated_writes)
    row = next(r for r in report if "old_invalidated" in r.label)
    assert row.separable is True
    assert row.full == (8, 8)
    assert row.ablated == (0, 8)


def test_report_marks_non_separable_when_overlap() -> None:
    """克制弃答维度:消融记忆不应让弃答掉分(无记忆照样该拒答)→ 不可区分=符合预期。"""
    full_probes = [_pr("克制弃答", "对抗", True) for _ in range(10)]
    ablated_probes = [_pr("克制弃答", "对抗", True) for _ in range(10)]
    report = separability_report(full_probes, [], ablated_probes, [])
    row = next(r for r in report if "克制弃答" in r.label)
    assert row.separable is False
    assert "无差异" in row.note or "不可区分" in row.note


def test_report_flags_anomalous_ablated_higher() -> None:
    """反常方向:削弱版反而更高 → 必须标出来(评估或消融配置有问题的信号)。"""
    full_probes = [_pr("知识更新", "直球", False) for _ in range(10)]
    ablated_probes = [_pr("知识更新", "直球", True) for _ in range(10)]
    report = separability_report(full_probes, [], ablated_probes, [])
    row = next(r for r in report if "知识更新" in r.label)
    assert row.separable is True
    assert "反常" in row.note
