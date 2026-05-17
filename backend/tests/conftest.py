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

# v1.0 monitoring-engine L2 e2e fixtures (Redis container + Celery worker
# subprocess). pytest only auto-loads files literally named `conftest.py`,
# so we explicitly re-export from `tests.conftest_celery` to register the
# fixtures into this conftest's scope.
from tests.conftest_celery import celery_worker_subprocess, redis_url  # noqa: F401, E402

LLMMode = Literal["none", "mock", "cassette", "live"]


def pytest_configure(config: pytest.Config) -> None:
    """Set default LLM_MODE if not already set by environment or layer conftest.

    Roadmap #2.5: POSTGRES_DB is force-set to the test db. sqlite-override tests
    are unaffected (don't read POSTGRES_DB at all); real-PG tests
    (test_pg_serve_path_e2e.py) need this set BEFORE any module imports
    `app.core.database` — pytest_configure runs before any test or test
    conftest module loads, so this is the only safe place.
    """
    os.environ.setdefault("LLM_MODE", "none")
    os.environ["POSTGRES_DB"] = "industry_assistant_test"


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


# ---------------------------------------------------------------------------
# Roadmap #2.5 PG container fixture — same shape as milvus_test_container,
# different compose file (repo-root docker-compose.yml) and readiness probe.
# Used only by tests/e2e/test_pg_serve_path_e2e.py for serve-path coverage.
# See: docs/superpowers/specs/2026-05-07-v0.9.x-pg-and-ci-setup.md § Task 2
# ---------------------------------------------------------------------------


def _wait_for_pg_ready(
    host: str, port: int, db: str, user: str, password: str, timeout: int = 60
) -> None:
    """Poll PG via psycopg2 until accepting connections + db is reachable."""
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        if _is_port_listening(host, port):
            try:
                import psycopg2

                conn = psycopg2.connect(
                    host=host, port=port, dbname=db, user=user, password=password
                )
                conn.close()
                return
            except Exception as e:  # psycopg2.OperationalError etc.
                last_err = e
        time.sleep(2)
    raise TimeoutError(f"PG ({db}) not ready after {timeout}s: {last_err}")


def _ensure_test_db_exists(host: str, port: int, user: str, password: str, test_db: str) -> None:
    """Create test_db if it doesn't exist. Idempotent.

    Handles the case where a developer's PG volume pre-dates 00-create-test-db.sql
    (postgres entrypoint init scripts only run on FIRST volume init,
    not on existing volumes).
    """
    import psycopg2

    # Connect to default postgres db (always exists), check + create.
    conn = psycopg2.connect(host=host, port=port, dbname="postgres", user=user, password=password)
    conn.autocommit = True  # CREATE DATABASE cannot run inside a transaction
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
        if cur.fetchone() is None:
            # quote_ident not available without extension; safe inline because
            # test_db is a hardcoded constant, not user input
            cur.execute(f'CREATE DATABASE "{test_db}"')
        cur.close()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def pg_test_container() -> Iterator[dict[str, object]]:
    """Session-scoped PG container, mirrors milvus_test_container.

    若已外部启动(127.0.0.1:5432 listening + industry_assistant_test 可连),复用,
    session 末**不**清理(避免影响外部 db / 开发者 dev 环境)。
    若没启动,fixture 自动 docker compose up -d postgres,session 末 down -v 清理。
    """
    backend_dir = Path(__file__).resolve().parents[1]  # → backend/
    repo_root = backend_dir.parent
    compose_file = repo_root / "docker-compose.yml"
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres123")
    test_db = "industry_assistant_test"

    started_by_us = False
    if not _is_port_listening(host, port):
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d", "postgres"],
            cwd=str(repo_root),
            check=True,
        )
        started_by_us = True

    try:
        # First wait for the default postgres db (always present once container is up)
        _wait_for_pg_ready(host, port, "postgres", user, password, timeout=60)
        # Then ensure test db exists (covers existing-volume migration case)
        _ensure_test_db_exists(host, port, user, password, test_db)
        # Final probe: test db must be reachable
        _wait_for_pg_ready(host, port, test_db, user, password, timeout=10)
        yield {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "db": test_db,
            "url": f"postgresql://{user}:{password}@{host}:{port}/{test_db}",
        }
    finally:
        if started_by_us:
            subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "down", "-v"],
                cwd=str(repo_root),
                check=False,
            )


# ---------------------------------------------------------------------------
# PG fixture — L0/L1/L2.5 共用(取代 sqlite-override)
# spec: docs/superpowers/specs/2026-05-17-pg-only-migration-design.md § 4 PR-A
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_test_engine(pg_test_container: dict[str, object]):
    """session-scoped SQLAlchemy engine bound to industry_assistant_test;
    create_all 跑一次(覆盖所有注册的 metadata)。

    Replaces 全部 in-memory sqlite engines used by L0/L1 tests.
    """
    import app.models  # noqa: F401 — barrel registers all metadata
    import app.services.trace_models  # noqa: F401 — trace/eval metadata
    from app.core.database import Base
    from sqlalchemy import create_engine

    url = str(pg_test_container["url"])
    engine = create_engine(url, future=True, pool_pre_ping=True)

    # idempotent — 跨 worktree session 复用 db 时不破坏
    Base.metadata.create_all(bind=engine)

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(pg_test_engine):
    """function-scoped Session with savepoint rollback.

    每个 test 起一个 outer transaction,test 完 rollback,
    所有 INSERT/UPDATE/DELETE 跨 test 不可见。
    """
    from sqlalchemy.orm import sessionmaker

    connection = pg_test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
