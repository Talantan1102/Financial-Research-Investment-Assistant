"""ClauseChunkerForPolicy — C 政策:按"第X条" / 数字编号切."""

from __future__ import annotations

import re

from app.kb.chunkers.base import Chunk, Chunker, count_tokens
from app.services.pdf_parser import ParsedDocument

_CLAUSE_PATTERNS = [
    r"(?=第[一二三四五六七八九十百千零0-9]+条)",
    r"(?=第[一二三四五六七八九十百千零0-9]+款)",
    r"(?=\n\d+\.\d+\s)",
]


class ClauseChunkerForPolicy(Chunker):
    """政策:已有天然边界,按条款拆分,无 overlap。条款短(<500 tokens)也保留独立 chunk."""

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0

        # 合并所有 sections text(政策 corpus section 边界不重要,条款边界才重要)
        full_text = "\n".join(s.text for s in doc.sections if s.text.strip())

        clauses = self._split_by_clauses(full_text)
        for clause in clauses:
            clause_stripped = clause.strip()
            if not clause_stripped:
                continue
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    text=clause_stripped,
                    tokens=count_tokens(clause_stripped),
                    section_title=None,
                    is_table=False,
                )
            )
            idx += 1

        return chunks

    @staticmethod
    def _split_by_clauses(text: str) -> list[str]:
        # combined regex split by all clause patterns(lookahead 保留分隔符在结果里)
        combined = "|".join(_CLAUSE_PATTERNS)
        parts = re.split(combined, text)
        return [p for p in parts if p and p.strip()]
