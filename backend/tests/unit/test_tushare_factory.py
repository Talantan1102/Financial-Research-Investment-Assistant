"""Unit tests for tushare_factory — env-driven mock/real switch."""

from __future__ import annotations

import pytest
from app.services.tushare_factory import build_tushare_service


def test_default_mode_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TUSHARE_MODE", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    svc = build_tushare_service()
    from app.services.tushare_mock_adapter import LegacyMockTushareAdapter

    assert isinstance(svc, LegacyMockTushareAdapter)


def test_real_mode_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(KeyError, match="TUSHARE_TOKEN"):
        build_tushare_service()


def test_real_mode_with_token_returns_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    monkeypatch.delenv("TUSHARE_BASE_URL", raising=False)
    svc = build_tushare_service()
    from app.services.tushare_service import RealTushareService

    assert isinstance(svc, RealTushareService)


def test_real_mode_uses_official_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TUSHARE_BASE_URL unset, factory must use official host so VCR cassettes match."""
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    monkeypatch.delenv("TUSHARE_BASE_URL", raising=False)
    svc = build_tushare_service()
    from app.services.tushare_service import RealTushareService

    assert isinstance(svc, RealTushareService)
    assert svc._client.base_url == "http://api.tushare.pro"


def test_real_mode_overrides_base_url_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """TUSHARE_BASE_URL env overrides default — production uses proxy, cassette uses official."""
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    monkeypatch.setenv("TUSHARE_BASE_URL", "http://example.com/dataapi")
    svc = build_tushare_service()
    from app.services.tushare_service import RealTushareService

    assert isinstance(svc, RealTushareService)
    assert svc._client.base_url == "http://example.com/dataapi"


def test_invalid_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "weird")
    with pytest.raises(ValueError, match="TUSHARE_MODE"):
        build_tushare_service()
