"""L0 — kb_factory KB_MODE switch + MockKbSearchService Protocol."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.services.kb_factory import build_kb_search_service_from_env
from app.services.kb_search_service import KbHit, KbSearchService
from app.services.mock_kb_service import MockKbSearchService
from app.services.reliable_kb_service import ReliableKbSearchService


def test_mock_kb_service_implements_protocol() -> None:
    svc = MockKbSearchService()
    assert isinstance(svc, KbSearchService)


@pytest.mark.asyncio
async def test_mock_kb_service_returns_canned_hits() -> None:
    """MockKbSearchService 用固定 stub 数据(不依赖外部 API)."""
    svc = MockKbSearchService()
    hits = await svc.search(query="test", top_k=3)
    assert isinstance(hits, list)
    assert all(isinstance(h, KbHit) for h in hits)
    assert len(hits) <= 3


def test_factory_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_MODE", "mock")
    svc = build_kb_search_service_from_env()
    # mock 模式不包 ReliableKbSearchService(避免 cache 隐藏 mock 行为)
    assert isinstance(svc, MockKbSearchService)


def test_factory_real_mode_wraps_with_reliable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_MODE", "real")
    monkeypatch.setenv("MILVUS_HOST", "127.0.0.1")
    monkeypatch.setenv("MILVUS_PORT", "19530")
    monkeypatch.setenv("EMBEDDING_MODE", "qwen")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-fake")
    with patch("app.services.kb_factory.MilvusKbClient") as MockClient:
        MockClient.return_value = MagicMock()
        svc = build_kb_search_service_from_env()
    assert isinstance(svc, ReliableKbSearchService)


def test_factory_unknown_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_MODE", "bogus")
    with pytest.raises(ValueError, match="Unknown KB_MODE"):
        build_kb_search_service_from_env()
