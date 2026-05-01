"""L0 — BochaService Protocol satisfaction + factory mode selection."""

from typing import Any

import pytest
from app.services.bocha_factory import build_bocha_service_from_env


def _supports_protocol(obj: Any) -> bool:
    """Duck-type Protocol check."""
    return hasattr(obj, "search") and callable(obj.search)


def test_factory_mock_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOCHA_MODE", raising=False)
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = build_bocha_service_from_env()
    assert _supports_protocol(svc)
    assert type(svc).__name__ in ("_MockBochaAdapter", "MockBochaService")


def test_factory_mock_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOCHA_MODE", "mock")
    monkeypatch.setenv("LLM_MODE", "mock")
    svc = build_bocha_service_from_env()
    assert _supports_protocol(svc)


def test_factory_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOCHA_MODE", "real")
    monkeypatch.setenv("BOCHA_API_KEY", "fake-key-for-test")
    svc = build_bocha_service_from_env()
    assert _supports_protocol(svc)
    assert type(svc).__name__ == "ReliableBochaService"  # was "BochaClient"


def test_factory_unknown_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOCHA_MODE", "weird")
    with pytest.raises(ValueError, match="BOCHA_MODE"):
        build_bocha_service_from_env()


def test_factory_real_missing_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOCHA_MODE", "real")
    monkeypatch.delenv("BOCHA_API_KEY", raising=False)
    with pytest.raises(KeyError, match="BOCHA_API_KEY"):
        build_bocha_service_from_env()
