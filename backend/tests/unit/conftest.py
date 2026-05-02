"""L0 — unit tests: pure functions / Pydantic / no LLM calls."""

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_none(monkeypatch):
    """Force LLM_MODE=none for every test in the unit layer."""
    monkeypatch.setenv("LLM_MODE", "none")
    yield


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch):
    """Unit tests must not route through the dev-shell SOCKS proxy.

    Many local dev shells set all_proxy=socks5://... for web traffic. httpx
    picks up these env vars and tries to create a SOCKS transport (requires
    the socksio extra). Strip them so unit tests that construct httpx / OpenAI
    clients don't fail even when socksio isn't installed.
    """
    for var in (
        "all_proxy",
        "ALL_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "http_proxy",
        "HTTP_PROXY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield
