from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, cast

import pytest
from app.processes.run_scheduler import RunScheduler
from app.processes.runtime import ProcessHealth, assert_fresh_health


class FlakyScheduling:
    def __init__(self) -> None:
        self.calls = 0

    async def recover_expired_attempts(self, limit: int) -> tuple[object, ...]:
        self.calls += 1
        if self.calls == 1:
            raise OSError("postgres connection reset")
        return ()

    async def schedule_once(self) -> None:
        return None


async def test_scheduler_retries_transient_connectivity_failure(tmp_path: Path) -> None:
    service = FlakyScheduling()
    health = ProcessHealth(tmp_path / "scheduler.json")
    scheduler = RunScheduler(cast(Any, service), None, poll_interval=0.01, health=health)
    task = asyncio.create_task(scheduler.run_forever())
    for _ in range(100):
        if service.calls >= 2:
            break
        await asyncio.sleep(0.005)
    scheduler.request_shutdown()
    await task
    assert service.calls >= 2
    assert (tmp_path / "scheduler.json").exists()


class BrokenScheduling:
    async def recover_expired_attempts(self, limit: int) -> tuple[object, ...]:
        raise ValueError("programming bug")

    async def schedule_once(self) -> None:
        return None


async def test_scheduler_does_not_swallow_programming_errors(tmp_path: Path) -> None:
    scheduler = RunScheduler(
        cast(Any, BrokenScheduling()),
        None,
        poll_interval=0.01,
        health=ProcessHealth(tmp_path / "h.json"),
    )
    with pytest.raises(ValueError, match="programming bug"):
        await scheduler.run_forever()


def test_healthcheck_rejects_stale_marker(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    ProcessHealth(path).healthy()
    old = time.time() - 30
    os.utime(path, (old, old))
    with pytest.raises(SystemExit):
        assert_fresh_health(path, 1)
