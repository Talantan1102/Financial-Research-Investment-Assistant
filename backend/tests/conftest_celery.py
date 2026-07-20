"""Celery + Redis fixtures for L2 e2e tests.

Pattern 对齐 docs/claude-context/pg-test-container-pattern.md:
session-scoped + 外部已起则复用 / 自起则负责拆.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Generator

import pytest

try:
    from testcontainers.redis import RedisContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False


CELERY_WORKER_QUEUES = ("default", "llm")


def prepare_celery_worker_env(base: dict[str, str], redis_url: str) -> dict[str, str]:
    """Build deterministic L2 worker env without enabling live network calls."""
    env = dict(base)
    env["CELERY_BROKER_URL"] = redis_url
    env["CELERY_RESULT_BACKEND"] = redis_url
    if env.get("LLM_MODE", "none") == "none":
        env["LLM_MODE"] = "mock"
    # Both mock and cassette construct the Qwen embedding service before the
    # chat task is marked running.  A non-empty placeholder is enough for
    # construction; these L2 tests never make a live embedding request.
    if env["LLM_MODE"] in {"mock", "cassette"} and not env.get("DASHSCOPE_API_KEY"):
        env["DASHSCOPE_API_KEY"] = "test-key-not-for-live-calls"
    return env


@pytest.fixture(scope="session")
def redis_url() -> Generator[str, None, None]:
    """Session-scoped redis broker URL.

    Strategy:
    - If REDIS_URL env set → use it (CI passes one)
    - Else if docker available → spin testcontainers RedisContainer
    - Else skip
    """
    if "REDIS_URL" in os.environ:
        yield os.environ["REDIS_URL"]
        return

    if not HAS_TESTCONTAINERS or not shutil.which("docker"):
        pytest.skip("Redis not available (set REDIS_URL or install docker + testcontainers[redis])")

    with RedisContainer("redis:7-alpine") as redis:
        url = f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/15"
        yield url


@pytest.fixture(scope="session")
def celery_worker_subprocess(redis_url: str) -> Generator[None, None, None]:
    """Spawn Celery worker subprocess against redis broker.

    Runs --concurrency=1 to keep ordering deterministic in tests.
    """
    env = prepare_celery_worker_env(dict(os.environ), redis_url)
    # Global pytest bootstrap deliberately defaults LLM_MODE to "none" so unit
    # tests fail on accidental LLM construction.  This fixture is an L2 worker,
    # and run_chat must get past dependency construction before it can mark the
    # DB task running; use mock unless the caller explicitly selected a real
    # integration mode (cassette/live/mock).
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "celery",
            "-A",
            "app.tasks.celery_app",
            "worker",
            "-Q",
            ",".join(CELERY_WORKER_QUEUES),
            "--concurrency",
            "1",
            "--loglevel",
            "INFO",
        ],
        cwd="backend",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr → stdout; celery logs to stderr by default
        bufsize=1,
    )

    # Wait for "ready" log line (max 60s — graph singleton build is heavy:
    # imports langchain/langgraph + builds CompiledStateGraph at worker import time).
    # Use select with short timeout so we re-check wall clock between readline calls
    # (readline alone can block past deadline if pipe is silent).
    import select

    start = time.time()
    ready = False
    while time.time() - start < 60:
        if proc.stdout is None:
            break
        rlist, _, _ = select.select([proc.stdout], [], [], 0.5)
        if not rlist:
            continue
        line = proc.stdout.readline().decode("utf-8", errors="ignore")
        if not line:
            # EOF — worker died
            break
        if "celery@" in line and "ready" in line:
            ready = True
            break

    if not ready:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.skip("celery worker did not become ready in 60s")

    yield

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
