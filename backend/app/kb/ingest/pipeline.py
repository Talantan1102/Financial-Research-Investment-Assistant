"""IngestPipeline — 解析 → chunk → embed → Milvus 主流程."""

from __future__ import annotations

import hashlib
import logging
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

            vectors = await self._embed_with_cache(chunks)
            rows = self._chunks_to_rows(spec, chunks, vectors)

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
                "pub_date": spec.metadata.get("pub_date", ""),
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
