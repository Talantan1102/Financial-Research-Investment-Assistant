"""L1 — integration tests: agent + cross-cutting, LLM via deterministic mock."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _force_llm_mode_mock(monkeypatch):
    """Force LLM_MODE=mock for every test in the integration layer."""
    monkeypatch.setenv("LLM_MODE", "mock")
    yield


# ---------------------------------------------------------------------------
# v0.7 Milvus container fixture
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
    backend_dir = Path(__file__).resolve().parents[2]  # → backend/
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
