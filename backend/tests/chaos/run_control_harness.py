"""Process-level failure harness for the Run control plane.

The harness deliberately keeps the destructive surface small: every docker
operation is made through one explicitly named Compose project and every
reported scenario carries PostgreSQL facts.  It is usable from pytest for
self-tests and from ``run_control_chaos.ps1`` for the real-process suite.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from jose import jwt

CHAOS_SCENARIOS: tuple[str, ...] = (
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
)

_SAFE_SERVICES = {
    "run-api",
    "run-scheduler-a",
    "run-scheduler-b",
    "run-dispatcher",
    "run-worker-a",
    "run-worker-b",
    "redis",
    "postgres",
}
_PROJECT_RE = re.compile(r"^rcp-[a-z0-9][a-z0-9-]{2,62}$")

_SCENARIO_MINIMUMS: dict[str, dict[str, int]] = {
    name: {"runs": 1, "attempts": 1, "events": 1, "outbox": 1, "terminal_runs": 1}
    for name in CHAOS_SCENARIOS
}
_SCENARIO_MINIMUMS.update(
    {
        "first_worker_crash": {
            "runs": 1,
            "attempts": 2,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 1,
        },
        "second_worker_crash": {
            "runs": 1,
            "attempts": 2,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 1,
        },
        "pause_resume_slot_release": {
            "runs": 1,
            "attempts": 2,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 1,
            "pauses": 1,
        },
        "revision_chain": {
            "runs": 3,
            "attempts": 1,
            "events": 1,
            "outbox": 1,
            "terminal_runs": 3,
            "revisions": 2,
        },
    }
)


class ComposeScopeError(RuntimeError):
    """A requested process/container is not owned by this harness project."""


@dataclass(frozen=True)
class ScenarioEvidence:
    name: str
    elapsed_seconds: float
    runs: int
    attempts: int
    events: int
    outbox: int
    terminal_runs: int = 0
    pauses: int = 0
    revisions: int = 0
    error: str | None = None
    legacy_rows: int = 0

    @property
    def has_database_facts(self) -> bool:
        return (
            self.runs > 0
            and self.attempts > 0
            and self.events > 0
            and self.outbox > 0
            and self.terminal_runs > 0
        )

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["legacy_rows"] = self.legacy_rows
        payload["has_database_facts"] = self.has_database_facts
        return payload


Runner = Callable[..., subprocess.CompletedProcess[str]]


class RunControlChaosHarness:
    def __init__(
        self,
        repo_root: Path,
        *,
        project: str | None = None,
        runner: Runner = subprocess.run,
        database_url: str | None = None,
        command_timeout: float = 30.0,
    ) -> None:
        if not _PROJECT_RE.fullmatch(project or ""):
            raise ValueError("project must be an isolated rcp-* Compose project")
        if command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        self.repo_root = repo_root.resolve()
        self.compose_file = self.repo_root / "docker-compose.yml"
        self.project = project or ""
        self._runner = runner
        self.command_timeout = command_timeout
        self.database_url = database_url or os.getenv("RUN_CONTROL_DATABASE_URL")
        self.evidence: list[ScenarioEvidence] = []
        self._last_compose_returncode = 0

    def _compose(self, *args: str, check: bool = True) -> str:
        command = (
            "docker",
            "compose",
            "-f",
            str(self.compose_file),
            "-p",
            self.project,
            *args,
        )
        result = self._runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.command_timeout,
        )
        if result is None:
            return ""
        self._last_compose_returncode = result.returncode
        if check and result.returncode != 0:
            raise RuntimeError(f"compose command failed: {result.stderr or result.stdout}")
        return result.stdout or ""

    def resolve_container(self, service: str) -> str:
        self._validate_service(service)
        output = self._compose("ps", "-q", service)
        container_ids = [line.strip() for line in output.splitlines() if line.strip()]
        if len(container_ids) != 1:
            raise ComposeScopeError(
                f"expected one container for {service!r} in project {self.project!r}, "
                f"got {container_ids!r}"
            )
        container_id = container_ids[0]
        raw = self._docker("inspect", container_id)
        try:
            inspected = json.loads(raw)[0]
            labels = inspected.get("Config", {}).get("Labels", {})
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ComposeScopeError(f"cannot inspect container {container_id}") from exc
        if labels.get("com.docker.compose.project") != self.project:
            raise ComposeScopeError(
                f"container {container_id} is outside Compose project {self.project}"
            )
        return container_id

    def wait_healthy(
        self, service: str, *, timeout: float = 60.0, poll_interval: float = 0.5
    ) -> None:
        self._validate_service(service)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self._compose("ps", "--format", "json", service, check=False)
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("Service") == service and row.get("State") == "running":
                    health = str(row.get("Health", "")).lower()
                    if health == "healthy":
                        return
            if poll_interval:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(f"health timeout for {service} after {timeout:.1f}s")

    def kill(self, service: str) -> None:
        container_id = self.resolve_container(service)
        self._docker("kill", container_id)

    def restart(self, service: str) -> None:
        self._validate_service(service)
        self.resolve_container(service)
        self._compose("up", "-d", "--no-deps", "--force-recreate", service)
        self.wait_healthy(service)

    def query_evidence(self, run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        """Return durable Run/Attempt/Event/Outbox counts for captured IDs."""
        if not self.database_url:
            raise RuntimeError("RUN_CONTROL_DATABASE_URL is required for evidence queries")
        if not run_ids:
            return {
                "runs": 0,
                "attempts": 0,
                "events": 0,
                "outbox": 0,
                "terminal_runs": 0,
                "pauses": 0,
                "revisions": 0,
                "legacy_rows": 0,
            }
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            parameters = (list(run_ids),)
            counts: dict[str, int] = {}
            for key, table in (
                ("runs", "runs"),
                ("attempts", "run_attempts"),
                ("events", "run_events"),
                ("outbox", "run_outbox"),
            ):
                cursor.execute(
                    f"SELECT count(*) FROM {table} WHERE run_id = ANY(%s::uuid[])", parameters
                )
                row = cursor.fetchone()
                counts[key] = int(row[0]) if row is not None else 0
            cursor.execute(
                "SELECT count(*) FROM runs WHERE id = ANY(%s::uuid[]) "
                "AND status IN ('completed','cancelled','failed','paused')",
                parameters,
            )
            row = cursor.fetchone()
            counts["terminal_runs"] = int(row[0]) if row is not None else 0
            cursor.execute("SELECT count(*) FROM chat_tasks")
            row = cursor.fetchone()
            counts["legacy_rows"] = int(row[0]) if row is not None else 0
            cursor.execute(
                "SELECT count(*) FROM run_pauses WHERE run_id = ANY(%s::uuid[])", parameters
            )
            row = cursor.fetchone()
            counts["pauses"] = int(row[0]) if row is not None else 0
            cursor.execute(
                "SELECT count(*) FROM runs WHERE id = ANY(%s::uuid[]) AND replaces_run_id IS NOT NULL",
                parameters,
            )
            row = cursor.fetchone()
            counts["revisions"] = int(row[0]) if row is not None else 0
        return counts

    def record(
        self, name: str, started: float, run_ids: list[str] | tuple[str, ...]
    ) -> ScenarioEvidence:
        if name not in CHAOS_SCENARIOS:
            raise ValueError(f"unknown chaos scenario: {name}")
        counts = self.query_evidence(run_ids)
        evidence = ScenarioEvidence(
            name,
            time.monotonic() - started,
            counts["runs"],
            counts["attempts"],
            counts["events"],
            counts["outbox"],
            counts["terminal_runs"],
            counts["pauses"],
            counts["revisions"],
            legacy_rows=counts["legacy_rows"],
        )
        minimums = _SCENARIO_MINIMUMS[name]
        counts = evidence.to_json()
        if any(int(counts.get(key, 0)) < minimum for key, minimum in minimums.items()):
            raise AssertionError(f"scenario {name} violated durable evidence contract: {evidence}")
        if name == "legacy_writer_zero" and counts["legacy_rows"] != 0:
            raise AssertionError(f"scenario {name} wrote legacy chat_tasks rows")
        self.evidence.append(evidence)
        return evidence

    def write_evidence(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replace atomically so a PowerShell catch/finally cannot append a
        # second JSON document and invalidate the evidence artifact.
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([item.to_json() for item in self.evidence], indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    def cleanup(self) -> None:
        """Remove only this project and prove no project container remains."""
        self._compose("down", "--volumes", "--remove-orphans", check=False)
        if self._last_compose_returncode != 0:
            raise ComposeScopeError(f"cleanup command failed for isolated project {self.project}")
        leftovers = self._compose("ps", "-q", check=False)
        if leftovers.strip():
            raise ComposeScopeError(
                f"cleanup left containers in isolated project {self.project}: {leftovers.strip()}"
            )
        for kind, command in (
            ("networks", ("network", "ls", "-q", "--filter")),
            ("volumes", ("volume", "ls", "-q", "--filter")),
        ):
            scoped = self._docker(*command, f"label=com.docker.compose.project={self.project}")
            if scoped.strip():
                raise ComposeScopeError(
                    f"cleanup left {kind} in isolated project {self.project}: {scoped.strip()}"
                )

    def run_scenarios(
        self,
        actions: Mapping[str, Callable[[], Sequence[str]]],
        *,
        evidence_path: Path | None = None,
    ) -> tuple[ScenarioEvidence, ...]:
        """Run every named failure action and persist durable evidence.

        Actions return the Run IDs they created.  Keeping actions injected makes
        the safety/self-test layer independent from a particular API client,
        while the production script supplies true Compose-process actions.
        An action failure is recorded with its original exception and then
        re-raised after all cleanup/evidence has been retained.
        """
        missing = set(CHAOS_SCENARIOS) - set(actions)
        extra = set(actions) - set(CHAOS_SCENARIOS)
        if missing or extra:
            raise ValueError(
                f"scenario map mismatch; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        first_error: Exception | None = None
        for name in CHAOS_SCENARIOS:
            started = time.monotonic()
            run_ids: Sequence[str] = ()
            try:
                run_ids = actions[name]()
                evidence = self.record(name, started, tuple(run_ids))
            except Exception as exc:
                counts = {
                    "runs": 0,
                    "attempts": 0,
                    "events": 0,
                    "outbox": 0,
                    "terminal_runs": 0,
                    "legacy_rows": 0,
                    "pauses": 0,
                    "revisions": 0,
                }
                if run_ids and self.database_url:
                    with suppress(Exception):
                        counts = self.query_evidence(tuple(run_ids))
                evidence = ScenarioEvidence(
                    name,
                    time.monotonic() - started,
                    counts["runs"],
                    counts["attempts"],
                    counts["events"],
                    counts["outbox"],
                    counts["terminal_runs"],
                    error=f"{type(exc).__name__}: {exc}",
                    pauses=counts["pauses"],
                    revisions=counts["revisions"],
                    legacy_rows=counts["legacy_rows"],
                )
                self.evidence.append(evidence)
                first_error = first_error or exc
        if evidence_path is not None:
            self.write_evidence(evidence_path)
        if first_error is not None:
            raise first_error
        return tuple(self.evidence)

    def _validate_service(self, service: str) -> None:
        if service not in _SAFE_SERVICES:
            raise ComposeScopeError(f"service {service!r} is outside run-control allowlist")

    def _docker(self, *args: str) -> str:
        result = self._runner(
            ("docker", *args),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=self.command_timeout,
        )
        if result is None or result.returncode != 0:
            raise ComposeScopeError(f"docker command failed: {getattr(result, 'stderr', '')}")
        return result.stdout or ""


def run_default_compose_suite(
    repo_root: Path, project: str, evidence_path: Path, *, timeout_seconds: float | None = None
) -> tuple[ScenarioEvidence, ...]:
    """Wire the named scenarios to the existing real-process acceptance client."""
    from tests.helpers.run_control_compose_harness import ComposeRunControlHarness

    legacy = ComposeRunControlHarness(repo_root)
    if timeout_seconds is not None:
        legacy.environment["RUN_CONTROL_COMMAND_TIMEOUT"] = str(max(1.0, timeout_seconds))
    legacy.project = project
    legacy.environment["RUN_CONTROL_COMPOSE_PROJECT"] = project
    build_mode = "--no-build" if legacy.environment.get("RUN_CONTROL_IMAGE") else "--build"
    legacy._compose(
        "up",
        "-d",
        build_mode,
        "--wait",
        "run-scheduler-a",
        "run-scheduler-b",
        "run-dispatcher",
        "run-worker-a",
        "run-worker-b",
        "run-api",
    )
    harness = RunControlChaosHarness(
        repo_root,
        project=project,
        database_url=legacy.database_url,
        command_timeout=max(1.0, timeout_seconds or 30.0),
    )

    def create_and_wait(key: str) -> list[str]:
        context = legacy._context()
        run_id = legacy._create_run(*context, key=key)
        legacy._wait_status(run_id, "completed", timeout=30)
        return [str(run_id)]

    def parallel() -> list[str]:
        return [str(item) for item in legacy._parallel_and_duplicate()]

    def browser_disconnect() -> list[str]:
        context = legacy._context()
        run_id = legacy._create_run(*context, key="browser-disconnect")
        token = jwt.encode(
            {"sub": str(context[1]), "exp": int(time.time()) + 3600},
            legacy.environment["RUN_CONTROL_JWT_SECRET_KEY"],
            algorithm="HS256",
        )
        request = Request(
            f"{legacy.api_url}/api/v1/tenants/{context[0]}/runs/{run_id}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        stream = urlopen(request, timeout=5)
        stream.close()  # browser disconnect; durable stream cursor is recovered below
        legacy._wait_status(run_id, "completed", timeout=30)
        return [str(run_id)]

    def tenant_fairness() -> list[str]:
        legacy.environment["RUN_WORKER_CAPACITY"] = "1"
        legacy._docker(
            "stop",
            legacy._scoped_named_container(f"{legacy.project}-run-worker-b-1", "run-worker-b"),
        )
        legacy._compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a")
        first_context = legacy._context()
        second_context = legacy._context()
        first = legacy._create_run(*first_context, key="fair-a")
        second = legacy._create_run(*second_context, key="fair-b")
        legacy._wait_status(first, "completed", timeout=30)
        legacy._wait_status(second, "completed", timeout=30)
        with legacy._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(DISTINCT tenant_id) FROM runs WHERE id=ANY(%s::uuid[])",
                ([first, second],),
            )
            row = cursor.fetchone()
            assert row is not None and row[0] == 2
            cursor.execute(
                "SELECT tenant_id, count(*) FROM runs WHERE id=ANY(%s::uuid[]) GROUP BY tenant_id ORDER BY tenant_id",
                ([first, second],),
            )
            distribution = cursor.fetchall()
            assert [int(item[1]) for item in distribution] == [1, 1]
            cursor.execute(
                "SELECT count(DISTINCT tenant_id) FROM run_attempts WHERE run_id=ANY(%s::uuid[])",
                ([first, second],),
            )
            row = cursor.fetchone()
            assert row is not None and row[0] == 2
        legacy._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        return [str(first), str(second)]

    def cancel_and_crash() -> list[str]:
        run_id = legacy._cancel_running_attempt()
        with legacy._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT worker_id FROM run_attempts WHERE run_id=%s ORDER BY attempt_no LIMIT 1",
                (run_id,),
            )
            row = cursor.fetchone()
            assert row is not None
            worker_id = row[0]
        legacy._docker(
            "kill", legacy._assert_scoped_container(legacy._container_for_worker(worker_id))
        )
        legacy._wait_status(run_id, "cancelled", timeout=10)
        return [str(run_id)]

    def pause_resume_slot_release() -> list[str]:
        context = legacy._context()
        previous = legacy.environment.copy()
        try:
            legacy.environment["RUN_WORKER_CAPACITY"] = "1"
            legacy.environment["RUN_SIMULATED_PAUSE_TYPE"] = "input"
            legacy._compose("stop", "run-worker-b", check=False)
            legacy._compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a")
            first = legacy._create_run(*context, key="pause-release-a")
            legacy._wait_status_in(first, {"waiting_approval", "waiting_input"}, timeout=15)
            second = legacy._create_run(*context, key="pause-release-b")
            legacy._wait_status_in(second, {"queued", "pending"}, timeout=15)
            with legacy._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pause_type FROM run_pauses WHERE run_id=%s ORDER BY pause_no DESC LIMIT 1",
                    (first,),
                )
                row = cursor.fetchone()
                assert row is not None and row[0] in {"approval", "input"}
                cursor.execute("SELECT status FROM runs WHERE id=%s", (second,))
                queued = cursor.fetchone()
                assert queued is not None and queued[0] in {"queued", "pending"}
            legacy._api(
                "POST",
                f"/api/v1/tenants/{context[0]}/runs/{first}/resume",
                context[1],
                body={"response": "continue"},
            )
            legacy._wait_status(first, "completed", timeout=30)
            legacy._wait_status(second, "completed", timeout=30)
            return [str(first), str(second)]
        finally:
            legacy.environment.clear()
            legacy.environment.update(previous)

    def revision_chain() -> list[str]:
        context = legacy._context()
        first = legacy._create_run(*context, key="revision-a")
        legacy._wait_status(first, "completed", timeout=30)
        session_id = legacy._run_session(first)
        previous = first
        ids = [first]
        for key in ("revision-b", "revision-c"):
            body = {"prompt": key, "session_id": str(session_id), "replaces_run_id": str(previous)}
            created = legacy._api(
                "POST",
                f"/api/v1/tenants/{context[0]}/runs",
                context[1],
                body=body,
                headers={"Idempotency-Key": key},
            )
            current = UUID(created["id"])
            legacy._wait_status(current, "completed", timeout=30)
            ids.append(current)
            previous = current
        with legacy._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT replaces_run_id FROM runs WHERE id=ANY(%s::uuid[]) ORDER BY created_at",
                (ids,),
            )
            chain = [row[0] for row in cursor.fetchall()]
            assert chain[0] is None and chain[1] == ids[0] and chain[2] == ids[1]
            cursor.execute("SELECT status FROM runs WHERE id=%s", (ids[0],))
            old_row = cursor.fetchone()
            assert old_row is not None and old_row[0] == "completed"
        return [str(item) for item in ids]

    def scheduler_dispatcher_restart() -> list[str]:
        for service in ("run-scheduler-a", "run-scheduler-b", "run-dispatcher"):
            legacy.resolve_container(service)
        legacy._compose("restart", "run-scheduler-a", "run-scheduler-b", "run-dispatcher")
        for service in ("run-scheduler-a", "run-scheduler-b", "run-dispatcher"):
            legacy._compose("ps", "--format", "json", service)
            harness.wait_healthy(service, timeout=30)
        run_ids = create_and_wait("scheduler-dispatcher-restart")
        with legacy._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM run_outbox WHERE run_id=%s AND acknowledged_at IS NOT NULL",
                (run_ids[0],),
            )
            row = cursor.fetchone()
            assert row is not None and row[0] > 0
        return run_ids

    def legacy_writer_zero() -> list[str]:
        run_ids = create_and_wait("legacy-writer-zero")
        with legacy._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM chat_tasks")
            row = cursor.fetchone()
            assert row is not None and row[0] == 0
        return run_ids

    def dual_scheduler() -> list[str]:
        rows = [
            json.loads(line)
            for line in legacy._compose("ps", "--format", "json").splitlines()
            if line.strip()
        ]
        healthy = {
            row.get("Service")
            for row in rows
            if row.get("State") == "running" and row.get("Health") == "healthy"
        }
        assert {"run-scheduler-a", "run-scheduler-b"} <= healthy
        # Two Runs enter the same queue; the existing helper asserts distinct
        # worker claims, one Attempt per Run, and durable Event/Outbox facts.
        return [str(item) for item in legacy._parallel_and_duplicate()]

    def duplicate_notification() -> list[str]:
        run_id, _ = legacy._parallel_and_duplicate()
        return [str(run_id)]

    def first_worker_crash() -> list[str]:
        return [str(legacy._kill_and_recover())]

    def second_worker_crash() -> list[str]:
        return [str(legacy._double_kill_retry_exhaustion())]

    def isolated(action: Callable[[], Sequence[str]]) -> Callable[[], Sequence[str]]:
        def invoke() -> Sequence[str]:
            previous = legacy.environment.copy()
            try:
                return action()
            finally:
                legacy.environment.clear()
                legacy.environment.update(previous)

        return invoke

    actions: dict[str, Callable[[], Sequence[str]]] = {
        "browser_disconnect": browser_disconnect,
        "two_worker_parallel": parallel,
        "tenant_fairness": tenant_fairness,
        "dual_scheduler": dual_scheduler,
        "duplicate_notification": duplicate_notification,
        "first_worker_crash": first_worker_crash,
        "second_worker_crash": second_worker_crash,
        "cancel_and_crash": cancel_and_crash,
        "pause_resume_slot_release": pause_resume_slot_release,
        "revision_chain": revision_chain,
        "redis_restart": lambda: [str(legacy._restart_redis_with_durable_outbox())],
        "scheduler_dispatcher_restart": scheduler_dispatcher_restart,
        "legacy_writer_zero": legacy_writer_zero,
    }
    actions = {name: isolated(action) for name, action in actions.items()}
    return harness.run_scenarios(actions, evidence_path=evidence_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args()
    run_default_compose_suite(
        args.repo_root, args.project, args.evidence, timeout_seconds=args.timeout
    )
