"""L0 — PdfParser Protocol + MineruParser + PdfPlumberParser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app.services.pdf_parser import (
    ParsedDocument,
    PdfParser,
    Section,
    Table,
)
from app.services.pdf_parsers.mineru import MineruParser
from app.services.pdf_parsers.pdfplumber import PdfPlumberParser


def test_protocol_satisfied_by_both_parsers() -> None:
    """两个 backend 都满足 PdfParser Protocol(structural typing)."""
    mineru = MineruParser()
    pdfplumber = PdfPlumberParser()
    assert isinstance(mineru, PdfParser)
    assert isinstance(pdfplumber, PdfParser)


def test_parsed_document_model_basic() -> None:
    doc = ParsedDocument(
        sections=[
            Section(title="第一章", text="这是正文。", section_type="paragraph"),
        ],
        tables=[
            Table(markdown="| col |\n|---|\n| val |", title="表 1", section_index=0),
        ],
        metadata={"title": "测试研报"},
    )
    assert len(doc.sections) == 1
    assert len(doc.tables) == 1
    assert doc.metadata["title"] == "测试研报"


@pytest.mark.asyncio
async def test_pdfplumber_parser_returns_sections(tmp_path: Path) -> None:
    """Mock pdfplumber.open;verify section 提取 + 跳表格."""
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")  # 不是合法 PDF,只是占位,mock 会拦截

    fake_page1 = type(
        "Page",
        (),
        {
            "extract_text": lambda self: "第一章\n这是正文段落,介绍背景。\n第二段:进一步阐述。",
            "extract_tables": lambda self: [],
        },
    )()
    fake_pdf = type(
        "Pdf", (), {"pages": [fake_page1], "__enter__": lambda s: s, "__exit__": lambda s, *a: None}
    )()

    with patch("pdfplumber.open", return_value=fake_pdf):
        parser = PdfPlumberParser()
        doc = await parser.parse(pdf_path)

    assert len(doc.sections) >= 1
    assert "第一章" in doc.sections[0].text or any("第一章" in s.text for s in doc.sections)
    # PdfPlumberParser v0.7 跳表格
    assert len(doc.tables) == 0


class _FakeProc:
    """Async-aware fake subprocess for MineruParser tests."""

    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", b"")


@pytest.mark.asyncio
async def test_mineru_parser_subprocess_invocation(tmp_path: Path) -> None:
    """mineru CLI subprocess wrap;mock create_subprocess_exec + content_list.json 文件."""
    import json

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")

    # mineru 输出在 <out>/<stem>/auto/ 目录
    fake_out_root = tmp_path / "mineru_out"
    fake_auto_dir = fake_out_root / "test" / "auto"
    fake_auto_dir.mkdir(parents=True)
    fake_blocks = [
        {"type": "text", "text": "标题", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "正文段落。", "page_idx": 0},
    ]
    (fake_auto_dir / "test_content_list.json").write_text(
        json.dumps(fake_blocks, ensure_ascii=False)
    )

    async def fake_subprocess_exec(*args, **kwargs):
        return _FakeProc()

    with (
        patch("app.services.pdf_parsers.mineru._OUT_ROOT", fake_out_root),
        patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec),
    ):
        parser = MineruParser()
        doc = await parser.parse(pdf_path)

    assert len(doc.sections) >= 1
    titles = [s.title for s in doc.sections if s.title]
    assert "标题" in titles or any("标题" in (s.text or "") for s in doc.sections)


@pytest.mark.asyncio
async def test_mineru_parser_extracts_html_tables(tmp_path: Path) -> None:
    """MinerU 3.x table_body 是 HTML;MineruParser 转 markdown."""
    import json

    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfake")

    fake_out_root = tmp_path / "mineru_out"
    fake_auto_dir = fake_out_root / "test" / "auto"
    fake_auto_dir.mkdir(parents=True)
    fake_blocks = [
        {"type": "text", "text": "收入", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "2024 年收入如下:", "page_idx": 0},
        {
            "type": "table",
            "table_body": "<table><tr><td>季度</td><td>营收</td></tr><tr><td>Q1</td><td>100</td></tr></table>",
            "table_caption": ["表 1: 季度营收"],
            "table_footnote": [],
            "page_idx": 0,
        },
    ]
    (fake_auto_dir / "test_content_list.json").write_text(
        json.dumps(fake_blocks, ensure_ascii=False)
    )

    async def fake_subprocess_exec(*args, **kwargs):
        return _FakeProc()

    with (
        patch("app.services.pdf_parsers.mineru._OUT_ROOT", fake_out_root),
        patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec),
    ):
        parser = MineruParser()
        doc = await parser.parse(pdf_path)

    assert len(doc.tables) == 1
    assert "Q1" in doc.tables[0].markdown
    assert "100" in doc.tables[0].markdown
    assert doc.tables[0].title is not None and "季度营收" in doc.tables[0].title


def test_pdfparser_factory_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDF_PARSER_MODE switch."""
    from app.services.pdf_parser_factory import build_pdf_parser_from_env

    monkeypatch.setenv("PDF_PARSER_MODE", "mineru")
    p1 = build_pdf_parser_from_env()
    assert isinstance(p1, MineruParser)

    monkeypatch.setenv("PDF_PARSER_MODE", "pdfplumber")
    p2 = build_pdf_parser_from_env()
    assert isinstance(p2, PdfPlumberParser)

    monkeypatch.setenv("PDF_PARSER_MODE", "bogus")
    with pytest.raises(ValueError, match="Unknown PDF_PARSER_MODE"):
        build_pdf_parser_from_env()
