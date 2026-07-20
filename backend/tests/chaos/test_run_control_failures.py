from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from tests.chaos.run_control_harness import (
    CHAOS_SCENARIOS,
    ComposeScopeError,
    RunControlChaosHarness,
    ScenarioEvidence,
)


def _stub_runner(args: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    del kwargs
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def test_suite_declares_the_twelve_required_scenarios() -> None:
    # The plan says "twelve" but enumerates first- and second-worker crashes
    # separately; preserving both gives thirteen independently auditable cases.
    assert len(CHAOS_SCENARIOS) == 13
    assert {
        "browser_disconnect",
        "two_worker_parallel",
        "tenant_fairness",
        "dual_scheduler",
        "duplicate_notification",
        "first_worker_crash",
        "second_worker_crash",
        "cancel_and_crash",
        "pause_resume_slot_release",
        "revision_chain",
        "redis_restart",
        "scheduler_dispatcher_restart",
        "legacy_writer_zero",
    } == set(CHAOS_SCENARIOS)


def test_compose_service_resolution_is_project_scoped(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(args)
        if args[-2:] == ("-q", "run-worker-a"):
            return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")
        if args[-2:] == ("inspect", "abc123"):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='[{"Config":{"Labels":{"com.docker.compose.project":"rcp-test"}}}]',
                stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=runner)
    assert harness.resolve_container("run-worker-a") == "abc123"
    assert any("-p" in call and "rcp-test" in call for call in calls)


def test_refuses_container_outside_project(tmp_path: Path) -> None:
    def runner(args: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        if args[-2:] == ("-q", "run-worker-a"):
            return subprocess.CompletedProcess(args, 0, stdout="other\n", stderr="")
        return subprocess.CompletedProcess(
            args,
            0,
            stdout='[{"Config":{"Labels":{"com.docker.compose.project":"other"}}}]',
            stderr="",
        )

    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=runner)
    with pytest.raises(ComposeScopeError, match="outside Compose project"):
        harness.resolve_container("run-worker-a")


def test_cleanup_rejects_leftover_project_containers(tmp_path: Path) -> None:
    def runner(args: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        if "down" in args:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="leftover\n", stderr="")

    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=runner)
    with pytest.raises(ComposeScopeError, match="left containers"):
        harness.cleanup()


def test_health_wait_has_a_bounded_timeout(tmp_path: Path) -> None:
    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=_stub_runner)
    with pytest.raises(TimeoutError, match="health timeout"):
        harness.wait_healthy("run-worker-a", timeout=0.01, poll_interval=0)


def test_evidence_requires_database_facts_not_only_process_state() -> None:
    evidence = ScenarioEvidence(
        name="browser_disconnect",
        elapsed_seconds=0.25,
        runs=1,
        attempts=1,
        events=4,
        outbox=1,
        terminal_runs=1,
    )
    assert evidence.has_database_facts
    assert evidence.to_json()["events"] == 4


def test_scenario_runner_requires_exact_map_and_preserves_action_error(tmp_path: Path) -> None:
    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=_stub_runner)

    def fake_query(_run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        return {
            "runs": 3,
            "attempts": 2,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 3,
            "pauses": 1,
            "revisions": 2,
            "legacy_rows": 0,
        }

    harness.query_evidence = fake_query  # type: ignore[method-assign, assignment]
    actions: dict[str, Callable[[], Sequence[str]]] = {
        name: (lambda: ["run-id"]) for name in CHAOS_SCENARIOS
    }
    actions["redis_restart"] = lambda: (_ for _ in ()).throw(RuntimeError("redis down"))
    with pytest.raises(RuntimeError, match="redis down"):
        harness.run_scenarios(actions, evidence_path=tmp_path / "evidence.json")
    rows = (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert '"name": "redis_restart"' in rows
    assert "redis down" in rows


def test_operator_script_wires_new_harness_and_evidence(tmp_path: Path) -> None:
    del tmp_path
    script = Path(__file__).resolve().parents[2] / "scripts" / "run_control_chaos.ps1"
    source = script.read_text(encoding="utf-8")
    assert "tests.chaos.run_control_harness" in source
    assert "RUN_CONTROL_CHAOS_EVIDENCE" in source
    assert "--evidence" in source
    assert "--remove-orphans" in source


def test_operator_script_bounds_children_cleanup_and_records_cleanup_failures() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "run_control_chaos.ps1"
    source = script.read_text(encoding="utf-8")
    assert "WaitForExit" in source
    assert "taskkill.exe /PID $process.Id /T /F" in source
    assert source.count("-Timeout (Get-RemainingSeconds)") >= 7
    assert 'Append-FailureEvidence -ErrorRecord $_ -Stage "cleanup"' in source
    assert "$script:PrimaryError" in source


def test_harness_requires_strict_health_and_real_restart_actions() -> None:
    source = (
        Path(__file__)
        .resolve()
        .parent.joinpath("run_control_harness.py")
        .read_text(encoding="utf-8")
    )
    assert 'health == "healthy"' in source
    assert 'legacy._compose("restart", "run-scheduler-a"' in source
    assert "harness.wait_healthy(service" in source
    assert "_parallel_and_duplicate()" in source


def test_cleanup_is_scoped_and_removes_project_volumes_and_networks(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    RunControlChaosHarness(tmp_path, project="rcp-test", runner=runner).cleanup()
    down = next(call for call in calls if "down" in call)
    assert "--volumes" in down
    assert "--remove-orphans" in down
    assert any(
        "network" in call and "label=com.docker.compose.project=rcp-test" in call for call in calls
    )
    assert any(
        "volume" in call and "label=com.docker.compose.project=rcp-test" in call for call in calls
    )


def test_evidence_file_remains_one_valid_json_array_after_action_failure(tmp_path: Path) -> None:
    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=_stub_runner)

    def fake_query(_run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        return {
            "runs": 3,
            "attempts": 2,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 3,
            "pauses": 1,
            "revisions": 2,
            "legacy_rows": 0,
        }

    harness.query_evidence = fake_query  # type: ignore[method-assign, assignment]
    actions: dict[str, Callable[[], Sequence[str]]] = {
        name: (lambda: ["run-id"]) for name in CHAOS_SCENARIOS
    }
    actions["redis_restart"] = lambda: (_ for _ in ()).throw(RuntimeError("redis down"))
    path = tmp_path / "evidence.json"
    with pytest.raises(RuntimeError):
        harness.run_scenarios(actions, evidence_path=path)
    import json

    rows = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert next(row for row in rows if row["name"] == "redis_restart")["error"]


def test_legacy_writer_evidence_rejects_any_legacy_rows(tmp_path: Path) -> None:
    harness = RunControlChaosHarness(tmp_path, project="rcp-test", runner=_stub_runner)

    def fake_query(_run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        return {
            "runs": 1,
            "attempts": 1,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 1,
            "pauses": 0,
            "revisions": 0,
            "legacy_rows": 1,
        }

    harness.query_evidence = fake_query  # type: ignore[method-assign, assignment]
    with pytest.raises(AssertionError, match="legacy chat_tasks"):
        harness.record("legacy_writer_zero", 0.0, ["run-id"])


def test_legacy_writer_evidence_zero_is_explicit_and_json_serializable() -> None:
    evidence = ScenarioEvidence(
        name="legacy_writer_zero",
        elapsed_seconds=0.1,
        runs=1,
        attempts=1,
        events=1,
        outbox=1,
        terminal_runs=1,
        legacy_rows=0,
    )
    payload = evidence.to_json()
    assert payload["legacy_rows"] == 0
    assert json.loads(json.dumps(payload))["legacy_rows"] == 0
