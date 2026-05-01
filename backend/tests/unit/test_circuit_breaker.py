"""L0 — CircuitBreaker 3-state transitions."""

import asyncio

import pytest
from app.services.circuit_breaker import CircuitBreaker, CircuitOpenError


@pytest.mark.asyncio
async def test_initial_state_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=0.1)
    assert cb.state == "closed"


@pytest.mark.asyncio
async def test_success_keeps_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=0.1)

    async def ok() -> int:
        return 42

    result = await cb.call(ok)
    assert result == 42
    assert cb.state == "closed"


@pytest.mark.asyncio
async def test_threshold_opens_breaker() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=0.1)

    async def fail() -> None:
        raise RuntimeError("boom")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(fail)
    assert cb.state == "open"


@pytest.mark.asyncio
async def test_open_breaker_short_circuits() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.5)

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(fail)
    assert cb.state == "open"

    called = False

    async def tracker() -> int:
        nonlocal called
        called = True
        return 1

    with pytest.raises(CircuitOpenError):
        await cb.call(tracker)
    assert not called  # short-circuited


@pytest.mark.asyncio
async def test_cooldown_transitions_to_half_open() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.1)

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(fail)
    assert cb.state == "open"

    await asyncio.sleep(0.15)

    async def ok() -> int:
        return 7

    result = await cb.call(ok)
    assert result == 7
    assert cb.state == "closed"


@pytest.mark.asyncio
async def test_half_open_failure_reopens() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.1)

    async def fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(fail)
    await asyncio.sleep(0.15)

    with pytest.raises(RuntimeError):
        await cb.call(fail)
    assert cb.state == "open"
