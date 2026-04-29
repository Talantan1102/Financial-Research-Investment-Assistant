"""L2 — e2e tests: HTTP → graph → Responder, LLM via cassette (pytest-recording)."""

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_cassette(monkeypatch):
    """Force LLM_MODE=cassette for every test in the e2e layer."""
    monkeypatch.setenv("LLM_MODE", "cassette")
    yield


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch):
    """L2 cassette tests must not honor the dev shell's proxy vars.

    Background: many local dev shells set all_proxy=socks5://... for general
    web traffic. httpx imports the `socksio` extra lazily and raises ImportError
    if a SOCKS proxy is active. pytest-recording would also try to route the
    intercepted call through that proxy, defeating the cassette. Strip them
    inside the test process so behavior is identical on dev laptops and CI.
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
