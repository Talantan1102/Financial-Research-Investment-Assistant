"""L0 — IngestPipeline(全 mock 跑通主流程 + 错误隔离)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.kb.ingest.cache import ChunkEmbedCache
from app.kb.ingest.pipeline import DocSpec, IngestPipeline
from app.kb.ingest.state import IngestState
from app.services.pdf_parser import ParsedDocument, Section


@pytest.fixture
def fake_pdf_parser() -> MagicMock:
    parser = MagicMock()
    parser.parse = AsyncMock(
        return_value=ParsedDocument(
            sections=[Section(title=None, text="测试段落 1。" * 30)],
            tables=[],
            metadata={},
        )
    )
    return parser


@pytest.fixture
def fake_embedding() -> MagicMock:
    svc = MagicMock()
    svc.embed = AsyncMock(side_effect=lambda texts: [[0.1] * 1024 for _ in texts])
    svc.dimension = 1024
    svc.model_name = "text-embedding-v3"
    return svc


@pytest.fixture
def fake_milvus() -> MagicMock:
    cli = MagicMock()
    cli.ensure_collections = AsyncMock()
    cli.insert = AsyncMock()
    return cli


@pytest.mark.asyncio
async def test_pipeline_ingests_one_doc(
    tmp_path: Path,
    fake_pdf_parser: MagicMock,
    fake_embedding: MagicMock,
    fake_milvus: MagicMock,
) -> None:
    pdf = tmp_path / "doc1.pdf"
    pdf.write_bytes(b"%PDF\nfake")

    state = IngestState(db_path=tmp_path / ".state.sqlite")
    await state.init()
    cache = ChunkEmbedCache(db_path=tmp_path / ".cache.sqlite")
    await cache.init()

    pipeline = IngestPipeline(
        pdf_parser=fake_pdf_parser,
        embedding_service=fake_embedding,
        milvus=fake_milvus,
        state=state,
        cache=cache,
    )

    spec = DocSpec(
        doc_id="d1",
        pdf_path=pdf,
        collection="kb_research",
        source_type="research",
        metadata={"broker": "招商证券"},
    )
    report = await pipeline.ingest_doc(spec)

    assert report.success
    assert report.chunk_count > 0
    assert fake_milvus.insert.called
    assert fake_embedding.embed.called

    # 第二次 ingest 同 doc 应该跳过(content_hash 不变)
    fake_embedding.embed.reset_mock()
    fake_milvus.insert.reset_mock()
    report2 = await pipeline.ingest_doc(spec)
    assert report2.skipped
    assert not fake_embedding.embed.called
    assert not fake_milvus.insert.called


@pytest.mark.asyncio
async def test_pipeline_uses_cache_for_repeated_chunks(
    tmp_path: Path,
    fake_pdf_parser,
    fake_embedding,
    fake_milvus,
) -> None:
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF\nfake")
    state = IngestState(db_path=tmp_path / ".state.sqlite")
    await state.init()
    cache = ChunkEmbedCache(db_path=tmp_path / ".cache.sqlite")
    await cache.init()

    fake_pdf_parser.parse.return_value = ParsedDocument(
        sections=[
            Section(title=None, text="可缓存段落 A"),
            Section(title=None, text="未缓存段落 B"),
        ],
        tables=[],
        metadata={},
    )
    # Pre-populate cache for "可缓存段落 A"(模拟之前 ingest 过的 chunk)
    await cache.set("可缓存段落 A", "text-embedding-v3", 1024, [0.5] * 1024)

    pipeline = IngestPipeline(
        pdf_parser=fake_pdf_parser,
        embedding_service=fake_embedding,
        milvus=fake_milvus,
        state=state,
        cache=cache,
    )
    spec = DocSpec(
        doc_id="d1", pdf_path=pdf, collection="kb_research", source_type="research", metadata={}
    )
    await pipeline.ingest_doc(spec)

    # embed call 应该只发未缓存的 1 个 chunk(不是 2 个)
    args, kwargs = fake_embedding.embed.call_args_list[-1]
    embed_input = args[0] if args else kwargs.get("texts")
    assert len(embed_input) == 1
    assert "未缓存" in embed_input[0]


@pytest.mark.asyncio
async def test_pipeline_isolates_failed_doc(
    tmp_path: Path,
    fake_pdf_parser,
    fake_embedding,
    fake_milvus,
) -> None:
    """1 doc parse 失败,后续 doc 仍能 ingest."""
    pdf1 = tmp_path / "bad.pdf"
    pdf1.write_bytes(b"x")
    pdf2 = tmp_path / "good.pdf"
    pdf2.write_bytes(b"%PDF\nok")

    parse_calls = {"n": 0}

    async def parse_side_effect(p: Path):
        parse_calls["n"] += 1
        if parse_calls["n"] == 1:
            raise RuntimeError("PDF parse failed")
        return ParsedDocument(
            sections=[Section(title=None, text="ok段落 1。" * 30)], tables=[], metadata={}
        )

    fake_pdf_parser.parse = parse_side_effect

    state = IngestState(db_path=tmp_path / ".state.sqlite")
    await state.init()
    cache = ChunkEmbedCache(db_path=tmp_path / ".cache.sqlite")
    await cache.init()

    pipeline = IngestPipeline(
        pdf_parser=fake_pdf_parser,
        embedding_service=fake_embedding,
        milvus=fake_milvus,
        state=state,
        cache=cache,
    )

    specs = [
        DocSpec(
            doc_id="bad",
            pdf_path=pdf1,
            collection="kb_research",
            source_type="research",
            metadata={},
        ),
        DocSpec(
            doc_id="good",
            pdf_path=pdf2,
            collection="kb_research",
            source_type="research",
            metadata={},
        ),
    ]
    reports = await pipeline.ingest_docs(specs)

    assert len(reports) == 2
    assert not reports[0].success
    assert reports[0].error is not None
    assert reports[1].success
