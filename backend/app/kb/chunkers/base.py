"""Chunker ABC + Chunk model + token 计数."""

from __future__ import annotations

import abc
from datetime import date
from functools import cache
from typing import Any

from pydantic import BaseModel, Field

from app.services.pdf_parser import ParsedDocument


class Chunk(BaseModel):
    chunk_index: int
    text: str
    tokens: int
    section_title: str | None = None
    is_table: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)
    publish_date: date | None = Field(
        default=None,
        description="原文档发布日期 (v1.x DD report backtest 用 — time-travel filter)",
    )


class Chunker(abc.ABC):
    """Chunker ABC. 子类实现 chunk(doc)."""

    @abc.abstractmethod
    async def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...


@cache
def _get_encoder() -> Any:
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Token count via tiktoken cl100k_base(qwen tokenizer 的近似,误差 ±20%)."""
    return len(_get_encoder().encode(text))
