"""L0 — HierarchicalMemory DI 接受 embed_cache + prompt_cache_store + injection_classifier(契约 § 3, § 9)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.memory.hierarchical import HierarchicalMemory


def test_default_di_all_none() -> None:
    """所有 cost optimization DI 默认 None, Plan 1B 测试不破坏."""
    mem = HierarchicalMemory(
        pg_session_factory=MagicMock(),
        age_executor=MagicMock(),
        milvus_client=MagicMock(),
        embed_service=MagicMock(),
        llm_extractor=MagicMock(),
        llm_judge=MagicMock(),
    )
    assert mem._injection_classifier is None
    assert mem._embed_cache is None
    assert mem._prompt_cache_store is None


def test_explicit_di_wired() -> None:
    classifier = MagicMock()
    embed_cache = MagicMock()
    pc_store = MagicMock()
    mem = HierarchicalMemory(
        pg_session_factory=MagicMock(),
        age_executor=MagicMock(),
        milvus_client=MagicMock(),
        embed_service=MagicMock(),
        llm_extractor=MagicMock(),
        llm_judge=MagicMock(),
        injection_classifier=classifier,
        embed_cache=embed_cache,
        prompt_cache_store=pc_store,
    )
    assert mem._injection_classifier is classifier
    assert mem._embed_cache is embed_cache
    assert mem._prompt_cache_store is pc_store


def test_only_embed_cache_wired() -> None:
    """部分 DI 注入仍工作 (None 默认补齐其他)."""
    embed_cache = MagicMock()
    mem = HierarchicalMemory(
        pg_session_factory=MagicMock(),
        age_executor=MagicMock(),
        milvus_client=MagicMock(),
        embed_service=MagicMock(),
        llm_extractor=MagicMock(),
        llm_judge=MagicMock(),
        embed_cache=embed_cache,
    )
    assert mem._embed_cache is embed_cache
    assert mem._prompt_cache_store is None
    assert mem._injection_classifier is None
