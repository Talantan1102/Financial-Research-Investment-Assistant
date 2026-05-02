"""build_pdf_parser_from_env — PDF_PARSER_MODE switch."""

from __future__ import annotations

import os

from app.services.pdf_parser import PdfParser
from app.services.pdf_parsers.mineru import MineruParser
from app.services.pdf_parsers.pdfplumber import PdfPlumberParser


def build_pdf_parser_from_env() -> PdfParser:
    """Build PdfParser based on PDF_PARSER_MODE env var.

    Values:
      - "mineru"(default): MinerU 3.x CLI subprocess(7GB 模型本地)
      - "pdfplumber": fallback / CI 模式,跳表格
    """
    mode = os.getenv("PDF_PARSER_MODE", "mineru")
    if mode == "mineru":
        return MineruParser()
    if mode == "pdfplumber":
        return PdfPlumberParser()
    raise ValueError(f"Unknown PDF_PARSER_MODE: {mode!r}; expected 'mineru' or 'pdfplumber'")
