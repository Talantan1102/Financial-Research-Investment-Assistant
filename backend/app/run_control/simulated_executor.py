"""Lease-aware deterministic executor used by the run-control acceptance service."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.chatloop.run_executor import PauseResult, RunUsage
from app.services.attempt_service import AttemptService, ClaimedAssignment


class SimulatedRunCrash(RuntimeError):  # noqa: N818
    pass


@dataclass(frozen=True)
class SimulatedExecution:
    delay_seconds: float = 0.0
    result: Mapping[str, Any] = field(default_factory=lambda: {"simulated": True})
    crash: bool = False
    pause_type: str | None = None

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
        lease_duration: float | None = None,
    ) -> None:
        if renew_interval <= 0:
            raise ValueError("renew_interval must be positive")
        if lease_duration is not None and renew_interval >= lease_duration:
            raise ValueError("renew_interval must be shorter than lease_duration")
        self._attempts = attempts
        self._instruction = instruction or SimulatedExecution()
        self._renew_interval = renew_interval
        self._paused_runs: set[str] = set()

    async def execute(
        self, assignment: ClaimedAssignment, instruction: SimulatedExecution | None = None
    ) -> None:
        plan = instruction or self._instruction
        if plan.crash:
            raise SimulatedRunCrash("simulated worker crash")
        if (
            plan.pause_type in {"input", "approval"}
            and str(assignment.run_id) not in self._paused_runs
        ):
            self._paused_runs.add(str(assignment.run_id))
            await self._attempts.pause_chat(
                assignment,
                PauseResult(
                    run_id=assignment.run_id,
                    attempt_id=assignment.attempt_id,
                    session_id=assignment.run_id,
                    pause_type=cast(Literal["input", "approval"], plan.pause_type),
                    request={"question": "continue?"},
                    continuation={"simulated": True},
                    usage=RunUsage("simulated", "simulated", 0, 0, 0, 0, 0.0),
                    tools=(),
                    events=(),
                ),
            )
            return
        remaining = plan.delay_seconds
        while remaining > 0:
            interval = min(remaining, self._renew_interval)
            if remaining >= self._renew_interval:
                await self._attempts.renew(
                    assignment.attempt_id, assignment.worker_id, assignment.claim_token
                )
            await asyncio.sleep(interval)
            remaining -= interval
        await self._attempts.complete_simulated(
            assignment.attempt_id, assignment.worker_id, assignment.claim_token, plan.result
        )
