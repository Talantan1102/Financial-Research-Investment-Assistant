"""L2 — e2e tests: HTTP → graph → Responder, LLM via cassette (pytest-recording)."""

import json
import re
from typing import Any

import pytest

_TOKEN_BODY_PATTERN = re.compile(r'"token"\s*:\s*"[^"]{8,}"')
_REDACTED_TOKEN = '"token": "REDACTED"'


def _token_stripped_body_matcher(r1: Any, r2: Any) -> None:
    """VCR matcher: compare POST bodies after stripping the 'token' field.

    Used by test_tushare_real_cassette to match tushare POST requests by
    api_name+params, ignoring the token that was redacted during recording.
    Raises AssertionError if bodies differ after token removal.
    """

    def _strip_token(body: Any) -> Any:
        raw = body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            if isinstance(d, dict):
                d.pop("token", None)
                return d
            return d
        except (json.JSONDecodeError, TypeError):
            return _TOKEN_BODY_PATTERN.sub(_REDACTED_TOKEN, str(raw))

    b1 = _strip_token(r1.body)
    b2 = _strip_token(r2.body)
    if b1 != b2:
        raise AssertionError(
            f"Request bodies differ (token stripped):\n  recorded: {b2}\n  replayed: {b1}"
        )


def pytest_recording_configure(config: Any, vcr: Any) -> None:
    """Register custom VCR matchers for this e2e layer.

    Called by pytest-recording after it creates its VCR instance, so we
    can add project-specific matchers without monkey-patching globals.
    """
    vcr.register_matcher("token_stripped_body", _token_stripped_body_matcher)


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
