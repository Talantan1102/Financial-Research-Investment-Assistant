"""L1 — integration tests: agent + cross-cutting, LLM via deterministic mock."""

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_mock(monkeypatch):
    """Force LLM_MODE=mock for every test in the integration layer."""
    monkeypatch.setenv("LLM_MODE", "mock")
    yield
