"""IngestPipeline — 解析 → chunk → embed → Milvus 主流程."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.kb.chunkers.base import Chunk
from app.kb.chunkers.router import chunker_for
from app.kb.ingest.cache import ChunkEmbedCache
from app.kb.ingest.state import IngestState
from app.services.embedding_service import EmbeddingService
from app.services.milvus_client import MilvusKbClient
from app.services.pdf_parser import PdfParser

logger = logging.getLogger(__name__)


def _parse_pub_date(s: str) -> date | None:
    """Parse pub_date string from spec.metadata. Returns None for empty/malformed.

    Accepts YYYYMMDD (8 digits) and YYYY-MM-DD (10 chars with dashes).
    """
    s = s.strip()
    if not s:
        return None
    try:
        if len(s) == 8 and s.isdigit():
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


class DocSpec(BaseModel):
    """Single doc input to ingest pipeline."""

    doc_id: str
    pdf_path: Path
    collection: str  # "kb_research" / "kb_financial" / "kb_policy"
    source_type: str  # "research" / "financial" / "policy"
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestReport(BaseModel):
    doc_id: str
    success: bool = False
    skipped: bool = False
    chunk_count: int = 0
    error: str | None = None


class IngestPipeline:
    """Per-doc ingest pipeline with caching + state + error isolation."""

    def __init__(
        self,
        *,
        pdf_parser: PdfParser,
        embedding_service: EmbeddingService,
        milvus: MilvusKbClient,
        state: IngestState,
        cache: ChunkEmbedCache,
    ) -> None:
        self._pdf_parser = pdf_parser
        self._embedding = embedding_service
        self._milvus = milvus
        self._state = state
        self._cache = cache

    async def ingest_doc(self, spec: DocSpec, *, force: bool = False) -> IngestReport:
        try:
            content = spec.pdf_path.read_bytes()
            content_hash = hashlib.sha256(content).hexdigest()

            if not force and await self._state.is_ingested(
                doc_id=spec.doc_id, content_hash=content_hash
            ):
                logger.info("ingest_skip doc=%s reason=already_ingested", spec.doc_id)
                return IngestReport(doc_id=spec.doc_id, skipped=True)

            doc = await self._pdf_parser.parse(spec.pdf_path)
            chunker = chunker_for(spec.source_type, embedding_service=self._embedding)
            chunks = await chunker.chunk(doc)

            if not chunks:
                logger.warning("ingest doc=%s no_chunks_extracted", spec.doc_id)
                return IngestReport(doc_id=spec.doc_id, success=False, error="no chunks")

            # Hard cap 切分:任何 chunk text > 4800 chars 强切 — 守 Milvus VARCHAR 5000 上限
            # 和 dashscope embed 8192 tokens 上限(中文 1.33 tokens/char,4800 chars ≈ 6400 tokens)。
            # chunker RecursiveSplitter chunk_size=600 是 soft limit,某些 corpus(财报大段
            # table markdown / 政策长条款)无合适 separator 切不开,在此做 final safety net。
            chunks = self._enforce_chunk_size_cap(chunks)

            # 从 spec.metadata 注入 publish_date(backtest time-travel filter 需要)。
            # chunker 模块无法访问 spec.metadata,统一在 pipeline 层补填。
            raw_pub_date = spec.metadata.get("pub_date", "")
            pub_date = _parse_pub_date(raw_pub_date)
            if raw_pub_date and pub_date is None:
                logger.warning(
                    "ingest doc=%s pub_date 解析失败 raw=%r — chunks 落库 publish_date=None",
                    spec.doc_id,
                    raw_pub_date,
                )
            if pub_date is not None:
                chunks = [c.model_copy(update={"publish_date": pub_date}) for c in chunks]

            vectors = await self._embed_with_cache(chunks)
            rows = self._chunks_to_rows(spec, chunks, vectors)
            rows = self._truncate_varchar_fields(rows)

            await self._milvus.insert(spec.collection, rows)
            await self._state.mark_ingested(
                doc_id=spec.doc_id,
                content_hash=content_hash,
                chunk_count=len(chunks),
            )
            logger.info(
                "ingest_done doc=%s chunks=%d cache_hits=%d cache_misses=%d",
                spec.doc_id,
                len(chunks),
                self._cache.stats["hits"],
                self._cache.stats["misses"],
            )
            return IngestReport(doc_id=spec.doc_id, success=True, chunk_count=len(chunks))

        except Exception as e:  # noqa: BLE001 — error isolation 是设计 intent
            logger.exception("ingest_fail doc=%s", spec.doc_id)
            return IngestReport(doc_id=spec.doc_id, success=False, error=str(e))

    async def ingest_docs(self, specs: list[DocSpec], *, force: bool = False) -> list[IngestReport]:
        reports: list[IngestReport] = []
        for spec in specs:
            report = await self.ingest_doc(spec, force=force)
            reports.append(report)
        return reports

    @staticmethod
    def _enforce_chunk_size_cap(chunks: list[Chunk], max_bytes: int = 4500) -> list[Chunk]:
        """Final cap:任何 chunk.text UTF-8 字节长度 > max_bytes 强切多段。

        ⚠️ Milvus VARCHAR max_length=5000 是 **字节** 不是字符。中文 UTF-8 3 bytes/char,
        5000 bytes ~ 1666 chars max。max_bytes=4500 留 500 bytes margin。
        切片用 UTF-8 byte boundary 回退,避免切断 multi-byte 字符。

        chunker RecursiveSplitter chunk_size 是 char count(soft limit),某些 corpus
        (财报大段 table markdown / 政策长条款)无合适 separator 切不开,在此做 final
        byte-aware safety net。
        """
        out: list[Chunk] = []
        idx = 0
        for c in chunks:
            encoded = c.text.encode("utf-8")
            if len(encoded) <= max_bytes:
                out.append(c.model_copy(update={"chunk_index": idx}))
                idx += 1
            else:
                from app.kb.chunkers.base import count_tokens

                cursor = 0
                while cursor < len(encoded):
                    end = min(cursor + max_bytes, len(encoded))
                    # 回退到 UTF-8 char boundary(non-leading byte: 10xxxxxx,即 & 0xC0 == 0x80)
                    while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
                        end -= 1
                    sub_text = encoded[cursor:end].decode("utf-8")
                    out.append(
                        c.model_copy(
                            update={
                                "chunk_index": idx,
                                "text": sub_text,
                                "tokens": count_tokens(sub_text),
                            }
                        )
                    )
                    cursor = end
                    idx += 1
        return out

    async def _embed_with_cache(self, chunks: list[Chunk]) -> list[list[float]]:
        """Cache miss 的 chunks 批量 embed,hit 的直接拿."""
        cached: dict[int, list[float]] = {}
        miss_indices: list[int] = []
        miss_texts: list[str] = []
        for i, c in enumerate(chunks):
            v = await self._cache.get(c.text, self._embedding.model_name, self._embedding.dimension)
            if v is None:
                miss_indices.append(i)
                miss_texts.append(c.text)
            else:
                cached[i] = v

        if miss_texts:
            new_vectors = await self._embedding.embed(miss_texts)
            for i, text, vec in zip(miss_indices, miss_texts, new_vectors, strict=True):
                await self._cache.set(
                    text, self._embedding.model_name, self._embedding.dimension, vec
                )
                cached[i] = vec

        return [cached[i] for i in range(len(chunks))]

    # Milvus VARCHAR field byte-length limits(对应 milvus_client.py schema 锁死值,
    # 单位是 UTF-8 字节,不是字符)。MinerU 切出的 section title / metadata 偶尔
    # 超限(例如 maotai 财报某个 section 53 bytes 超 50 byte limit),需 truncate。
    _VARCHAR_BYTE_LIMITS: dict[str, int] = {
        "chunk_id": 80,
        "doc_id": 64,
        "chunk_text": 5000,
        "pub_date": 10,
        "source_url": 500,
        "source_type": 20,
        # research
        "broker": 50,
        "industry": 50,
        "rating": 20,
        "analyst": 100,
        # financial
        "company_code": 10,
        "company_name": 100,
        "fiscal_quarter": 4,
        "section": 50,
        # policy
        "issuer": 50,
        "doc_number": 50,
        "scope": 100,
    }

    @classmethod
    def _truncate_varchar_fields(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Final safety net:按 schema VARCHAR byte limits 截断每个 row 的 string 值。

        Byte-aware truncate(回退到 UTF-8 char boundary 避免切断 multi-byte char)。
        """
        for row in rows:
            for k, v in list(row.items()):
                if not isinstance(v, str):
                    continue
                limit = cls._VARCHAR_BYTE_LIMITS.get(k)
                if limit is None:
                    continue
                encoded = v.encode("utf-8")
                if len(encoded) <= limit:
                    continue
                # byte-aware truncate
                end = limit
                while end < len(encoded) and (encoded[end] & 0xC0) == 0x80:
                    end -= 1
                row[k] = encoded[:end].decode("utf-8")
        return rows

    @staticmethod
    def _chunks_to_rows(
        spec: DocSpec, chunks: list[Chunk], vectors: list[list[float]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for c, v in zip(chunks, vectors, strict=True):
            row: dict[str, Any] = {
                "doc_id": spec.doc_id,
                "chunk_id": f"{spec.doc_id}::{c.chunk_index}",
                "chunk_index": c.chunk_index,
                "chunk_text": c.text,
                "vector": v,
                "pub_date": c.publish_date.isoformat()
                if c.publish_date is not None
                else spec.metadata.get("pub_date", ""),
                "source_url": spec.metadata.get("source_url", ""),
                "source_type": spec.source_type,
            }
            # 类型特定字段
            if spec.source_type == "research":
                row.update(
                    {
                        "broker": spec.metadata.get("broker", ""),
                        "industry": spec.metadata.get("industry", ""),
                        "rating": spec.metadata.get("rating", ""),
                        "target_price": spec.metadata.get("target_price", 0.0),
                        "analyst": spec.metadata.get("analyst", ""),
                    }
                )
            elif spec.source_type == "financial":
                row.update(
                    {
                        "company_code": spec.metadata.get("company_code", ""),
                        "company_name": spec.metadata.get("company_name", ""),
                        "fiscal_year": spec.metadata.get("fiscal_year", 0),
                        "fiscal_quarter": spec.metadata.get("fiscal_quarter", ""),
                        "section": c.section_title or "",
                    }
                )
            elif spec.source_type == "policy":
                row.update(
                    {
                        "issuer": spec.metadata.get("issuer", ""),
                        "doc_number": spec.metadata.get("doc_number", ""),
                        "scope": spec.metadata.get("scope", ""),
                    }
                )
            rows.append(row)
        return rows
