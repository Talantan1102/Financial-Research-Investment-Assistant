"""Lease-aware Phase 2 executor that uses only the public AttemptService API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.services.attempt_service import AttemptService, ClaimedAssignment


class SimulatedRunCrash(RuntimeError):  # noqa: N818 - explicit acceptance signal
    """Simulate abrupt executor loss without writing a terminal Attempt command."""


@dataclass(frozen=True)
class SimulatedExecution:
    delay_seconds: float = 0.0
    result: Mapping[str, Any] = field(default_factory=lambda: {"simulated": True})
    crash: bool = False

    def __post_init__(self) -> None:
        if self.delay_seconds < 0:
            raise ValueError("delay_seconds must be nonnegative")


class SimulatedRunExecutor:
    def __init__(
        self,
        attempts: AttemptService,
        *,
        instruction: SimulatedExecution | None = None,
        renew_interval: float = 10.0,
    ) -> None:
        if renew_interval <= 0:
            raise ValueError("renew_interval must be positive")
        self._attempts = attempts
        self._instruction = instruction or SimulatedExecution()
        self._renew_interval = renew_interval

    async def execute(
        self,
        assignment: ClaimedAssignment,
        instruction: SimulatedExecution | None = None,
    ) -> None:
        plan = instruction or self._instruction
        if plan.crash:
            raise SimulatedRunCrash("simulated worker crash")
        remaining = plan.delay_seconds
        while remaining > 0:
            interval = min(remaining, self._renew_interval)
            await asyncio.sleep(interval)
            remaining -= interval
            if remaining > 0:
                await self._attempts.renew(
                    assignment.attempt_id,
                    assignment.worker_id,
                    assignment.claim_token,
                )
        await self._attempts.complete_simulated(
            assignment.attempt_id,
            assignment.worker_id,
            assignment.claim_token,
            plan.result,
        )
