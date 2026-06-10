"""Entity registry — 7 entity + 11 rel + normalize + jieba tokenize.

spec ref: § 3 Ontology(prescribed seed + drift-tolerant)
contract ref: § 5 registry.py 签名

Plan 1B 范围:
- Stock: ts_code 格式校验(6 数字 + .SH/.SZ/.BJ), 失败 audit_flag=True
- Industry/Sector: passthrough + audit_flag=True(申万 registry 留 v1.x 接)
- Metric/Strategy: 附录 A 白名单 → 统一英文标识
- Concept: passthrough(免 audit, 主题概念太多无法白名单)
- User: 固定 'User'

未来增强(留 v1.x):
- 申万行业 registry 接 Tushare /api/sw_hierarchy
- Concept registry 接 Tushare 概念字段
"""

from __future__ import annotations

import re

import jieba

# === 7 entity types ===
ENTITY_TYPES: list[str] = [
    "User",
    "Stock",
    "Industry",
    "Sector",
    "Metric",
    "Strategy",
    "Concept",
]

# === 11 rel types ===
REL_TYPES: list[str] = [
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
]

# === 附录 A 白名单 ===

# Metric 白名单(估值 + 财务 + 现金流 + 成长 ~30 个)
METRIC_WHITELIST: dict[str, str] = {
    # 估值
    "pe": "PE",
    "pe_ttm": "PE_TTM",
    "pb": "PB",
    "ps": "PS",
    "ev_ebitda": "EV_EBITDA",
    "dividend_yield": "dividend_yield",
    # 盈利
    "roe": "ROE",
    "roa": "ROA",
    "roic": "ROIC",
    "gross_margin": "gross_margin",
    "net_margin": "net_margin",
    "eps": "EPS",
    # 现金流
    "cash_flow": "cash_flow",
    "fcf": "FCF",
    "operating_cash_flow": "operating_cash_flow",
    # 资产负债
    "debt_ratio": "debt_ratio",
    "current_ratio": "current_ratio",
    "quick_ratio": "quick_ratio",
    # 成长
    "revenue_growth": "revenue_growth",
    "earnings_growth": "earnings_growth",
    "yoy_growth": "yoy_growth",
}

# Strategy 白名单(估值 + 增长 + 价值 ~20 个)
STRATEGY_WHITELIST: dict[str, str] = {
    "dcf": "DCF",
    "价值投资": "价值投资",
    "value_investing": "价值投资",
    "成长投资": "成长投资",
    "growth_investing": "成长投资",
    "趋势投资": "趋势投资",
    "momentum": "趋势投资",
    "deep_value": "deep_value",
    "quality_growth": "quality_growth",
    "高股息": "高股息",
    "技术分析": "技术分析",
    "technical_analysis": "技术分析",
    "套利": "套利",
    "arbitrage": "套利",
    "peg": "PEG",
    "eva": "EVA",
}

# === ts_code regexes ===
# C64: two distinct patterns — validation (full-string) stays private;
# search-in-text variant is exported so skip_gate.py can share the SSOT.
_TS_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
# Public: matches ts_code embedded in free text (word-boundary anchored)
SEARCH_TS_CODE_RE = re.compile(r"\b\d{6}\.(SH|SZ|BJ)\b")


def normalize_entity(entity_type: str, raw_label: str) -> tuple[str, bool]:
    """Returns (normalized_label, audit_flag).

    - User: 固定 'User'
    - Stock: ts_code 校验; 不匹配 → trim 后 audit_flag=True
    - Metric/Strategy: 白名单(case-insensitive) → 统一标识; 失败 audit_flag=True
    - Industry/Sector: 当前 passthrough + audit_flag=True(留 v1.x 接申万 registry)
    - Concept: passthrough + audit_flag=False(主题概念无法白名单)

    audit_flag=True 表示 normalize 失败(写库时仍写, 标 audit_flag 在 properties).
    """
    if entity_type == "User":
        return "User", False

    label = raw_label.strip()

    if entity_type == "Stock":
        if _TS_CODE_RE.match(label):
            return label, False
        # 不是 ts_code 格式(如 "茅台" / "Maotai") → audit
        return label, True

    if entity_type == "Metric":
        normalized = METRIC_WHITELIST.get(label.lower())
        if normalized is None:
            return label, True
        return normalized, False

    if entity_type == "Strategy":
        normalized = STRATEGY_WHITELIST.get(label.lower())
        if normalized is None:
            return label, True
        return normalized, False

    if entity_type == "Industry":
        # 接申万 registry(2026-06-09):自由文本行业标签 → 申万 canonical,
        # 修对话流评估写侧根因(白酒/白酒Ⅱ/高端白酒 落同一节点,演化链不断)。
        from app.memory.industry_registry import normalize_industry

        return normalize_industry(label)

    if entity_type == "Sector":
        # Sector(申万一级粒度)暂仍 passthrough + audit_flag(留后续接一级 registry)
        return label, True

    if entity_type == "Concept":
        return label, False

    # 未知 entity_type
    return label, True


def is_valid_rel_type(rel_type: str) -> bool:
    """Pure: rel_type ∈ REL_TYPES?"""
    return rel_type in REL_TYPES


def jieba_tokenize_for_search(text: str) -> str:
    """jieba.cut_for_search 全模式切词, 空格连接.

    用于 chat_memory_nodes / chat_memory_edges 的 search_tokens 字段写入.
    Plan 1B 实现, Plan 3 检索路径 1(BM25)调用.

    spec ref: § 5 路径 1 jieba pre-tokenize 方案(避开 zhparser PG 扩展可移植性问题).
    """
    if not text:
        return ""
    return " ".join(jieba.cut_for_search(text))
