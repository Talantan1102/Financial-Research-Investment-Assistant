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


def test_normalize_entity_industry_passthrough() -> None:
    """申万 registry 不在 Plan 1B 范围, 走 passthrough + audit_flag(下游 v1.x 接 registry)."""
    label, audit_flag = normalize_entity("Industry", "白酒")
    assert label == "白酒"
    # 当前没接申万 registry, 走 audit_flag 提示后续补
    assert audit_flag is True


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
