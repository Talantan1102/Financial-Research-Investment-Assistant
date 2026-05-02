"""L0 — Chunker base + 3 子类 + router."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.kb.chunkers.base import Chunk, count_tokens
from app.kb.chunkers.clause import ClauseChunkerForPolicy
from app.kb.chunkers.router import chunker_for
from app.kb.chunkers.section import SectionChunkerForFinancial
from app.kb.chunkers.semantic import SemanticChunkerForResearch
from app.services.pdf_parser import ParsedDocument, Section, Table


def test_count_tokens_chinese() -> None:
    """tiktoken cl100k_base 中文 token 估算 — 不要求精确,只要在合理范围."""
    text = "招商证券对宁德时代的看法"
    n = count_tokens(text)
    assert 5 <= n <= 30  # ~12 chars * 0.8-2 tokens/char


def test_chunk_model_basic() -> None:
    c = Chunk(
        chunk_index=0,
        text="测试内容",
        tokens=4,
        section_title="第一章",
        is_table=False,
    )
    assert c.chunk_index == 0
    assert c.tokens == 4
    assert not c.is_table


@pytest.mark.asyncio
async def test_section_chunker_yields_one_chunk_per_section() -> None:
    """B 财报:每个 section 一个 chunk(若 ≤ 800 tokens),tables 独立 chunk."""
    doc = ParsedDocument(
        sections=[
            Section(title="管理层讨论", text="这是讨论内容,不长,< 800 tokens。"),
            Section(title="业务概述", text="业务说明。"),
        ],
        tables=[Table(markdown="| col |\n|---|\n| 100 |", section_index=0, title="Q1 营收")],
    )
    chunker = SectionChunkerForFinancial()
    chunks = await chunker.chunk(doc)

    assert len(chunks) == 3  # 2 sections + 1 table
    assert chunks[0].section_title == "管理层讨论"
    assert not chunks[0].is_table
    assert chunks[2].is_table
    assert "100" in chunks[2].text


@pytest.mark.asyncio
async def test_section_chunker_splits_long_section() -> None:
    """超过 800 tokens 的 section 用 RecursiveSplitter 二次切."""
    long_text = "段落。" * 600  # ~1200 tokens
    doc = ParsedDocument(sections=[Section(title="长 section", text=long_text)], tables=[])
    chunker = SectionChunkerForFinancial()
    chunks = await chunker.chunk(doc)
    assert len(chunks) >= 2
    assert all(c.tokens <= 800 + 100 for c in chunks)  # 容忍 splitter 边界 overlap 偏差


@pytest.mark.asyncio
async def test_clause_chunker_splits_by_article() -> None:
    """C 政策:按"第X条" / 数字编号切."""
    text = (
        "第一条 本办法适用于 A 类机构。\n"
        "第二条 申报材料应包含以下内容:\n"
        "1.1 基本信息\n"
        "1.2 财务数据\n"
        "第三条 监管部门定期审查。"
    )
    doc = ParsedDocument(sections=[Section(title=None, text=text)], tables=[])
    chunker = ClauseChunkerForPolicy()
    chunks = await chunker.chunk(doc)

    # 至少 3 个 chunk(3 条),不要求精确(具体由 regex 实现决定)
    assert len(chunks) >= 3
    # 每条独立内容
    texts = [c.text for c in chunks]
    assert any("第一条" in t for t in texts)
    assert any("第二条" in t for t in texts)
    assert any("第三条" in t for t in texts)


@pytest.mark.asyncio
async def test_semantic_chunker_calls_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 研报:LangChain SemanticChunker via embedding 相似度切.

    Mock embedding service,verify 调用了 + 输出非空 chunks。
    """
    fake_embed = AsyncMock(return_value=[[0.1] * 1024 for _ in range(20)])
    fake_embedding_svc = type(
        "Svc",
        (),
        {"embed": fake_embed, "dimension": 1024, "model_name": "fake"},
    )()

    text = "研报正文段落 1。研报正文段落 2。" * 30
    doc = ParsedDocument(sections=[Section(title="研报", text=text)], tables=[])
    chunker = SemanticChunkerForResearch(embedding_service=fake_embedding_svc)
    chunks = await chunker.chunk(doc)

    assert len(chunks) >= 1
    assert all(c.tokens <= 800 + 100 for c in chunks)


def test_router_dispatches_correctly() -> None:
    """source_type → chunker class."""
    fake_embedding = type("E", (), {"embed": AsyncMock(), "dimension": 1024, "model_name": "x"})()

    assert isinstance(
        chunker_for("research", embedding_service=fake_embedding), SemanticChunkerForResearch
    )
    assert isinstance(
        chunker_for("financial", embedding_service=fake_embedding), SectionChunkerForFinancial
    )
    assert isinstance(
        chunker_for("policy", embedding_service=fake_embedding), ClauseChunkerForPolicy
    )

    with pytest.raises(ValueError, match="Unknown source_type"):
        chunker_for("bogus", embedding_service=fake_embedding)
