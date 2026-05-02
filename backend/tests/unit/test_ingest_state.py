"""L0 — IngestState sqlite 增量去重."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.kb.ingest.state import IngestState


@pytest.mark.asyncio
async def test_state_records_doc(tmp_path: Path) -> None:
    state = IngestState(db_path=tmp_path / ".ingest_state.sqlite")
    await state.init()
    await state.mark_ingested(doc_id="d1", content_hash="abc123", chunk_count=10)

    assert await state.is_ingested(doc_id="d1", content_hash="abc123")


@pytest.mark.asyncio
async def test_state_detects_content_change(tmp_path: Path) -> None:
    """同 doc_id 但 content_hash 变 → is_ingested False(触发重 ingest)."""
    state = IngestState(db_path=tmp_path / ".ingest_state.sqlite")
    await state.init()
    await state.mark_ingested(doc_id="d1", content_hash="hash_v1", chunk_count=5)

    assert not await state.is_ingested(doc_id="d1", content_hash="hash_v2")


@pytest.mark.asyncio
async def test_state_persists_across_instances(tmp_path: Path) -> None:
    db = tmp_path / ".ingest_state.sqlite"
    s1 = IngestState(db_path=db)
    await s1.init()
    await s1.mark_ingested(doc_id="d1", content_hash="x", chunk_count=3)

    s2 = IngestState(db_path=db)
    await s2.init()
    assert await s2.is_ingested(doc_id="d1", content_hash="x")


@pytest.mark.asyncio
async def test_state_force_clear(tmp_path: Path) -> None:
    state = IngestState(db_path=tmp_path / ".ingest_state.sqlite")
    await state.init()
    await state.mark_ingested(doc_id="d1", content_hash="x", chunk_count=3)
    await state.clear_doc("d1")
    assert not await state.is_ingested(doc_id="d1", content_hash="x")
