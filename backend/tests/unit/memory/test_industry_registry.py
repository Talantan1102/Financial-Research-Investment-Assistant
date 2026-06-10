"""Industry 实体归一(接申万 registry):自由文本行业标签 → 申万 canonical。

对话流评估写侧根因:registry 对 Industry 是 passthrough,白酒/白酒Ⅱ/高端白酒 落不同
节点 → 观点演化链断开(看多在白酒Ⅱ、中性在白酒,互不作废)。归一到同一 canonical 才修。
"""

from __future__ import annotations

from app.memory.industry_registry import normalize_industry


def test_baijiu_variants_normalize_to_same_canonical() -> None:
    """白酒 / 白酒Ⅱ / 白酒II / 高端白酒 / 次高端白酒 → 同一 canonical(演化链不断的前提)。"""
    canon = {
        normalize_industry(x)[0] for x in ["白酒", "白酒Ⅱ", "白酒II", "高端白酒", "次高端白酒"]
    }
    assert len(canon) == 1, f"白酒系应归一到一个 canonical,实得 {canon}"


def test_canonical_is_shenwan_l2_name() -> None:
    """canonical 取申万二级正式名「白酒Ⅱ」(与既有断言候选表对齐)。"""
    assert normalize_industry("高端白酒")[0] == "白酒Ⅱ"
    assert normalize_industry("白酒")[0] == "白酒Ⅱ"


def test_exact_shenwan_name_is_clean_no_audit() -> None:
    """直命中申万正式名 → 不打 audit_flag。"""
    canon, audit = normalize_industry("白酒Ⅱ")
    assert canon == "白酒Ⅱ"
    assert audit is False


def test_free_text_alias_hit_no_audit() -> None:
    """已知 alias(高端白酒)命中映射 → 归一且不 audit。"""
    canon, audit = normalize_industry("高端白酒")
    assert canon == "白酒Ⅱ"
    assert audit is False


def test_different_industries_not_merged() -> None:
    """白酒 与 医药 不得误并(归一不能把不同行业揉一起)。"""
    assert normalize_industry("白酒")[0] != normalize_industry("医药生物")[0]


def test_unknown_label_passthrough_with_audit() -> None:
    """完全不认识的行业 → 原样返回 + audit_flag(留痕,不强行编)。"""
    canon, audit = normalize_industry("某个生造行业XYZ")
    assert canon == "某个生造行业XYZ"
    assert audit is True


def test_medical_variants_normalize() -> None:
    """医药 / 医药生物 → 同一 canonical。"""
    assert normalize_industry("医药")[0] == normalize_industry("医药生物")[0]
