"""KB Chunk schema 加 publish_date 字段 + pipeline _parse_pub_date — Phase 1 Task 1.3.

spec § 9 风险 #5
"""

from __future__ import annotations

from datetime import date


def test_chunk_schema_has_publish_date_field() -> None:
    """Chunk Pydantic schema 必须含 publish_date: date | None 字段."""
    from app.kb.chunkers.base import Chunk

    fields = Chunk.model_fields
    assert "publish_date" in fields, (
        "Chunk schema 必须含 publish_date 字段 (time-travel 数据控制需要)"
    )


def test_chunk_publish_date_optional() -> None:
    """publish_date 默认 None — 兼容历史已 ingest 的 chunk."""
    from app.kb.chunkers.base import Chunk

    # Construct with only required fields
    chunk = Chunk(chunk_index=0, text="测试财报数据", tokens=10)
    assert chunk.publish_date is None


def test_chunk_publish_date_accepts_date_value() -> None:
    """publish_date 可设为 date 类型."""
    from app.kb.chunkers.base import Chunk

    chunk = Chunk(
        chunk_index=0,
        text="2024 Q2 财报",
        tokens=8,
        publish_date=date(2024, 7, 30),
    )
    assert chunk.publish_date == date(2024, 7, 30)


def test_chunk_publish_date_field_type() -> None:
    """publish_date 字段必须是非必填字段 (is_required() == False)."""
    from app.kb.chunkers.base import Chunk

    assert Chunk.model_fields["publish_date"].is_required() is False, (
        "publish_date 应为可选字段 (默认 None),不能是 required"
    )


# ---------------------------------------------------------------------------
# _parse_pub_date helper 单元测试
# ---------------------------------------------------------------------------


def test_parse_pub_date_yyyymmdd() -> None:
    """YYYYMMDD 8-digit format 应被正确解析."""
    from app.kb.ingest.pipeline import _parse_pub_date

    assert _parse_pub_date("20240730") == date(2024, 7, 30)


def test_parse_pub_date_iso_format() -> None:
    """YYYY-MM-DD ISO format 应被正确解析."""
    from app.kb.ingest.pipeline import _parse_pub_date

    assert _parse_pub_date("2024-07-30") == date(2024, 7, 30)


def test_parse_pub_date_empty_string_returns_none() -> None:
    """空字符串应返回 None."""
    from app.kb.ingest.pipeline import _parse_pub_date

    assert _parse_pub_date("") is None
    assert _parse_pub_date("   ") is None


def test_parse_pub_date_malformed_returns_none() -> None:
    """格式错误的字符串应返回 None 而非抛异常."""
    from app.kb.ingest.pipeline import _parse_pub_date

    assert _parse_pub_date("not-a-date") is None
    assert _parse_pub_date("2024/07/30") is None
    assert _parse_pub_date("99999999") is None


# ---------------------------------------------------------------------------
# I1 回归测试: _chunks_to_rows pub_date 行与 Chunk.publish_date 一致
# ---------------------------------------------------------------------------


def test_chunks_to_rows_pub_date_iso_from_parsed_chunk() -> None:
    """I1 回归: chunk.publish_date=date(2024,7,30) → Milvus row pub_date='2024-07-30' (ISO).

    raw spec.metadata 可以是 malformed ('2024/07/30'),但 Milvus 行必须用 parsed
    publish_date.isoformat(),保证 T1.5 KBBacktestAdapter strict-mode 可靠过滤。
    """
    from pathlib import Path

    from app.kb.chunkers.base import Chunk
    from app.kb.ingest.pipeline import DocSpec, IngestPipeline

    parsed_date = date(2024, 7, 30)
    chunk = Chunk(
        chunk_index=0,
        text="Q2 财报摘要",
        tokens=8,
        publish_date=parsed_date,
    )
    spec = DocSpec(
        doc_id="test_doc_001",
        pdf_path=Path("/dev/null"),
        collection="kb_research",
        source_type="research",
        metadata={"pub_date": "2024/07/30"},  # malformed raw — should NOT appear in row
    )
    dummy_vector: list[float] = [0.0] * 4

    rows = IngestPipeline._chunks_to_rows(spec, [chunk], [dummy_vector])

    assert len(rows) == 1
    assert rows[0]["pub_date"] == "2024-07-30", (
        f"Milvus row pub_date 应为 ISO 格式 '2024-07-30',实际得到 {rows[0]['pub_date']!r}. "
        "raw malformed '2024/07/30' 不得直接写入 row (I1 回归)"
    )


def test_chunks_to_rows_pub_date_empty_when_publish_date_none() -> None:
    """I1 边界: chunk.publish_date=None + spec.metadata pub_date='' → row pub_date=''."""
    from pathlib import Path

    from app.kb.chunkers.base import Chunk
    from app.kb.ingest.pipeline import DocSpec, IngestPipeline

    chunk = Chunk(chunk_index=0, text="无日期文档", tokens=6)
    spec = DocSpec(
        doc_id="test_doc_002",
        pdf_path=Path("/dev/null"),
        collection="kb_research",
        source_type="research",
        metadata={},
    )
    dummy_vector: list[float] = [0.0] * 4

    rows = IngestPipeline._chunks_to_rows(spec, [chunk], [dummy_vector])

    assert rows[0]["pub_date"] == ""
