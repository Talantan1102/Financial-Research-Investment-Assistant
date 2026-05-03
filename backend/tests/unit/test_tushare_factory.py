"""Unit tests for tushare_factory — env-driven mock/real switch."""

from __future__ import annotations

import pytest
from app.services.tushare_factory import build_tushare_service


@pytest.mark.skip(reason="depends on Task 4 LegacyMockTushareAdapter")
def test_default_mode_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TUSHARE_MODE", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    svc = build_tushare_service()
    # Mock svc 类型是 LegacyMockTushareAdapter,具体名后 Task 4 引入,这里只验返回非 None
    assert svc is not None


def test_real_mode_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    with pytest.raises(KeyError, match="TUSHARE_TOKEN"):
        build_tushare_service()


def test_real_mode_with_token_returns_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "real")
    monkeypatch.setenv("TUSHARE_TOKEN", "fake-token")
    svc = build_tushare_service()
    from app.services.tushare_service import RealTushareService

    assert isinstance(svc, RealTushareService)


def test_invalid_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUSHARE_MODE", "weird")
    with pytest.raises(ValueError, match="TUSHARE_MODE"):
        build_tushare_service()
