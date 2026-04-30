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


@pytest.fixture
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """L2 fixture — tells pytest-recording where to store/find cassettes.

    Cassettes live at backend/tests/fixtures/cassettes/<module-stem>/
    so the Task-7 sanitize pre-commit hook (regex ^backend/tests/fixtures/cassettes/)
    actually covers every cassette recorded in this project.
    """
    module_stem = request.module.__name__.rsplit(".", 1)[-1]
    cassette_dir = FIXTURES_DIR / "cassettes" / module_stem
    cassette_dir.mkdir(parents=True, exist_ok=True)
    return str(cassette_dir)


def _strip_dashscope_response_headers(response: dict) -> dict:
    """Remove DashScope-specific response headers before recording.

    Headers like ``x-dashscope-call-gateway`` contain the substring
    ``dashscope-``, which the check_cassette_sanitize.py script flags as a
    potential credential leak (the pattern is intentionally broad to catch
    any ``sk-dashscope-…`` token). Strip them at recording time so cassettes
    stay clean without loosening the sanitize rules.
    """
    headers = response.get("headers", {})
    response["headers"] = {k: v for k, v in headers.items() if "dashscope" not in k.lower()}
    return response


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
        "before_record_response": _strip_dashscope_response_headers,
    }


@pytest.fixture
def tmp_eval_db(tmp_path: Path) -> Path:
    """L0/L1 fixture — fresh SQLite file per test, auto-cleaned by tmp_path.

    SQLite path modeling: every test that touches TraceService / EvalRecorder
    must accept this fixture and pass it as db_path. Sharing a global db is
    forbidden — Plan B's feedback_test_env_modeling lesson.
    """
    return tmp_path / "eval.sqlite"
