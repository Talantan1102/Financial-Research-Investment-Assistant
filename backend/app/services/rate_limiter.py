"""RateLimiter — sliding-window async rate limiter.

Tracks last N call timestamps in a deque; on acquire(), if N >= max_calls,
sleeps until the oldest timestamp falls outside window_s.

Thread/task-safe via asyncio.Lock — concurrent acquire() calls serialize.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimiter:
    def __init__(self, *, max_calls: int, window_s: float = 60.0) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._max_calls = max_calls
        self._window_s = window_s
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block (await) until a call is allowed, then record current timestamp."""
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > self._window_s:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    return
                wait_s = self._window_s - (now - self._timestamps[0])
                # release lock during sleep so other awaiters can re-check
                self._lock.release()
                try:
                    await asyncio.sleep(wait_s)
                finally:
                    await self._lock.acquire()
