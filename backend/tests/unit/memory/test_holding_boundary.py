"""策略 A 持仓边界:持仓陈述不入记忆图(评估驱动的产品能力)。

对话流评估持仓仲裁族冒烟发现:用户口头报「茅台加到700股」,抽取器照建 HOLDS 边
(库里实有 HOLDS 边)——记忆与持仓监控模块形成双真相源。策略 A 要求持仓事实
(HOLDS/SOLD)归持仓模块、不入记忆图,只留观点/偏好。本测试守过滤纯函数。
"""

from __future__ import annotations

from app.memory.path_b_runner import HOLDING_REL_TYPES, filter_holding_edges


def test_holding_rel_types_are_holds_and_sold() -> None:
    assert frozenset({"HOLDS", "SOLD"}) == HOLDING_REL_TYPES


def test_filter_drops_holding_keeps_views() -> None:
    edges = [
        {"rel_type": "HOLDS", "target_label": "600519.SH"},
        {"rel_type": "EXPRESSED_VIEW", "target_label": "白酒"},
        {"rel_type": "SOLD", "target_label": "600519.SH"},
        {"rel_type": "PREFERS", "target_label": "高股息"},
    ]
    kept = filter_holding_edges(edges)
    rel_types = [e["rel_type"] for e in kept]
    assert rel_types == ["EXPRESSED_VIEW", "PREFERS"]  # 持仓边被剔,观点/偏好留


def test_filter_empty_and_no_holding_safe() -> None:
    assert filter_holding_edges([]) == []
    views = [{"rel_type": "EXPRESSED_VIEW"}]
    assert filter_holding_edges(views) == views
