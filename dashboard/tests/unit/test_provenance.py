"""provenance fuzzy match — spec § 7.3。Plan 1 Task 5。"""

from __future__ import annotations

from pathlib import Path

from dashboard.derive.provenance import (
    normalize_text,
    verify_quote_in_source,
)


def test_normalize_strips_whitespace() -> None:
    assert normalize_text("  hello  world\n") == "hello world"


def test_normalize_removes_markdown_emphasis() -> None:
    assert normalize_text("**bold**") == "bold"
    assert normalize_text("_italic_") == "italic"
    assert normalize_text("`code`") == "code"


def test_normalize_collapses_internal_whitespace() -> None:
    assert normalize_text("a   b\t\nc") == "a b c"


def test_verify_exact_match(tmp_path: Path) -> None:
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema。", encoding="utf-8")
    result = verify_quote_in_source("LLM 输出强制走 JSON schema", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_markdown_in_source_match(tmp_path: Path) -> None:
    """source 含 markdown,quote 不含,normalize 后命中。"""
    src = tmp_path / "spec.md"
    src.write_text("**LLM** 输出 *强制* 走 JSON `schema`", encoding="utf-8")
    result = verify_quote_in_source("LLM 输出 强制 走 JSON schema", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_quote_in_markdown_match(tmp_path: Path) -> None:
    """quote 含 markdown,source 不含,normalize 后也命中。"""
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema", encoding="utf-8")
    result = verify_quote_in_source("**LLM** 输出强制走 JSON `schema`", src, base_dir=tmp_path)
    assert result.ok is True


def test_verify_fabricated_quote_rejected(tmp_path: Path) -> None:
    src = tmp_path / "spec.md"
    src.write_text("LLM 输出强制走 JSON schema。", encoding="utf-8")
    result = verify_quote_in_source("LLM 必须用 tools call", src, base_dir=tmp_path)
    assert result.ok is False
    assert "not found" in result.reason.lower()


def test_verify_source_file_missing(tmp_path: Path) -> None:
    result = verify_quote_in_source("x", Path("nonexistent.md"), base_dir=tmp_path)
    assert result.ok is False
    assert "not exist" in result.reason.lower()


def test_verify_source_with_anchor(tmp_path: Path) -> None:
    """source 含 #anchor 段,verify 时剥离,只校验文件内容。"""
    src = tmp_path / "spec.md"
    src.write_text("hello world", encoding="utf-8")
    result = verify_quote_in_source("hello", "spec.md#§2", base_dir=tmp_path)
    assert result.ok is True
