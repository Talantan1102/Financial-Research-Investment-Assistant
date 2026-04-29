"""L2 — e2e tests: HTTP → graph → Responder, LLM via cassette (pytest-recording)."""

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_cassette(monkeypatch):
    """Force LLM_MODE=cassette for every test in the e2e layer."""
    monkeypatch.setenv("LLM_MODE", "cassette")
    yield
