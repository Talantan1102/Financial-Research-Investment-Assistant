"""抽取后校验护栏:prompt/解码漏网的硬兜底——幻觉日期、脏 label。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.memory.extraction_guards import is_stance_phrase_label, sanitize_edge


def _ep(y: int = 2025, m: int = 1, d: int = 6) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


def test_rejects_future_valid_to() -> None:
    edge = {
        "rel_type": "EXPRESSED_VIEW",
        "target_label": "白酒Ⅱ",
        "valid_from": "2025-01-06",
        "valid_to": "2027-04-01",  # 幻觉未来日期
        "importance": 0.9,
        "reasoning": "x",
        "source_label": "User",
    }
    out = sanitize_edge(edge, episode_date=_ep())
    assert out["valid_to"] is None  # 越界 valid_to 被重置为 null


def test_rejects_unparseable_valid_to() -> None:
    edge = {"rel_type": "EXPRESSED_VIEW", "target_label": "白酒Ⅱ",
            "valid_from": "2025-01-06", "valid_to": "假设2025-04-15",
            "importance": 0.9, "reasoning": "x", "source_label": "User"}
    out = sanitize_edge(edge, episode_date=_ep())
    assert out["valid_to"] is None


def test_keeps_valid_to_in_window() -> None:
    edge = {"rel_type": "EXPRESSED_VIEW", "target_label": "白酒Ⅱ",
            "valid_from": "2025-01-06", "valid_to": "2025-02-03",  # 合理:对话日附近
            "importance": 0.9, "reasoning": "x", "source_label": "User"}
    out = sanitize_edge(edge, episode_date=_ep(2025, 2, 3))
    assert out["valid_to"] == "2025-02-03"  # 合理日期不动


def test_keeps_null_valid_to() -> None:
    edge = {"rel_type": "EXPRESSED_VIEW", "target_label": "白酒Ⅱ",
            "valid_from": "2025-01-06", "valid_to": None,
            "importance": 0.9, "reasoning": "x", "source_label": "User"}
    out = sanitize_edge(edge, episode_date=_ep())
    assert out["valid_to"] is None


def test_flags_stance_phrase_label() -> None:
    assert is_stance_phrase_label("看多高端白酒") is True
    assert is_stance_phrase_label("看空白酒") is True
    assert is_stance_phrase_label("买入茅台") is True


def test_clean_label_not_flagged() -> None:
    assert is_stance_phrase_label("白酒Ⅱ") is False
    assert is_stance_phrase_label("600519.SH") is False
    assert is_stance_phrase_label("提价权") is False


def test_build_output_tolerant_keeps_good_drops_bad() -> None:
    """一条非法 rel_type 边 + 一条脏 label 边 + 一条好边 → 只丢坏的,好边存活(不毁整批)。"""
    from uuid import uuid4

    from app.memory.extractor import _build_output_tolerant

    parsed = {
        "entities": [
            {"entity_type": "Industry", "entity_label": "白酒Ⅱ", "properties": {}},
            {"entity_type": "NotAType", "entity_label": "x", "properties": {}},  # 非法类型
        ],
        "edges": [
            {"rel_type": "EXPRESSED_VIEW", "source_label": "User", "target_label": "白酒Ⅱ",
             "valid_from": "2025-04-01", "valid_to": None, "importance": 0.9,
             "reasoning": "看多收回转中性", "properties": {"view": "中性"}},  # 好边
            {"rel_type": "NOT_A_REL", "source_label": "User", "target_label": "白酒Ⅱ",
             "valid_from": "2025-04-01", "valid_to": None, "importance": 0.9,
             "reasoning": "x", "properties": {}},  # 非法关系 → 丢
            {"rel_type": "EXPRESSED_VIEW", "source_label": "User", "target_label": "看多高端白酒",
             "valid_from": "2025-04-01", "valid_to": None, "importance": 0.9,
             "reasoning": "x", "properties": {}},  # 脏 label → 丢
            {"rel_type": "EXPRESSED_VIEW", "source_label": "User", "target_label": "白酒Ⅱ",
             "valid_from": "2025-04-01", "valid_to": "2027-04-01", "importance": 0.9,
             "reasoning": "x", "properties": {}},  # 幻觉 valid_to → 被重置 null
        ],
    }
    out = _build_output_tolerant(parsed, episode_date=_ep(2025, 4, 1), session_id=uuid4())
    # 好实体存活、非法类型丢
    assert [e.entity_label for e in out.entities] == ["白酒Ⅱ"]
    # 好边 2 条存活(EXPRESSED_VIEW→白酒Ⅱ),非法关系+脏label 丢
    assert len(out.edges) == 2
    assert all(e.rel_type == "EXPRESSED_VIEW" and e.target_label == "白酒Ⅱ" for e in out.edges)
    # 幻觉 valid_to 被护栏重置
    assert all(e.valid_to is None for e in out.edges)
