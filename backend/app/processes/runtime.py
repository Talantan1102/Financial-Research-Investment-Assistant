"""Shared liveness and bounded retry primitives for run-control processes."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from pathlib import Path

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

TRANSIENT_ERRORS = (
    RedisConnectionError,
    RedisTimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
    OperationalError,
    InterfaceError,
)


def is_transient_error(exc: BaseException) -> bool:
    """Return true only for connectivity failures; programming errors must escape."""

    if isinstance(exc, TRANSIENT_ERRORS):
        return True
    return isinstance(exc, DBAPIError) and bool(exc.connection_invalidated)


class BoundedBackoff:
    def __init__(self, *, initial: float = 0.1, maximum: float = 5.0) -> None:
        self._initial = initial
        self._maximum = maximum
        self._current = initial

    def reset(self) -> None:
        self._current = self._initial

    async def wait(self, shutdown: asyncio.Event) -> None:
        delay = self._current
        self._current = min(self._maximum, self._current * 2)
        with suppress(TimeoutError):
            await asyncio.wait_for(shutdown.wait(), timeout=delay)


class ProcessHealth:
    """Timestamped health state consumed by the Compose healthcheck."""

    def __init__(self, path: str | Path | None = None) -> None:
        selected = (
            path
            if path is not None
            else os.getenv("RUN_HEALTH_FILE", "/tmp/run-control-health.json")
        )
        self.path = Path(selected)
        self._dependencies: dict[str, float] = {}
        self._dependency_max_age = float(os.getenv("RUN_HEALTH_DEPENDENCY_MAX_AGE_SECONDS", "2"))

    def healthy(self) -> None:
        self.path.write_text(
            json.dumps({"healthy": True, "monotonic": time.monotonic()}), encoding="utf-8"
        )

    def unhealthy(self) -> None:
        self.path.unlink(missing_ok=True)

    def dependency_succeeded(self, name: str) -> None:
        now = time.monotonic()
        self._dependencies[name] = now
        required = {"postgres", "redis"}
        if required <= self._dependencies.keys() and all(
            now - self._dependencies[item] <= self._dependency_max_age for item in required
        ):
            self.healthy()
        else:
            self.unhealthy()

    def dependency_failed(self, name: str) -> None:
        self._dependencies.pop(name, None)
        self.unhealthy()


def assert_fresh_health(path: str | Path, max_age_seconds: float) -> None:
    health_path = Path(path)
    payload = json.loads(health_path.read_text(encoding="utf-8"))
    if payload.get("healthy") is not True:
        raise SystemExit(1)
    if time.time() - health_path.stat().st_mtime > max_age_seconds:
        raise SystemExit(1)


def healthcheck_main() -> None:
    assert_fresh_health(
        os.getenv("RUN_HEALTH_FILE", "/tmp/run-control-health.json"),
        float(os.getenv("RUN_HEALTH_MAX_AGE_SECONDS", "3")),
    )


if __name__ == "__main__":
    healthcheck_main()
