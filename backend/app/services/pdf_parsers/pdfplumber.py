"""PdfPlumberParser — fallback / CI 模式.

简化版:跳表格(financial corpus 表格用 MinerU 主力 backend),只提取文本段落。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pdfplumber

from app.services.pdf_parser import ParsedDocument, Section


class PdfPlumberParser:
    async def parse(self, pdf_path: Path) -> ParsedDocument:
        return await asyncio.to_thread(self._parse_sync, pdf_path)

    def _parse_sync(self, pdf_path: Path) -> ParsedDocument:
        sections: list[Section] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                # 简单按 \n\n 切段,每段一个 Section(后续 Chunker 再细切)
                for paragraph in [p.strip() for p in text.split("\n\n") if p.strip()]:
                    sections.append(Section(title=None, text=paragraph, section_type="paragraph"))
        # tables 跳过(spec 决策七 fallback 妥协)
        return ParsedDocument(sections=sections, tables=[], metadata={})
