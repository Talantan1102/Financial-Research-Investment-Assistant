"""C5: assert_jwt_secret_configured() fail-fast guard for the serving app.

A deployment must never sign/verify JWTs with a publicly-known key (an attacker
could forge tokens for any user). The guard runs at lifespan startup; tests/eval
may use the dev default.
"""

from __future__ import annotations

import pytest
from app.core.security import assert_jwt_secret_configured


def test_jwt_guard_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        assert_jwt_secret_configured()


def test_jwt_guard_raises_on_known_insecure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in (
        "your-super-secret-key-change-in-production",
        "insecure-dev-default-change-me",
    ):
        monkeypatch.setenv("JWT_SECRET_KEY", bad)
        with pytest.raises(RuntimeError, match="insecure"):
            assert_jwt_secret_configured()


def test_jwt_guard_passes_with_real_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "a-real-random-secret-0123456789abcdef0123456789")
    assert_jwt_secret_configured()  # must not raise
