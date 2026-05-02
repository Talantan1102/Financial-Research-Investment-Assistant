"""L2 e2e — IngestPipeline 一份 doc 全链路(MinerU 本地 + qwen embed cassette)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.kb.ingest.cache import ChunkEmbedCache
from app.kb.ingest.pipeline import DocSpec, IngestPipeline
from app.kb.ingest.state import IngestState
from app.services.embedding_factory import build_embedding_service_from_env
from app.services.milvus_client import COLLECTION_POLICY, MilvusKbClient
from app.services.pdf_parser_factory import build_pdf_parser_from_env

pytestmark = pytest.mark.vcr


@pytest.fixture
def small_pdf_path() -> Path:
    p = Path("data/sample_corpus/policy/2024_csrc_xinnengyuanche.pdf")
    if not p.exists():
        pytest.skip(f"sample PDF not present: {p}")
    return p


@pytest.mark.asyncio
async def test_ingest_one_doc_e2e_cassette(
    milvus_test_container: dict[str, Any],
    small_pdf_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端:解析 → chunk → embed(cassette)→ Milvus → re-ingest skip / force cache hit."""
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")
    monkeypatch.setenv("PDF_PARSER_MODE", "mineru")
    monkeypatch.setenv("MILVUS_HOST", str(milvus_test_container["host"]))
    monkeypatch.setenv("MILVUS_PORT", str(milvus_test_container["port"]))

    parser = build_pdf_parser_from_env()
    embedding = build_embedding_service_from_env()
    milvus = MilvusKbClient(
        host=str(milvus_test_container["host"]),
        port=int(milvus_test_container["port"]),
    )
    await milvus.drop_all()
    await milvus.ensure_collections()

    state = IngestState(db_path=tmp_path / ".state.sqlite")
    await state.init()
    cache = ChunkEmbedCache(db_path=tmp_path / ".cache.sqlite")
    await cache.init()

    pipeline = IngestPipeline(
        pdf_parser=parser,
        embedding_service=embedding,
        milvus=milvus,
        state=state,
        cache=cache,
    )

    spec = DocSpec(
        doc_id="e2e_csrc_test",
        pdf_path=small_pdf_path,
        collection=COLLECTION_POLICY,
        source_type="policy",
        metadata={
            "issuer": "证监会",
            "doc_number": "[2024]18号",
            "scope": "上市公司新能源车业务披露",
            "pub_date": "2024-04-15",
            "source_url": "",
        },
    )

    report = await pipeline.ingest_doc(spec)
    assert report.success
    assert report.chunk_count > 0
    assert cache.stats["misses"] == report.chunk_count

    report2 = await pipeline.ingest_doc(spec)
    assert report2.skipped

    report3 = await pipeline.ingest_doc(spec, force=True)
    assert report3.success
    assert cache.stats["hits"] >= report3.chunk_count
