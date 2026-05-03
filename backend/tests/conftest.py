"""Global test fixtures and configuration.

Each layer (unit/integration/e2e/eval) has its own conftest.py that may
override LLM_MODE. The default here is 'none' to fail loudly if any test
forgets to set its mode and accidentally tries to call a real LLM.
"""

import os
import socket
import subprocess
import time
from collections.abc import Iterator
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


# ---------------------------------------------------------------------------
# v0.7 Milvus container fixture (promoted to global scope in v0.8.1 Task 5
# so both tests/integration/ and tests/e2e/ can use it — pytest does not
# inherit fixtures across sibling conftest dirs).
# ---------------------------------------------------------------------------


def _is_port_listening(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((host, port))
        return True
    except (TimeoutError, OSError):
        return False
    finally:
        s.close()


def _wait_for_milvus_ready(host: str = "127.0.0.1", port: int = 19530, timeout: int = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_listening(host, port):
            try:
                from pymilvus import MilvusClient

                client = MilvusClient(uri=f"http://{host}:{port}")
                client.has_collection("nonexistent_probe")
                return
            except Exception:
                pass
        time.sleep(2)
    raise TimeoutError(f"Milvus not ready after {timeout}s")


@pytest.fixture(scope="session")
def milvus_test_container() -> Iterator[dict[str, object]]:
    """Session-scoped Milvus container via docker-compose.

    若已外部启动(MILVUS_HOST=127.0.0.1, MILVUS_PORT=19530 listening),复用,
    session 末**不**清理(避免影响外部使用者)。
    若没启动,fixture 自动 docker compose up -d,session 末 down -v 清理。
    """
    backend_dir = Path(__file__).resolve().parents[1]  # → backend/
    compose_file = backend_dir / "docker-compose.milvus.yml"
    host = os.environ.get("MILVUS_HOST", "127.0.0.1")
    port = int(os.environ.get("MILVUS_PORT", "19530"))

    started_by_us = False
    if not _is_port_listening(host, port):
        # 起容器
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            cwd=str(backend_dir),
            check=True,
        )
        started_by_us = True

    try:
        _wait_for_milvus_ready(host=host, port=port, timeout=120)
        yield {"host": host, "port": port}
    finally:
        if started_by_us:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "down", "-v"],
                cwd=str(backend_dir),
                check=False,
            )
