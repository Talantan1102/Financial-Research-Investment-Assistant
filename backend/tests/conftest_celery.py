"""Celery + Redis fixtures for L2 e2e tests.

Pattern 对齐 docs/claude-context/pg-test-container-pattern.md:
session-scoped + 外部已起则复用 / 自起则负责拆.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Generator

import pytest

try:
    from testcontainers.redis import RedisContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False


def _stop_worker(proc: subprocess.Popen[bytes]) -> None:
    """Stop the worker and its uv/celery child processes on every platform."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


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
    env = os.environ.copy()
    env["CELERY_BROKER_URL"] = redis_url
    env["CELERY_RESULT_BACKEND"] = redis_url

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "celery",
            "-A",
            "app.tasks.celery_app",
            "worker",
            "-Q",
            "default,llm",
            "--concurrency",
            "1",
            "--pool=solo",
            "--loglevel",
            "INFO",
        ],
        cwd="backend",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr → stdout; celery logs to stderr by default
        bufsize=1,
    )

    # Wait for "ready" without select(): Windows select only accepts sockets, not
    # subprocess pipes. A daemon reader keeps the timeout enforceable everywhere.
    import queue
    import threading

    lines: queue.Queue[bytes] = queue.Queue()

    def _read_worker_output() -> None:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, b""):
            lines.put(line)

    threading.Thread(target=_read_worker_output, daemon=True).start()

    start = time.time()
    ready = False
    while time.time() - start < 60:
        try:
            raw_line = lines.get(timeout=0.5)
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        line = raw_line.decode("utf-8", errors="ignore")
        if "celery@" in line and "ready" in line:
            ready = True
            break

    if not ready:
        _stop_worker(proc)
        pytest.skip("celery worker did not become ready in 60s")

    yield

    _stop_worker(proc)
