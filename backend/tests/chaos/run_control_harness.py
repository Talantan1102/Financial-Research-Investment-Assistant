"""Process-level failure harness for the Run control plane.

The harness deliberately keeps the destructive surface small: every docker
operation is made through one explicitly named Compose project and every
reported scenario carries PostgreSQL facts.  It is usable from pytest for
self-tests and from ``run_control_chaos.ps1`` for the real-process suite.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psycopg

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
    error: str | None = None

    @property
    def has_database_facts(self) -> bool:
        return self.runs > 0 and self.attempts > 0 and self.events > 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"has_database_facts": self.has_database_facts}


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
                    if health in {"healthy", ""}:
                        return
            if poll_interval:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        raise TimeoutError(f"health timeout for {service} after {timeout:.1f}s")

    def kill(self, service: str) -> None:
        container_id = self.resolve_container(service)
        self._docker("kill", container_id)

    def restart(self, service: str) -> None:
        self._validate_service(service)
        self._compose("up", "-d", "--no-deps", "--force-recreate", service)
        self.wait_healthy(service)

    def query_evidence(self, run_ids: list[str] | tuple[str, ...]) -> dict[str, int]:
        """Return durable Run/Attempt/Event/Outbox counts for captured IDs."""
        if not self.database_url:
            raise RuntimeError("RUN_CONTROL_DATABASE_URL is required for evidence queries")
        if not run_ids:
            return {"runs": 0, "attempts": 0, "events": 0, "outbox": 0}
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            parameters = (list(run_ids),)
            counts: dict[str, int] = {}
            for key, table in (
                ("runs", "runs"),
                ("attempts", "run_attempts"),
                ("events", "run_events"),
                ("outbox", "run_outbox"),
            ):
                cursor.execute(f"SELECT count(*) FROM {table} WHERE run_id = ANY(%s::uuid[])", parameters)
                row = cursor.fetchone()
                counts[key] = int(row[0]) if row is not None else 0
        return counts

    def record(self, name: str, started: float, run_ids: list[str] | tuple[str, ...]) -> ScenarioEvidence:
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
        )
        if not evidence.has_database_facts:
            raise AssertionError(f"scenario {name} has no durable database facts: {evidence}")
        self.evidence.append(evidence)
        return evidence

    def write_evidence(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([item.to_json() for item in self.evidence], indent=2), encoding="utf-8")

    def cleanup(self) -> None:
        """Remove only this project and prove no project container remains."""
        self._compose("down", "--remove-orphans", check=False)
        if self._last_compose_returncode != 0:
            raise ComposeScopeError(
                f"cleanup command failed for isolated project {self.project}"
            )
        leftovers = self._compose("ps", "-q", check=False)
        if leftovers.strip():
            raise ComposeScopeError(
                f"cleanup left containers in isolated project {self.project}: {leftovers.strip()}"
            )

    def run_scenarios(
        self,
        actions: dict[str, Callable[[], Sequence[str]]],
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
            raise ValueError(f"scenario map mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
        first_error: Exception | None = None
        for name in CHAOS_SCENARIOS:
            started = time.monotonic()
            run_ids: Sequence[str] = ()
            try:
                run_ids = actions[name]()
                evidence = self.record(name, started, tuple(run_ids))
            except Exception as exc:
                counts = {"runs": 0, "attempts": 0, "events": 0, "outbox": 0}
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
                    error=f"{type(exc).__name__}: {exc}",
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
