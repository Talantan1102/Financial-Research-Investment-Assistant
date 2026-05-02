"""CircuitBreaker — 3-state breaker (closed / open / half_open).

State transitions:
  closed → open      : N consecutive failures
  open   → half_open : cooldown_s elapsed since opening
  half_open → closed : 1 successful call
  half_open → open   : 1 failed call

Concurrent calls in half_open are serialized via asyncio.Lock — only one
trial at a time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

T = TypeVar("T")

State = Literal["closed", "open", "half_open"]


class CircuitOpenError(Exception):
    """Raised when a call is short-circuited due to open breaker."""


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, cooldown_s: float = 30.0) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if cooldown_s <= 0:
            raise ValueError("cooldown_s must be positive")
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._state: State = "closed"
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_lock = asyncio.Lock()

    @property
    def state(self) -> State:
        if (
            self._state == "open"
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self._cooldown_s
        ):
            self._state = "half_open"
        return self._state

    async def call(self, coro_factory: Callable[[], Awaitable[T]]) -> T:
        current = self.state

        if current == "open":
            raise CircuitOpenError("circuit breaker is open")

        if current == "half_open":
            async with self._half_open_lock:
                if self._state == "open":
                    raise CircuitOpenError("circuit breaker is open")
                try:
                    result = await coro_factory()
                except Exception:
                    self._state = "open"
                    self._opened_at = time.monotonic()
                    self._consecutive_failures += 1
                    raise
                else:
                    self._state = "closed"
                    self._consecutive_failures = 0
                    self._opened_at = None
                    return result

        # closed
        try:
            result = await coro_factory()
        except Exception:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._state = "open"
                self._opened_at = time.monotonic()
            raise
        else:
            self._consecutive_failures = 0
            return result
