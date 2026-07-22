"""Celery + Redis fixtures for L2 e2e tests.

Pattern 对齐 docs/claude-context/pg-test-container-pattern.md:
session-scoped + 外部已起则复用 / 自起则负责拆.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import pytest

try:
    from testcontainers.redis import RedisContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False


def _stop_posix_worker(proc: subprocess.Popen[bytes]) -> None:
    """Terminate the whole worker process group, escalating after a bounded wait."""
    try:
        process_group = os.getpgid(proc.pid)
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group, getattr(signal, "SIGKILL", 9))
        except ProcessLookupError:
            return
        proc.wait(timeout=10)


def _stop_worker(proc: subprocess.Popen[bytes]) -> None:
    """Stop the worker and its uv/celery child processes on every platform."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    _stop_posix_worker(proc)


def _start_worker(producer_config: Any, *args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
    """Restore in-process producer configuration when spawning fails."""
    try:
        return subprocess.Popen(*args, **kwargs)
    except BaseException:
        producer_config.__exit__(*sys.exc_info())
        raise


@contextmanager
def configured_celery_producer(redis_url: str) -> Generator[None, None, None]:
    """Point the in-process producer/result consumer at the worker's broker."""
    from app.tasks.celery_app import celery_app

    apps = [celery_app]
    paper_module = sys.modules.get("app.tasks.paper_trading")
    paper_task = getattr(paper_module, "match_order", None)
    if paper_task is not None and paper_task.app is not celery_app:
        apps.append(paper_task.app)
    originals = [(app, app.conf.broker_url, app.conf.result_backend) for app in apps]
    for app in apps:
        app.conf.broker_url = redis_url
        app.conf.result_backend = redis_url
        app._backend_cache = None
    try:
        yield
    finally:
        for app, old_broker, old_backend in originals:
            app.conf.broker_url = old_broker
            app.conf.result_backend = old_backend
            app._backend_cache = None


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
def paper_trading_worker_fixture_path() -> str | None:
    return os.environ.get("PAPER_TRADING_WORKER_FIXTURE")


@pytest.fixture(scope="session")
def celery_worker_llm_mode() -> str | None:
    """Optional LLM mode for the worker subprocess.

    Most worker tests do not construct an LLM service and should retain the
    suite-wide ``none`` guard. Tests that exercise an LLM-backed task override
    this fixture explicitly instead of relying on function-scoped environment
    mutation that happens after the session worker has started.
    """
    return os.environ.get("CELERY_WORKER_LLM_MODE")


@pytest.fixture(scope="session")
def celery_worker_subprocess(
    redis_url: str,
    paper_trading_worker_fixture_path: str | None,
    celery_worker_llm_mode: str | None,
) -> Generator[None, None, None]:
    """Spawn Celery worker subprocess against redis broker.

    Runs --concurrency=1 to keep ordering deterministic in tests.
    """
    env = os.environ.copy()
    for proxy_var in (
        "all_proxy",
        "ALL_PROXY",
        "https_proxy",
        "HTTPS_PROXY",
        "http_proxy",
        "HTTP_PROXY",
    ):
        env.pop(proxy_var, None)
    env["CELERY_BROKER_URL"] = redis_url
    env["CELERY_RESULT_BACKEND"] = redis_url
    if celery_worker_llm_mode is not None:
        env["LLM_MODE"] = celery_worker_llm_mode
    if paper_trading_worker_fixture_path is not None:
        env["PAPER_TRADING_WORKER_FIXTURE"] = paper_trading_worker_fixture_path

    worker_args = [
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
    ]
    if paper_trading_worker_fixture_path is not None:
        worker_args.extend(["--include", "tests.worker_paper_trading_fixture"])

    producer_config = configured_celery_producer(redis_url)
    producer_config.__enter__()
    proc = _start_worker(
        producer_config,
        worker_args,
        cwd="backend",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge stderr → stdout; celery logs to stderr by default
        bufsize=1,
        start_new_session=sys.platform != "win32",
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
        producer_config.__exit__(None, None, None)
        pytest.skip("celery worker did not become ready in 60s")

    try:
        yield
    finally:
        _stop_worker(proc)
        producer_config.__exit__(None, None, None)
