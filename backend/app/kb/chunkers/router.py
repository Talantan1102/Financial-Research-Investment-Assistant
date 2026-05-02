"""chunker_for(source_type) — 类型路由."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.kb.chunkers.base import Chunker
from app.kb.chunkers.clause import ClauseChunkerForPolicy
from app.kb.chunkers.section import SectionChunkerForFinancial
from app.kb.chunkers.semantic import SemanticChunkerForResearch

if TYPE_CHECKING:
    from app.services.embedding_service import EmbeddingService


def chunker_for(source_type: str, *, embedding_service: EmbeddingService) -> Chunker:
    """Route source_type → chunker class.

    源类型(corpus 类):
      - "research" → SemanticChunkerForResearch(embedding 相似度切)
      - "financial" → SectionChunkerForFinancial(MinerU sections + table)
      - "policy" → ClauseChunkerForPolicy(条款 regex)
    """
    if source_type == "research":
        return SemanticChunkerForResearch(embedding_service=embedding_service)
    if source_type == "financial":
        return SectionChunkerForFinancial()
    if source_type == "policy":
        return ClauseChunkerForPolicy()
    raise ValueError(
        f"Unknown source_type: {source_type!r}; expected 'research'|'financial'|'policy'"
    )
