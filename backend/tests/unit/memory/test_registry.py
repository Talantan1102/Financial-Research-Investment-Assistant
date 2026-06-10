"""L0: Entity registry — 7 entity types + 11 rel types + normalize_entity + jieba."""

from __future__ import annotations

import pytest
from app.memory.registry import (
    ENTITY_TYPES,
    METRIC_WHITELIST,
    REL_TYPES,
    STRATEGY_WHITELIST,
    is_valid_rel_type,
    jieba_tokenize_for_search,
    normalize_entity,
)

# ---- 常量 ----


def test_entity_types_count_seven() -> None:
    assert len(ENTITY_TYPES) == 7
    assert set(ENTITY_TYPES) == {
        "User",
        "Stock",
        "Industry",
        "Sector",
        "Metric",
        "Strategy",
        "Concept",
    }


def test_rel_types_count_eleven() -> None:
    assert len(REL_TYPES) == 11
    assert set(REL_TYPES) == {
        "HOLDS",
        "WATCHES",
        "PREFERS",
        "AVOIDS",
        "EXPRESSED_VIEW",
        "SOLD",
        "STUDIED",
        "COMPARED",
        "BELONGS_TO",
        "HAS_CONCEPT",
        "CORRELATED_WITH",
    }


def test_metric_whitelist_has_pe_roe() -> None:
    """spec 附录 A 白名单核心 metric 必须在."""
    assert "PE" in METRIC_WHITELIST.values()
    assert "ROE" in METRIC_WHITELIST.values()


def test_strategy_whitelist_has_dcf_value() -> None:
    """spec 附录 A 白名单核心 strategy 必须在."""
    assert "DCF" in STRATEGY_WHITELIST.values()
    assert "价值投资" in STRATEGY_WHITELIST.values()


# ---- is_valid_rel_type ----


def test_is_valid_rel_type_holds() -> None:
    assert is_valid_rel_type("HOLDS") is True


def test_is_valid_rel_type_unknown() -> None:
    assert is_valid_rel_type("FROBNICATES") is False


# ---- normalize_entity ----


@pytest.mark.parametrize(
    "raw, expected, audit",
    [
        ("600519.SH", "600519.SH", False),
        ("000858.SZ", "000858.SZ", False),
        ("000001.BJ", "000001.BJ", False),
        ("茅台", "茅台", True),  # 不是 ts_code 格式 → audit_flag
        ("600519.SH ", "600519.SH", False),  # trim
    ],
)
def test_normalize_entity_stock(raw: str, expected: str, audit: bool) -> None:
    label, audit_flag = normalize_entity("Stock", raw)
    assert label == expected
    assert audit_flag is audit


def test_normalize_entity_user_fixed() -> None:
    """User 类型固定 'User' label."""
    label, audit_flag = normalize_entity("User", "anything")
    assert label == "User"
    assert audit_flag is False


def test_normalize_entity_metric_pe_uppercase() -> None:
    label, audit_flag = normalize_entity("Metric", "pe")
    assert label == "PE"
    assert audit_flag is False


def test_normalize_entity_metric_unknown_audit() -> None:
    label, audit_flag = normalize_entity("Metric", "unknown_metric")
    assert audit_flag is True


def test_normalize_entity_strategy_dcf() -> None:
    label, audit_flag = normalize_entity("Strategy", "dcf")
    assert label == "DCF"
    assert audit_flag is False


def test_normalize_entity_industry_normalizes_via_shenwan() -> None:
    """接申万 registry(2026-06-09):Industry 不再 passthrough,白酒系归一到申万 canonical。
    这是对话流评估写侧根因修复——白酒/白酒Ⅱ/高端白酒 必须落同一节点,演化链才不断。"""
    label, audit_flag = normalize_entity("Industry", "白酒")
    assert label == "白酒Ⅱ"
    assert audit_flag is False
    # 自由文本变体也归一
    assert normalize_entity("Industry", "高端白酒")[0] == "白酒Ⅱ"
    assert normalize_entity("Industry", "白酒Ⅱ")[0] == "白酒Ⅱ"
    # 认不出的行业仍 passthrough + audit
    unknown, ua = normalize_entity("Industry", "生造行业ZZZ")
    assert unknown == "生造行业ZZZ" and ua is True


# ---- jieba_tokenize_for_search ----


def test_jieba_tokenize_chinese() -> None:
    """jieba.cut_for_search 切'贵州茅台' → '贵州 茅台 贵州茅台'."""
    tokens = jieba_tokenize_for_search("贵州茅台")
    parts = set(tokens.split())
    # cut_for_search 至少切出"贵州"和"茅台"
    assert "贵州" in parts
    assert "茅台" in parts


def test_jieba_tokenize_empty_string() -> None:
    assert jieba_tokenize_for_search("") == ""


def test_jieba_tokenize_mixed_zh_en() -> None:
    tokens = jieba_tokenize_for_search("茅台 600519.SH")
    parts = set(tokens.split())
    assert "茅台" in parts
    assert "600519" in parts or "600519.SH" in parts


# ---- C64: SEARCH_TS_CODE_RE exported and semantically distinct from _TS_CODE_RE ----


def test_search_ts_code_re_exported() -> None:
    """C64: SEARCH_TS_CODE_RE must be importable from registry (single owner)."""
    from app.memory.registry import SEARCH_TS_CODE_RE

    assert SEARCH_TS_CODE_RE is not None


def test_search_ts_code_re_matches_embedded_code() -> None:
    """C64: search-variant matches a ts_code embedded in free text."""
    from app.memory.registry import SEARCH_TS_CODE_RE

    assert SEARCH_TS_CODE_RE.search("看看 600519.SH 怎么样") is not None


def test_validation_ts_code_re_requires_standalone() -> None:
    """C64: validation regex (_TS_CODE_RE) must NOT match code embedded in text.

    The full-string anchored pattern (^...$ via match/fullmatch) should fail
    against free text, while search-variant succeeds.
    """
    from app.memory.registry import _TS_CODE_RE as _VALIDATION_RE
    from app.memory.registry import SEARCH_TS_CODE_RE

    text_with_embedded = "看看 600519.SH 怎么样"
    # validation regex: does NOT match (anchored ^ ... $)
    assert _VALIDATION_RE.match(text_with_embedded) is None
    # search regex: DOES match
    assert SEARCH_TS_CODE_RE.search(text_with_embedded) is not None


def test_validation_ts_code_re_matches_bare_code() -> None:
    """Validation regex still recognizes a bare standalone ts_code."""
    from app.memory.registry import _TS_CODE_RE as _VALIDATION_RE

    assert _VALIDATION_RE.match("600519.SH") is not None
    assert _VALIDATION_RE.match("000858.SZ") is not None
    assert _VALIDATION_RE.match("123456.BJ") is not None
