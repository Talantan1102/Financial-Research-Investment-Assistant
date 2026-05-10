"""L0 unit tests for Milvus outbox helper functions (no DB)."""

from __future__ import annotations

from app.memory.milvus_outbox import build_edge_embed_text


def test_build_edge_embed_text_format_basic() -> None:
    """spec § 2 embed text 模板基本组成."""
    out = build_edge_embed_text(
        rel_type="HOLDS",
        source_entity_type="User",
        source_label="User",
        target_entity_type="Stock",
        target_label="600519.SH",
        reasoning="用户说持有",
        properties={"qty": 500},
    )
    assert "HOLDS" in out
    assert "User" in out
    assert "600519.SH" in out
    assert "→" in out
    assert "用户说持有" in out
    assert '"qty": 500' in out  # JSON-encoded properties


def test_build_edge_embed_text_chinese_props_no_ascii_escape() -> None:
    """中文 props 不被 escape, 保留可读性供 embed."""
    out = build_edge_embed_text(
        rel_type="PREFERS",
        source_entity_type="User",
        source_label="User",
        target_entity_type="Strategy",
        target_label="DCF",
        reasoning="偏好 DCF",
        properties={"风格": "保守"},
    )
    assert "保守" in out


def test_build_edge_embed_text_empty_properties() -> None:
    """空 properties → JSON {}."""
    out = build_edge_embed_text(
        rel_type="WATCHES",
        source_entity_type="User",
        source_label="User",
        target_entity_type="Stock",
        target_label="000001.SZ",
        reasoning="关注",
        properties={},
    )
    assert "{}" in out
