"""SemanticChunkerForResearch — A 研报:LangChain SemanticChunker 集成 + 中文 separators."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.kb.chunkers.base import Chunk, Chunker, count_tokens

if TYPE_CHECKING:
    from app.services.embedding_service import EmbeddingService

from app.services.pdf_parser import ParsedDocument

_RESEARCH_TOKEN_MAX = 800


class SemanticChunkerForResearch(Chunker):
    """研报:用 embedding 相似度切语义边界,fallback 到 RecursiveSplitter 控制 max chunk size。

    实现策略(避免 LangChain 全家依赖):
    1. 在每个 MinerU section 内部按 sentence(中文 "。!?\\n")拆 sentences
    2. 用 EmbeddingService.embed batch 拿每 sentence embedding
    3. 计算相邻 sentence cosine 距离
    4. 距离 > threshold(0.4 default,Spike 后调)→ 切 chunk
    5. 后处理:超过 _RESEARCH_TOKEN_MAX 的 chunk 强制按 RecursiveSplitter 切
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        *,
        breakpoint_threshold: float = 0.4,
    ) -> None:
        self._embedding = embedding_service
        self._threshold = breakpoint_threshold

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0

        for section in doc.sections:
            sentences = self._split_sentences(section.text)
            if not sentences:
                continue

            # < 5 sentences 不做 semantic 分,直接 1 chunk
            if len(sentences) < 5:
                merged = "".join(sentences)
                chunks.extend(self._maybe_split_oversized(merged, section.title, idx))
                idx = len(chunks)
                continue

            embeddings = await self._embedding.embed(sentences)
            distances = self._compute_distances(embeddings)

            current: list[str] = []
            for i, sent in enumerate(sentences):
                current.append(sent)
                # 在 i+1 处判断切 chunk(注意 distances[i] 是 i 与 i+1 的距离)
                if i < len(distances) and distances[i] > self._threshold:
                    merged = "".join(current)
                    chunks.extend(self._maybe_split_oversized(merged, section.title, idx))
                    idx = len(chunks)
                    current = []

            if current:
                merged = "".join(current)
                chunks.extend(self._maybe_split_oversized(merged, section.title, idx))
                idx = len(chunks)

        return chunks

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        import re

        # split keeping the sentence-ending char
        parts = re.split(r"(?<=[。?!])", text)
        return [p for p in parts if p.strip()]

    @staticmethod
    def _compute_distances(embeddings: list[list[float]]) -> list[float]:
        import math

        out: list[float] = []
        for i in range(len(embeddings) - 1):
            a, b = embeddings[i], embeddings[i + 1]
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            similarity = dot / (na * nb) if na > 0 and nb > 0 else 0.0
            out.append(1.0 - similarity)  # cosine distance
        return out

    def _maybe_split_oversized(
        self, text: str, section_title: str | None, idx_start: int
    ) -> list[Chunk]:
        """超过 _RESEARCH_TOKEN_MAX 的 chunk 强制切."""
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        token_count = count_tokens(text)
        if token_count <= _RESEARCH_TOKEN_MAX:
            return [
                Chunk(
                    chunk_index=idx_start,
                    text=text,
                    tokens=token_count,
                    section_title=section_title,
                    is_table=False,
                )
            ]

        # chunk_size=600 chars 对应纯中文 ≈800 tokens(1.33 tokens/char)
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=600,
            chunk_overlap=50,
            separators=["\n\n", "。", "\n", "?", "!", ";", " ", ""],
        )
        out: list[Chunk] = []
        for i, sub in enumerate(splitter.split_text(text)):
            out.append(
                Chunk(
                    chunk_index=idx_start + i,
                    text=sub,
                    tokens=count_tokens(sub),
                    section_title=section_title,
                    is_table=False,
                )
            )
        return out
