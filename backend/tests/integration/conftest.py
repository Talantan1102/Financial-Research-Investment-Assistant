"""L1 — integration tests: agent + cross-cutting, LLM via deterministic mock.

Note: ``milvus_test_container`` fixture was promoted to ``tests/conftest.py``
(global scope) in v0.8.1 Task 5 so both tests/integration/ and tests/e2e/
can use it — pytest does not inherit fixtures across sibling conftest dirs.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_mock(monkeypatch):
    """Force LLM_MODE=mock for every test in the integration layer."""
    monkeypatch.setenv("LLM_MODE", "mock")
    yield
