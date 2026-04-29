"""L3 — eval tests: golden set + LLM-as-judge, LLM via real API.

WARNING: These tests cost real money. They are excluded from default `poe test`.
Run via: `poe eval` (Plan C) or `pytest backend/tests/eval -m live_only`.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_live(monkeypatch):
    """Force LLM_MODE=live for every test in the eval layer."""
    monkeypatch.setenv("LLM_MODE", "live")
    yield
