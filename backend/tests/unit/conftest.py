"""L0 — unit tests: pure functions / Pydantic / no LLM calls."""

import os

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_none(monkeypatch):
    """Force LLM_MODE=none for every test in the unit layer."""
    monkeypatch.setenv("LLM_MODE", "none")
    yield
