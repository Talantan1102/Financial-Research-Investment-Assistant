"""Global test fixtures and configuration.

Each layer (unit/integration/e2e/eval) has its own conftest.py that may
override LLM_MODE. The default here is 'none' to fail loudly if any test
forgets to set its mode and accidentally tries to call a real LLM.
"""

import os
from pathlib import Path
from typing import Literal

import pytest
from app.services.llm_mock_client import MockLLMClient

LLMMode = Literal["none", "mock", "cassette", "live"]


def pytest_configure(config: pytest.Config) -> None:
    """Set default LLM_MODE if not already set by environment or layer conftest."""
    os.environ.setdefault("LLM_MODE", "none")


@pytest.fixture
def llm_mode() -> LLMMode:
    """Returns the current LLM_MODE for the running test."""
    mode = os.environ.get("LLM_MODE", "none")
    assert mode in ("none", "mock", "cassette", "live"), f"Invalid LLM_MODE: {mode}"
    return mode  # type: ignore[return-value]


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """L1 fixture — provides a deterministic MockLLMClient for injection
    into LLMService. L0 tests must not use this (LLM_MODE=none guard).
    """
    return MockLLMClient.from_fixture_dir(FIXTURES_DIR / "llm_mocks")


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    """L2 fixture — pytest-recording config. Sanitizes auth headers, matches
    on method/scheme/host/path/body so prompt changes invalidate cassettes.
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path", "body"],
    }
