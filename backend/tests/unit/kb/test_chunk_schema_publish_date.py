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
    """publish_date 字段 annotation 必须是 date | None."""
    import typing

    from app.kb.chunkers.base import Chunk

    field_info = Chunk.model_fields["publish_date"]
    # The annotation should allow None (i.e. Optional[date])
    annotation = field_info.annotation
    # get_args returns (date, NoneType) for Optional[date]
    args = typing.get_args(annotation)
    assert date in args, f"publish_date annotation args {args!r} 应含 date"
    assert type(None) in args, f"publish_date annotation args {args!r} 应含 NoneType"


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
