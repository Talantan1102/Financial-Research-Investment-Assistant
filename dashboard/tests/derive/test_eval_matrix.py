"""evaluation matrix derive 层单测 — load + summary + fail-loud。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.derive.eval_matrix import (
    EvalMatrix,
    load_eval_matrix,
    matrix_summary,
)

CONFIG = Path(__file__).parent.parent.parent / "config" / "eval_system.yaml"


@pytest.fixture
def matrix() -> EvalMatrix:
    return load_eval_matrix(CONFIG)


def test_loads_4_layers_7_subsystems(matrix: EvalMatrix) -> None:
    assert [layer.id for layer in matrix.layers] == [
        "component",
        "agent",
        "system",
        "regression",
    ]
    assert {s.id for s in matrix.subsystems} == {
        "kb",
        "chat",
        "research",
        "memory",
        "monitoring",
        "valuation",
        "debate",
    }


def test_every_subsystem_has_all_4_cells(matrix: EvalMatrix) -> None:
    layer_ids = {layer.id for layer in matrix.layers}
    for sub in matrix.subsystems:
        assert set(sub.cells.keys()) == layer_ids, f"{sub.id} 缺 cell"
        for cell in sub.cells.values():
            assert cell.status in {"covered", "partial", "gap"}


def test_summary_counts_sum_to_total(matrix: EvalMatrix) -> None:
    s = matrix_summary(matrix)
    # 7 subsystems × 4 layers = 28 格
    assert s.total == 28
    assert s.covered + s.partial + s.gap == s.total


def test_summary_counts_exact(matrix: EvalMatrix) -> None:
    """对当前 yaml 的精确三态计数 — 改 yaml status 时此断言会提示重算。"""
    s = matrix_summary(matrix)
    assert s.covered == 10
    assert s.partial == 12
    assert s.gap == 6


def test_summary_coverage_pct_is_int_percentage(matrix: EvalMatrix) -> None:
    s = matrix_summary(matrix)
    assert isinstance(s.coverage_pct, int)
    assert s.coverage_pct == round(s.covered / s.total * 100)
    # 10/28 → 36
    assert s.coverage_pct == 36


def test_summary_covered_by_layer(matrix: EvalMatrix) -> None:
    s = matrix_summary(matrix)
    # 每列 covered 数之和 == 总 covered 数
    assert sum(s.covered_by_layer.values()) == s.covered
    # regression 列是最弱的(全项目无 covered)
    assert s.covered_by_layer["regression"] == 0
    # component 列最强
    assert s.covered_by_layer["component"] == 6


def test_cell_fields_typed(matrix: EvalMatrix) -> None:
    kb = next(s for s in matrix.subsystems if s.id == "kb")
    comp = kb.cells["component"]
    assert comp.status == "partial"
    assert isinstance(comp.methods, tuple)
    assert isinstance(comp.evidence, tuple)
    assert "backend/tests/unit/test_chunkers.py" in comp.evidence
    # gap 格无 methods / evidence,gap 文案非空
    gap_cell = kb.cells["regression"]
    assert gap_cell.status == "gap"
    assert gap_cell.methods == ()
    assert gap_cell.evidence == ()
    assert gap_cell.gap != ""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "bad.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_LAYERS_BLOCK = """
layers:
  - {id: component, name_cn: 组, name_en: C, desc: d}
  - {id: agent, name_cn: 智, name_en: A, desc: d}
  - {id: system, name_cn: 系, name_en: S, desc: d}
  - {id: regression, name_cn: 回, name_en: R, desc: d}
"""


def test_illegal_status_fails_loud(tmp_path: Path) -> None:
    body = (
        _LAYERS_BLOCK
        + """
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component: {status: bogus, methods: [], evidence: [], gap: ''}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
      regression: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="status 非法"):
        load_eval_matrix(_write(tmp_path, body))


def test_missing_cell_fails_loud(tmp_path: Path) -> None:
    """subsystem 缺某层 cell → fail loud(不静默补空)。"""
    body = (
        _LAYERS_BLOCK
        + """
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component: {status: gap, methods: [], evidence: [], gap: ''}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="缺失 layer 'regression'"):
        load_eval_matrix(_write(tmp_path, body))


def test_missing_top_level_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="subsystems"):
        load_eval_matrix(_write(tmp_path, _LAYERS_BLOCK))
