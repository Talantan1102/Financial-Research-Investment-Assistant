"""Conftest for dd_report Phase 1 tests — 沿用 b1_differential pattern.

env 加载 + proxy unset(避免 vcr / openai client 抓 proxy 干扰).
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(Path(__file__).parents[3] / ".env")
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip proxy env vars — 沿用 b1_differential conftest."""
    for var in ("all_proxy", "ALL_PROXY", "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(var, raising=False)
