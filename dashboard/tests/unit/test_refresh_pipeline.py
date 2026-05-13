"""RefreshPipeline L0 — 5 个 step 独立路径 + milvus 降级 4 种 + critical 错误。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from dashboard.derive.refresh_pipeline import RefreshPipeline, StepEvent

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIG_DIR = PROJECT_ROOT / "dashboard" / "config"


@pytest.fixture
def pipeline(tmp_path: Path) -> RefreshPipeline:
    return RefreshPipeline(
        project_root=PROJECT_ROOT,
        config_dir=REAL_CONFIG_DIR,
        db_path=tmp_path / "board.db",
        seed_path=PROJECT_ROOT / "dashboard" / "data" / "deep_cards_seed.jsonl",
    )


def test_step_event_dataclass_shape() -> None:
    ev = StepEvent(step="chip_resolve", status="done", label="x", detail="y", duration_ms=5)
    assert ev.step == "chip_resolve"
    # status 只接受 4 个文字量(运行时不严格,但实现需 Literal 标注)
    valid: set[Literal["running", "done", "skip", "error"]] = {"running", "done", "skip", "error"}
    assert ev.status in valid


def test_chip_resolve_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._chip_resolve_step()
    assert ev.step == "chip_resolve"
    assert ev.status == "done"
    assert "chip" in ev.detail.lower() or ev.detail  # 实现给出 detail
    assert ev.duration_ms >= 0


def test_seed_ingest_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._seed_ingest_step()  # type: ignore[attr-defined]
    assert ev.step == "seed_ingest"
    assert ev.status == "done"
    # detail 应含 "insert"/"skip" 计数
    assert "insert" in ev.detail or "skipped" in ev.detail


def test_decision_extract_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._decision_extract_step()  # type: ignore[attr-defined]
    assert ev.step == "decision_extract"
    assert ev.status == "done"
    # 至少抽出一个决策(本仓 specs 多)
    assert "entries" in ev.detail or "decision" in ev.detail.lower()


def test_snapshot_finalize_step_returns_done(pipeline: RefreshPipeline) -> None:
    ev = pipeline._snapshot_finalize_step()  # type: ignore[attr-defined]
    assert ev.step == "snapshot_finalize"
    assert ev.status == "done"
    assert "refreshed_at" in ev.detail or "snapshot" in ev.detail.lower()


def test_milvus_reindex_skip_when_host_missing(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.step == "milvus_reindex"
    assert ev.status == "skip"
    assert "milvus disabled" in ev.detail.lower()


def test_milvus_reindex_skip_when_embedding_key_missing(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "embedding" in ev.detail.lower() and "missing" in ev.detail.lower()


def test_milvus_reindex_skip_when_milvus_unreachable(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    async def _raise_connection_error(self_: object) -> None:
        raise ConnectionError("milvus boom")

    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.ensure_collection",
        _raise_connection_error,
    )
    # 防真的连接 Milvus(__init__ 也连):patch __init__ no-op
    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.__init__",
        lambda self, **kw: None,
    )

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "unreachable" in ev.detail.lower()


def test_milvus_reindex_skip_when_embedding_call_fails(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_BOARD_MILVUS_HOST", "localhost")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")

    # 让 ensure_collection 不抛(假装连上)
    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.__init__",
        lambda self, **kw: None,
    )

    async def _noop_ensure(self_: object) -> None:
        return None

    monkeypatch.setattr(
        "dashboard.state.milvus_collection.DeepCardMilvusClient.ensure_collection", _noop_ensure
    )

    class _BoomEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom embedding")

    monkeypatch.setattr(
        "app.services.embedding_factory.build_embedding_service_from_env",
        lambda: _BoomEmbedder(),
    )

    # 先塞一张 deep_card,否则 cards 列表空就直接 done with 0 upserts
    from dashboard.derive.deep_card_types import DeepCard
    from dashboard.state.db import open_db
    from dashboard.state.repositories import DeepCardRepo

    conn = open_db(pipeline.db_path)
    try:
        DeepCardRepo(conn).upsert(DeepCard(cap_id="memory.long_term_memory", what="x"))
    finally:
        conn.close()

    import asyncio

    ev = asyncio.run(pipeline._milvus_reindex_step())  # type: ignore[attr-defined]
    assert ev.status == "skip"
    assert "embedding error" in ev.detail.lower()


def test_stream_yields_all_5_steps_in_order(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    import asyncio

    async def _collect() -> list[StepEvent]:
        return [e async for e in pipeline.stream()]

    events = asyncio.run(_collect())
    # 每 step 一 running + 一 done|skip|error,共 5×2 = 10
    assert len(events) == 10
    expected_order = [
        "chip_resolve",
        "chip_resolve",
        "seed_ingest",
        "seed_ingest",
        "decision_extract",
        "decision_extract",
        "milvus_reindex",
        "milvus_reindex",
        "snapshot_finalize",
        "snapshot_finalize",
    ]
    assert [e.step for e in events] == expected_order
    assert [e.status for e in events[::2]] == ["running"] * 5
    # milvus skip,其他 done
    statuses = [e.status for e in events[1::2]]
    assert statuses == ["done", "done", "done", "skip", "done"]


def test_stream_yields_error_event_when_chip_resolve_raises(
    pipeline: RefreshPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)

    def _boom(_self: object) -> StepEvent:
        raise RuntimeError("chip resolve boom")

    monkeypatch.setattr(RefreshPipeline, "_chip_resolve_step", _boom)

    import asyncio

    async def _collect() -> list[StepEvent]:
        return [e async for e in pipeline.stream()]

    events = asyncio.run(_collect())
    # chip_resolve running + error,但后续 step 仍然跑(spec § 2.4 不取消,只标 step error)
    chip_events = [e for e in events if e.step == "chip_resolve"]
    assert len(chip_events) == 2
    assert chip_events[0].status == "running"
    assert chip_events[1].status == "error"
    assert "boom" in chip_events[1].detail
    # snapshot_finalize 总是跑
    assert any(e.step == "snapshot_finalize" and e.status == "done" for e in events)
