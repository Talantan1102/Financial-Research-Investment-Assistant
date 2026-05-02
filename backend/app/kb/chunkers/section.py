"""SectionChunkerForFinancial — B 财报:section 直接 chunk + table 独立."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.kb.chunkers.base import Chunk, Chunker, count_tokens
from app.services.pdf_parser import ParsedDocument

_SECTION_TOKEN_MAX = 800
_OVERLAP_CHARS = 50
# 中文 tiktoken 估算: ~1.33 tokens/char;600 chars ≈ 800 tokens(最密中文文本的上限)
_CHUNK_SIZE_CHARS = 600


class SectionChunkerForFinancial(Chunker):
    """财报:每个 MinerU section 一个 chunk(若超 800 tokens 用 RecursiveSplitter 二次切),
    tables 独立 chunk(MinerU 转 markdown 形式).

    中文 separators:["\\n\\n", "。", "\\n", "?", "!", ";", " ", ""]
    """

    def __init__(self) -> None:
        # chunk_size=600 chars 对应纯中文 ≈800 tokens(1.33 tokens/char);中英混排更低
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=_CHUNK_SIZE_CHARS,
            chunk_overlap=_OVERLAP_CHARS,
            separators=["\n\n", "。", "\n", "?", "!", ";", " ", ""],
        )

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0

        for section in doc.sections:
            tokens = count_tokens(section.text)
            if tokens <= _SECTION_TOKEN_MAX:
                chunks.append(
                    Chunk(
                        chunk_index=idx,
                        text=section.text,
                        tokens=tokens,
                        section_title=section.title,
                        is_table=False,
                    )
                )
                idx += 1
            else:
                for sub in self._splitter.split_text(section.text):
                    chunks.append(
                        Chunk(
                            chunk_index=idx,
                            text=sub,
                            tokens=count_tokens(sub),
                            section_title=section.title,
                            is_table=False,
                        )
                    )
                    idx += 1

        for table in doc.tables:
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    text=table.markdown,
                    tokens=count_tokens(table.markdown),
                    section_title=table.title,
                    is_table=True,
                    extra={"section_index": table.section_index},
                )
            )
            idx += 1

        return chunks
