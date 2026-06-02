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


def test_kb_cells_carry_todo(matrix: EvalMatrix) -> None:
    """KB 的 component / regression 缺口格带补缺口 TODO(RAGAS 检索评估计划)。"""
    kb = next(s for s in matrix.subsystems if s.id == "kb")
    comp_todo = kb.cells["component"].todo
    assert len(comp_todo) == 6, "KB component 应有 6 条 RAGAS 检索评估 TODO"
    first = comp_todo[0]
    assert "qrels" in first.task
    assert first.est == "~1.5d"
    assert first.done is False
    # 至少一条提到 RAGAS,坐实这是检索评估计划
    assert any("RAGAS" in t.task for t in comp_todo)
    # regression 格也有收尾 TODO
    assert len(kb.cells["regression"].todo) == 2


def test_cells_without_todo_default_empty(matrix: EvalMatrix) -> None:
    """没写 todo 的格子 → 空 tuple,不影响其它子系统。"""
    mem = next(s for s in matrix.subsystems if s.id == "memory")
    assert mem.cells["component"].todo == ()


def test_todo_missing_task_fails_loud(tmp_path: Path) -> None:
    body = (
        _LAYERS_BLOCK
        + """
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component:
        status: gap
        methods: []
        evidence: []
        gap: ''
        todo:
          - {est: "~1d", done: false}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
      regression: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="todo.*缺失 task"):
        load_eval_matrix(_write(tmp_path, body))


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


def test_glossary_covers_every_referenced_method(matrix: EvalMatrix) -> None:
    """每个 cell 引用的评估方法 tag 都必须在 method_glossary 里有词条。"""
    referenced = {
        m for sub in matrix.subsystems for cell in sub.cells.values() for m in cell.methods
    }
    assert referenced, "矩阵里应有方法 tag"
    missing = referenced - matrix.glossary.keys()
    assert not missing, f"这些方法缺词典词条: {sorted(missing)}"


def test_glossary_entry_is_typed(matrix: EvalMatrix) -> None:
    """词条字段类型化 + family 合法 + 样例三段齐全。"""
    from dashboard.derive.eval_matrix import FAMILY_LABELS, EvalMethod

    m = matrix.glossary["unit-test"]
    assert isinstance(m, EvalMethod)
    assert m.name_cn and m.name_en and m.how
    assert m.family in FAMILY_LABELS
    assert m.family_label == FAMILY_LABELS[m.family]
    assert m.sample.given and m.sample.expect and m.sample.verdict


def test_resolve_methods_returns_cards_in_order(matrix: EvalMatrix) -> None:
    """resolve_methods 按 cell.methods 顺序返回 EvalMethod 卡片。"""
    mem = next(s for s in matrix.subsystems if s.id == "memory")
    cell = mem.cells["component"]
    cards = matrix.resolve_methods(cell)
    assert tuple(c.id for c in cards) == cell.methods


def test_learning_path_parsed(matrix: EvalMatrix) -> None:
    """组件级评估学习路径:8 步,首步是第 0 步,带 kind/est,关联格正确。"""
    path = matrix.learning_path
    assert len(path) == 8
    assert path[0].title.startswith("第 0 步")
    # 第 1 步关联到 对话 Agent 组件级
    assert "对话 Agent·组件级" in path[1].maps
    # 第 4 步攻检索,关联 知识库检索·组件级
    assert any("知识库检索·组件级" in s.maps for s in path)
    # 每步都有非空 what,且至少一步有工期估计
    assert all(s.what for s in path)
    assert any(s.est for s in path)


def test_learning_path_missing_what_fails_loud(tmp_path: Path) -> None:
    body = (
        _LAYERS_BLOCK
        + """
learning_path:
  - {title: "第 0 步", kind: 看, est: "~0.5d"}
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component: {status: gap, methods: [], evidence: [], gap: ''}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
      regression: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="learning_path.*what"):
        load_eval_matrix(_write(tmp_path, body))


def test_glossary_missing_referenced_method_fails_loud(tmp_path: Path) -> None:
    """cell 引用了词典里没有的方法 → fail loud。"""
    body = (
        _LAYERS_BLOCK
        + """
method_glossary:
  unit-test:
    name_cn: 单测
    name_en: Unit Test
    family: deterministic
    how: h
    sample: {given: g, expect: e, verdict: v}
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component: {status: covered, methods: [ghost-method], evidence: [], gap: ''}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
      regression: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="没有词条.*ghost-method"):
        load_eval_matrix(_write(tmp_path, body))


def test_glossary_illegal_family_fails_loud(tmp_path: Path) -> None:
    body = (
        _LAYERS_BLOCK
        + """
method_glossary:
  unit-test:
    name_cn: 单测
    name_en: Unit Test
    family: bogus-family
    how: h
    sample: {given: g, expect: e, verdict: v}
subsystems:
  - id: x
    name_cn: X
    name_en: X
    summary: s
    cells:
      component: {status: gap, methods: [], evidence: [], gap: ''}
      agent: {status: gap, methods: [], evidence: [], gap: ''}
      system: {status: gap, methods: [], evidence: [], gap: ''}
      regression: {status: gap, methods: [], evidence: [], gap: ''}
"""
    )
    with pytest.raises(ValueError, match="family 非法"):
        load_eval_matrix(_write(tmp_path, body))


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
