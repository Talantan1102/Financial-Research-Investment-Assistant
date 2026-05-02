"""L0 — RateLimiter sliding window enforcement."""

import asyncio
import time

import pytest
from app.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_under_limit_no_wait() -> None:
    rl = RateLimiter(max_calls=5, window_s=1.0)
    started = time.monotonic()
    for _ in range(5):
        await rl.acquire()
    elapsed = time.monotonic() - started
    assert elapsed < 0.05  # 5 instant calls under limit


@pytest.mark.asyncio
async def test_over_limit_blocks() -> None:
    rl = RateLimiter(max_calls=2, window_s=0.3)
    await rl.acquire()
    await rl.acquire()
    started = time.monotonic()
    await rl.acquire()  # this one must wait until window slides
    elapsed = time.monotonic() - started
    assert elapsed >= 0.25  # roughly 0.3s wait (allow jitter)
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_window_slides() -> None:
    rl = RateLimiter(max_calls=2, window_s=0.2)
    await rl.acquire()
    await rl.acquire()
    await asyncio.sleep(0.25)  # window passes
    started = time.monotonic()
    await rl.acquire()
    elapsed = time.monotonic() - started
    assert elapsed < 0.05  # no wait — window slid past first 2


@pytest.mark.asyncio
async def test_concurrent_acquire_serialized() -> None:
    """Concurrent acquire calls don't interleave timestamps inconsistently."""
    rl = RateLimiter(max_calls=3, window_s=0.5)

    async def task() -> float:
        started = time.monotonic()
        await rl.acquire()
        return time.monotonic() - started

    elapsed = await asyncio.gather(*[task() for _ in range(5)])
    # First 3 should be near-zero; last 2 should be ≥ 0.4s
    elapsed_sorted = sorted(elapsed)
    n_short = sum(1 for t in elapsed_sorted if t < 0.05)
    n_long = sum(1 for t in elapsed_sorted if t >= 0.4)
    assert n_short == 3
    assert n_long == 2
