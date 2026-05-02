"""PdfParser Protocol + ParsedDocument / Section / Table model.

详见 spec docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md 节 7。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

SectionType = Literal["heading", "paragraph", "list", "code", "other"]


class Section(BaseModel):
    title: str | None = None
    text: str
    section_type: SectionType = "paragraph"


class Table(BaseModel):
    markdown: str
    title: str | None = None
    section_index: int = 0


class ParsedDocument(BaseModel):
    sections: list[Section] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class PdfParser(Protocol):
    """PDF 解析 backend Protocol;通过 PDF_PARSER_MODE 切换."""

    async def parse(self, pdf_path: Path) -> ParsedDocument:
        """解析 PDF 文件,返回结构化 sections + tables + metadata."""
        ...
