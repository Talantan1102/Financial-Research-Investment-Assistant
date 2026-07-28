from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from app.models.user import User
from eval.chatloop.business_runner import (
    BusinessExecutionContext,
    BusinessObservation,
    BusinessRunner,
)
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.environment import CaseEnvironmentManager
from sqlalchemy import func, select


def _case(case_id: str):
    return load_catalog().by_id(case_id)


async def _cleanup_external_memory(_edge_ids: list[str], _node_ids: list[str]) -> None:
    return None


@dataclass
class RecordingExecutor:
    contexts: list[BusinessExecutionContext] = field(default_factory=list)

    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
        self.contexts.append(context)
        return BusinessObservation(
            transcript=tuple(
                {"role": "user", "content": message} for message in context.case.user_messages
            ),
            tool_ledger=(),
            run_state={"status": "completed"},
            evidence={"timeline": context.timeline},
        )


class FailingExecutor:
    async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
        del context
        raise TimeoutError("controlled executor timeout")


def _runner(disposable_eval_runtime, executor: Any) -> BusinessRunner:
    manager = CaseEnvironmentManager(
        disposable_eval_runtime,
        external_memory_cleanup=_cleanup_external_memory,
    )
    return BusinessRunner(
        manager,
        direct_executor=executor,
        durable_executor=executor,
    )


@pytest.mark.asyncio
async def test_runner_passes_trial_scoped_actor_and_cleans_identity(
    disposable_eval_runtime,
    disposable_eval_async_session_factory,
) -> None:
    executor = RecordingExecutor()

    result = await _runner(disposable_eval_runtime, executor).run_trial(
        _case("B4-01"),
        trial_index=3,
        random_seed=314159,
    )

    assert result.trial_status == "valid"
    assert result.database_before_after["before"]["funds"] == {
        "available_cash": "620000.00",
        "frozen_cash": "80000.00",
    }
    assert len(executor.contexts) == 1
    context = executor.contexts[0]
    assert context.random_seed == 314159
    assert context.execution_id
    assert context.actor == context.environment.actor("requester")
    assert context.actor.user_id is not None
    assert context.actor.token
    async with disposable_eval_async_session_factory() as session:
        assert await session.get(User, context.actor.user_id) is None


@pytest.mark.asyncio
async def test_random_seed_deterministically_controls_harness_execution_identity(
    disposable_eval_runtime,
) -> None:
    first_executor = RecordingExecutor()
    second_executor = RecordingExecutor()
    third_executor = RecordingExecutor()

    await _runner(disposable_eval_runtime, first_executor).run_trial(
        _case("B4-01"), trial_index=0, random_seed=17
    )
    await _runner(disposable_eval_runtime, second_executor).run_trial(
        _case("B4-01"), trial_index=0, random_seed=17
    )
    await _runner(disposable_eval_runtime, third_executor).run_trial(
        _case("B4-01"), trial_index=0, random_seed=18
    )

    assert first_executor.contexts[0].execution_id == second_executor.contexts[0].execution_id
    assert first_executor.contexts[0].execution_id != third_executor.contexts[0].execution_id


@pytest.mark.asyncio
async def test_cross_user_case_executes_as_requester_without_owner_visibility(
    disposable_eval_runtime,
) -> None:
    class CrossUserExecutor(RecordingExecutor):
        async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
            assert context.actor.role == "other_user"
            assert (await context.environment.snapshot(actor_name="requester"))["orders"][
                "count"
            ] == 0
            assert (await context.environment.snapshot(actor_name="owner"))["orders"]["count"] == 1
            assert context.fault_plans[0].mode == "conflict"
            return await super().execute(context)

    direct_case = _case("B7-16").model_copy(
        update={
            "initial_state": _case("B7-16").initial_state.model_copy(
                update={"execution_mode": "direct"}
            )
        }
    )
    result = await _runner(disposable_eval_runtime, CrossUserExecutor()).run_trial(
        direct_case,
        trial_index=0,
    )

    assert result.trial_status == "valid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case_id", "message"),
    [
        ("B4-06", "memory isolation"),
        ("B7-16", "durable stack isolation"),
    ],
)
async def test_unisolated_external_capability_fails_before_identity_seed(
    disposable_eval_runtime,
    disposable_eval_async_session_factory,
    case_id: str,
    message: str,
) -> None:
    async with disposable_eval_async_session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(User))

    with pytest.raises(RuntimeError, match=message):
        await _runner(disposable_eval_runtime, RecordingExecutor()).run_trial(
            _case(case_id),
            trial_index=0,
        )

    async with disposable_eval_async_session_factory() as session:
        after = await session.scalar(select(func.count()).select_from(User))
    assert after == before


@pytest.mark.asyncio
async def test_executor_failure_is_harness_failed_and_still_cleans(
    disposable_eval_runtime,
    disposable_eval_async_session_factory,
) -> None:
    result = await _runner(disposable_eval_runtime, FailingExecutor()).run_trial(
        _case("B4-01"),
        trial_index=0,
    )

    assert result.trial_status == "harness_failed"
    assert result.observation is None
    assert result.failure_reason is not None
    assert "controlled executor timeout" in result.failure_reason
    async with disposable_eval_async_session_factory() as session:
        for user_id in result.environment_manifest["user_ids"]:
            assert await session.get(User, user_id) is None


@pytest.mark.asyncio
async def test_task_cancellation_still_cleans_trial_identity(
    disposable_eval_runtime,
    disposable_eval_async_session_factory,
) -> None:
    started = asyncio.Event()
    actor_ids: list[Any] = []

    class HangingExecutor:
        async def execute(self, context: BusinessExecutionContext) -> BusinessObservation:
            actor_ids.append(context.actor.user_id)
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    task = asyncio.create_task(
        _runner(disposable_eval_runtime, HangingExecutor()).run_trial(
            _case("B4-01"),
            trial_index=0,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async with disposable_eval_async_session_factory() as session:
        assert await session.get(User, actor_ids[0]) is None
