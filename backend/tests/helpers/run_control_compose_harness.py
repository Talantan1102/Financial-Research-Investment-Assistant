"""Self-bootstrapping Compose L2.5 acceptance harness for Phase 2 run control."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import psycopg
from jose import jwt
from redis import Redis


@dataclass(frozen=True)
class ComposeAcceptanceResult:
    project: str
    parallel_runs: tuple[UUID, UUID]
    crash_run: UUID
    redis_restart_run: UUID
    serial_runs: tuple[UUID, UUID]
    cancel_run: UUID
    capacity_runs: tuple[UUID, UUID]
    postgres_restart_run: UUID
    full_capacity_run: UUID


class ComposeCleanupError(RuntimeError):
    """Raised when bounded Compose cleanup cannot prove isolation."""


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ComposeRunControlHarness:
    def __init__(
        self,
        repo_root: Path,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        cleanup_attempts: int = 3,
        cleanup_retry_delay: float = 0.25,
    ) -> None:
        if cleanup_attempts <= 0 or cleanup_retry_delay < 0:
            raise ValueError("cleanup retry configuration is invalid")
        suffix = uuid4().hex[:10]
        self.project = f"rcp6-{suffix}"
        self.postgres_container = f"{self.project}-postgres"
        self.redis_container = f"{self.project}-redis"
        self.postgres_port = _free_port()
        self.redis_port = _free_port()
        self.api_port = _free_port()
        self.repo_root = repo_root
        self._runner = runner
        self._cleanup_attempts = cleanup_attempts
        self._cleanup_retry_delay = cleanup_retry_delay
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "RUN_CONTROL_POSTGRES_CONTAINER_NAME": self.postgres_container,
                "RUN_CONTROL_REDIS_CONTAINER_NAME": self.redis_container,
                "POSTGRES_PUBLISHED_PORT": str(self.postgres_port),
                "REDIS_PUBLISHED_PORT": str(self.redis_port),
                "RUN_CONTROL_API_PUBLISHED_PORT": str(self.api_port),
                "RUN_CONTROL_POSTGRES_USER": "rc_user",
                "RUN_CONTROL_POSTGRES_PASSWORD": f"rc-{suffix}",
                "RUN_CONTROL_POSTGRES_DB": "rc_acceptance",
                "RUN_CONTROL_JWT_SECRET_KEY": f"jwt-{suffix}-isolated-secret",
                "RUN_LEASE_SECONDS": "3",
                "RUN_HEARTBEAT_TTL_SECONDS": "3",
                "RUN_HEARTBEAT_INTERVAL_SECONDS": "0.25",
                "RUN_RENEW_INTERVAL_SECONDS": "0.25",
                "RUN_POLL_INTERVAL_SECONDS": "0.1",
                "RUN_SIMULATED_DELAY_SECONDS": "0.5",
            }
        )
        if image := os.getenv("RUN_CONTROL_ACCEPTANCE_IMAGE"):
            self.environment["RUN_CONTROL_IMAGE"] = image
        self.database_url = (
            f"postgresql://rc_user:rc-{suffix}@127.0.0.1:{self.postgres_port}/rc_acceptance"
        )
        self.redis_url = f"redis://127.0.0.1:{self.redis_port}/0"
        self.api_url = f"http://127.0.0.1:{self.api_port}"

    def resolve_container(self, service: str) -> str:
        """Resolve one container and prove Compose project/service ownership."""
        output = self._compose("ps", "-q", service, check=False)
        ids = [line.strip() for line in output.splitlines() if line.strip()]
        if len(ids) != 1:
            raise ComposeCleanupError(f"expected one container for {service!r}: {ids!r}")
        return self._assert_scoped_container(ids[0], service)

    def _assert_scoped_container(self, container: str, service: str | None = None) -> str:
        try:
            inspected = json.loads(self._docker("inspect", container))[0]
            labels = inspected.get("Config", {}).get("Labels", {})
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ComposeCleanupError(f"cannot inspect container {container}") from exc
        if labels.get("com.docker.compose.project") != self.project:
            raise ComposeCleanupError(
                f"container {container} is outside Compose project {self.project}"
            )
        actual_service = labels.get("com.docker.compose.service")
        if actual_service not in {
            "run-worker-a",
            "run-worker-b",
            "run-dispatcher",
            "redis",
            "postgres",
        }:
            raise ComposeCleanupError(
                f"container {container} has unexpected Compose service {actual_service!r}"
            )
        if service is not None and actual_service != service:
            raise ComposeCleanupError(f"container {container} is not Compose service {service}")
        return container

    def _scoped_named_container(self, container: str, service: str) -> str:
        return self._assert_scoped_container(container, service)

    def run(self) -> ComposeAcceptanceResult:
        result: ComposeAcceptanceResult | None = None
        primary_error: Exception | None = None
        try:
            build_mode = "--no-build" if self.environment.get("RUN_CONTROL_IMAGE") else "--build"
            self._compose(
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
            self._assert_processes_healthy()
            if os.getenv("RUN_CONTROL_INJECT_FAILURE_AFTER_UP") == "1":
                raise RuntimeError("injected failure after Compose up")
            parallel = self._parallel_and_duplicate()
            crash = self._kill_and_recover()
            redis_restart = self._restart_redis_with_durable_outbox()
            serial = self._same_session_serialization()
            cancel = self._cancel_running_attempt()
            capacity = self._single_worker_capacity_two()
            self._double_kill_retry_exhaustion()
            postgres_restart = self._restart_postgres_and_recover()
            full_capacity = self._full_capacity_stays_healthy()
            result = ComposeAcceptanceResult(
                project=self.project,
                parallel_runs=parallel,
                crash_run=crash,
                redis_restart_run=redis_restart,
                serial_runs=serial,
                cancel_run=cancel,
                capacity_runs=capacity,
                postgres_restart_run=postgres_restart,
                full_capacity_run=full_capacity,
            )
        except Exception as exc:
            primary_error = exc
        cleanup_error: Exception | None = None
        try:
            self._cleanup()
        except Exception as exc:
            cleanup_error = exc
        if primary_error is not None and cleanup_error is not None:
            raise ExceptionGroup(
                "run-control acceptance and cleanup both failed",
                [primary_error, cleanup_error],
            )
        if primary_error is not None:
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
        assert result is not None
        return result

    def _parallel_and_duplicate(self) -> tuple[UUID, UUID]:
        context_a = self._context()
        context_b = self._context(tenant_id=context_a[0], user_id=context_a[1])
        run_a = self._create_run(*context_a, key="parallel-a")
        run_b = self._create_run(*context_b, key="parallel-b")
        self._wait_status(run_a, "completed", timeout=15)
        self._wait_status(run_b, "completed", timeout=15)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT runs.started_at, runs.finished_at, run_attempts.worker_id "
                "FROM runs JOIN run_attempts ON run_attempts.run_id=runs.id "
                "WHERE runs.id=ANY(%s::uuid[])",
                ([run_a, run_b],),
            )
            rows = cursor.fetchall()
            assert len(rows) == 2
            assert len({row[2] for row in rows}) == 2
            assert max(row[0] for row in rows) < min(row[1] for row in rows)
        outbox_row = self._wait_outbox_facts(
            run_a,
            "attempt.assigned",
            lambda row: row is not None and row[4] >= 1 and row[5] and row[6],
            select=(
                "id,tenant_id,attempt_id,worker_id,delivery_attempts,"
                "delivered_at IS NOT NULL,acknowledged_at IS NOT NULL"
            ),
        )
        outbox_id, tenant_id, attempt_id, worker_id, delivery_attempts, _, _ = outbox_row
        envelope = json.dumps(
            {
                "v": 1,
                "outbox_id": str(outbox_id),
                "event_type": "attempt.assigned",
                "tenant_id": str(tenant_id),
                "run_id": str(run_a),
                "attempt_id": str(attempt_id),
                "worker_id": str(worker_id),
                "payload": {},
                "delivery_attempts": delivery_attempts,
            },
            separators=(",", ":"),
        )
        redis = Redis.from_url(self.redis_url)
        key = f"run:worker:{worker_id}:assignments"
        try:
            redis.xadd(key, {"data": envelope})
            self._wait(lambda: redis.xlen(key) == 0, timeout=5, message="duplicate not drained")
            pending = cast(dict[str, Any], redis.xpending(key, "run-worker-assignments-v1"))
            assert pending["pending"] == 0
        finally:
            redis.close()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM run_attempts WHERE run_id=%s", (run_a,))
            assert cursor.fetchone() == (1,)
            cursor.execute(
                "SELECT count(*),max(seq),count(*) FILTER (WHERE event_type='run.completed') "
                "FROM run_events WHERE run_id=%s",
                (run_a,),
            )
            assert cursor.fetchone() == (4, 4, 1)
        return run_a, run_b

    def _kill_and_recover(self) -> UUID:
        self.environment["RUN_LEASE_SECONDS"] = "1"
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "2"
        self._compose(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "run-scheduler-a",
            "run-scheduler-b",
            "run-worker-a",
            "run-worker-b",
        )
        run_id = self._create_run(*self._context(), key="crash")
        first = self._wait_attempt(run_id, 1, "running", timeout=10)
        container = self._container_for_worker(first[1])
        self._docker(
            "update",
            "--restart=no",
            self._scoped_named_container(
                container,
                "run-worker-a" if container.endswith("run-worker-a-1") else "run-worker-b",
            ),
        )
        self._docker(
            "kill",
            self._scoped_named_container(
                container,
                "run-worker-a" if container.endswith("run-worker-a-1") else "run-worker-b",
            ),
        )
        second = self._wait_attempt(run_id, 2, "running", timeout=10)
        assert second[1] != first[1]
        self._wait_status(run_id, "completed", timeout=10)
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT attempt_no,status FROM run_attempts WHERE run_id=%s ORDER BY attempt_no",
                (run_id,),
            )
            assert cursor.fetchall() == [(1, "lost"), (2, "completed")]
            cursor.execute("SELECT retry_count FROM runs WHERE id=%s", (run_id,))
            assert cursor.fetchone() == (1,)
        return run_id

    def _restart_redis_with_durable_outbox(self) -> UUID:
        self.environment["RUN_LEASE_SECONDS"] = "10"
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "0.5"
        self._compose(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "run-scheduler-a",
            "run-scheduler-b",
            "run-worker-a",
            "run-worker-b",
        )
        dispatcher = f"{self.project}-run-dispatcher-1"
        redis_dependent_services = (
            "run-scheduler-a",
            "run-scheduler-b",
            "run-dispatcher",
            "run-worker-a",
            "run-worker-b",
        )
        before = {
            service: json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]
            for service in redis_dependent_services
        }
        self._docker("stop", self._scoped_named_container(dispatcher, "run-dispatcher"))
        run_id = self._create_run(*self._context(), key="redis-restart")
        self._wait_status(run_id, "assigned", timeout=10)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id,attempt_id FROM run_outbox "
                "WHERE run_id=%s AND event_type='attempt.assigned' ORDER BY id",
                (run_id,),
            )
            original_rows = cursor.fetchall()
            assert len(original_rows) == 1
            outbox_id, original_attempt_id = original_rows[0]
            cursor.execute(
                "UPDATE run_attempts SET lease_expires_at=CURRENT_TIMESTAMP + INTERVAL '90 seconds' "
                "WHERE run_id=%s AND id=%s",
                (run_id, original_attempt_id),
            )
            assert cursor.rowcount == 1
            connection.commit()
        self._wait_outbox_by_id(
            outbox_id,
            lambda row: row == (0, None, None),
        )
        self._docker("stop", self._scoped_named_container(self.redis_container, "redis"))

        def redis_outage_visible() -> bool:
            states = [
                json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]["State"]
                for service in redis_dependent_services
                if service != "run-dispatcher"
            ]
            return all(state["Running"] for state in states) and any(
                state["Health"]["Status"] != "healthy" for state in states
            )

        self._wait(
            redis_outage_visible,
            timeout=12,
            message="Redis outage did not invalidate process health",
        )
        self._docker("start", self._scoped_named_container(self.redis_container, "redis"))
        self._docker("start", self._scoped_named_container(dispatcher, "run-dispatcher"))

        def redis_dependents_recovered() -> bool:
            current = {
                service: json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]
                for service in redis_dependent_services
            }
            return all(
                value["State"]["Running"]
                and value["State"]["Health"]["Status"] == "healthy"
                and value["Id"] == before[service]["Id"]
                for service, value in current.items()
            )

        self._wait(
            redis_dependents_recovered,
            timeout=20,
            message="processes did not self-heal after Redis restart",
        )
        self._wait_status(run_id, "completed", timeout=15)
        self._wait_outbox_by_id(
            outbox_id,
            lambda row: row is not None and row[0] >= 1 and row[1:] == (True, True),
            select="delivery_attempts,delivered_at IS NOT NULL,acknowledged_at IS NOT NULL",
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM run_attempts WHERE run_id=%s ORDER BY attempt_no",
                (run_id,),
            )
            assert cursor.fetchall() == [(original_attempt_id,)]
        return run_id

    def _same_session_serialization(self) -> tuple[UUID, UUID]:
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "1"
        self._compose(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "run-worker-a",
            "run-worker-b",
        )
        context = self._context()
        first = self._create_run(*context, key="serial-a")
        self._wait_status(first, "running", timeout=10)
        try:
            self._create_run(*context, key="serial-rejected", session_id=self._run_session(first))
        except HTTPError as exc:
            assert exc.code == 409
            pass
        else:
            raise AssertionError("same Session accepted two active Runs")
        self._wait_status(first, "completed", timeout=10)
        second = self._create_run(*context, key="serial-b", session_id=self._run_session(first))
        self._wait_status(second, "completed", timeout=10)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT started_at,finished_at FROM runs WHERE id=ANY(%s::uuid[]) "
                "ORDER BY started_at",
                ([first, second],),
            )
            rows = cursor.fetchall()
            assert rows[0][1] <= rows[1][0]
        return first, second

    def _context(
        self,
        *,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> tuple[UUID, UUID]:
        tenant_id = tenant_id or uuid4()
        user_id = user_id or uuid4()
        with self._connect() as connection, connection.cursor() as cursor:
            if user_id is not None:
                cursor.execute(
                    "INSERT INTO users(id,username,email,hashed_password,is_active,is_superuser,"
                    "created_at,updated_at) VALUES (%s,%s,%s,'hash',true,false,now(),now()) "
                    "ON CONFLICT (id) DO NOTHING",
                    (user_id, f"u-{user_id}", f"{user_id}@example.com"),
                )
            cursor.execute(
                "INSERT INTO tenants(id,name,slug,is_personal,max_running_runs,max_queued_runs,"
                "created_at) VALUES (%s,%s,%s,false,2,20,now()) ON CONFLICT (id) DO NOTHING",
                (tenant_id, f"t-{tenant_id}", f"t-{tenant_id}"),
            )
            cursor.execute(
                "INSERT INTO tenant_memberships(tenant_id,user_id,role,joined_at) "
                "VALUES (%s,%s,'owner',now()) ON CONFLICT DO NOTHING",
                (tenant_id, user_id),
            )
        return tenant_id, user_id

    def _create_run(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        key: str,
        session_id: UUID | None = None,
    ) -> UUID:
        body: dict[str, Any] = {"prompt": f"acceptance {key}"}
        if session_id is not None:
            body["session_id"] = str(session_id)
        created = self._api(
            "POST",
            f"/api/v1/tenants/{tenant_id}/runs",
            user_id,
            body=body,
            headers={"Idempotency-Key": key},
        )
        run_id = UUID(created["id"])
        fetched = self._api("GET", f"/api/v1/tenants/{tenant_id}/runs/{run_id}", user_id)
        assert fetched["id"] == str(run_id) and fetched["tenant_id"] == str(tenant_id)
        return run_id

    def _cancel_running_attempt(self) -> UUID:
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "5"
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        tenant_id, user_id = self._context()
        run_id = self._create_run(tenant_id, user_id, key="cancel")
        self._wait_status(run_id, "running", timeout=10)
        self._api("POST", f"/api/v1/tenants/{tenant_id}/runs/{run_id}/cancel", user_id, body={})
        self._wait_status(run_id, "cancelled", timeout=3)
        self._wait_outbox_facts(
            run_id,
            "attempt.cancel",
            lambda row: (
                row is not None and row[0] >= 1 and row[1] is not None and row[2] is not None
            ),
        )
        return run_id

    def _single_worker_capacity_two(self) -> tuple[UUID, UUID]:
        self.environment["RUN_WORKER_CAPACITY"] = "2"
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "1"
        self._docker(
            "stop", self._scoped_named_container(f"{self.project}-run-worker-b-1", "run-worker-b")
        )
        self._compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a")
        first = self._create_run(*self._context(), key="capacity-a")
        second = self._create_run(*self._context(), key="capacity-b")
        self._wait_status(first, "completed", timeout=10)
        self._wait_status(second, "completed", timeout=10)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT runs.started_at,runs.finished_at,run_attempts.worker_id FROM runs JOIN run_attempts "
                "ON run_attempts.run_id=runs.id WHERE runs.id=ANY(%s::uuid[])",
                ([first, second],),
            )
            rows = cursor.fetchall()
            assert len({row[2] for row in rows}) == 1
            assert max(row[0] for row in rows) < min(row[1] for row in rows)
        self.environment["RUN_WORKER_CAPACITY"] = "1"
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        return first, second

    def _double_kill_retry_exhaustion(self) -> UUID:
        self.environment["RUN_LEASE_SECONDS"] = "1"
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "5"
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        run_id = self._create_run(*self._context(), key="double-kill")
        first = self._wait_attempt(run_id, 1, "running", timeout=10)
        first_container = self._container_for_worker(first[1])
        self._docker("update", "--restart=no", self._assert_scoped_container(first_container))
        self._docker("kill", self._assert_scoped_container(first_container))
        second = self._wait_attempt(run_id, 2, "running", timeout=10)
        second_container = self._container_for_worker(second[1])
        self._docker("update", "--restart=no", self._assert_scoped_container(second_container))
        self._docker("kill", self._assert_scoped_container(second_container))
        self._wait_status(run_id, "failed", timeout=10)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT attempt_no,status FROM run_attempts WHERE run_id=%s ORDER BY attempt_no",
                (run_id,),
            )
            assert cursor.fetchall() == [(1, "lost"), (2, "lost")]
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "0.5"
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        return run_id

    def _restart_postgres_and_recover(self) -> UUID:
        services = (
            "run-scheduler-a",
            "run-scheduler-b",
            "run-dispatcher",
            "run-worker-a",
            "run-worker-b",
            "run-api",
        )
        before = {
            service: json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]
            for service in services
        }
        self._docker("stop", self._scoped_named_container(self.postgres_container, "postgres"))

        def observed_unhealthy() -> bool:
            states = [
                json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]["State"]
                for service in services
            ]
            return all(state["Running"] for state in states) and any(
                state["Health"]["Status"] != "healthy" for state in states
            )

        self._wait(observed_unhealthy, timeout=12, message="PG outage did not invalidate health")
        self._docker("start", self._scoped_named_container(self.postgres_container, "postgres"))

        def all_healthy() -> bool:
            current = {
                service: json.loads(self._docker("inspect", f"{self.project}-{service}-1"))[0]
                for service in services
            }
            return all(
                value["State"]["Running"]
                and value["State"]["Health"]["Status"] == "healthy"
                and value["Id"] == before[service]["Id"]
                and value["RestartCount"] >= before[service]["RestartCount"]
                for service, value in current.items()
            )

        self._wait(all_healthy, timeout=20, message="processes did not self-heal after PG restart")
        run_id = self._create_run(*self._context(), key="postgres-restart")
        self._wait_status(run_id, "completed", timeout=15)
        return run_id

    def _full_capacity_stays_healthy(self) -> UUID:
        self.environment["RUN_WORKER_CAPACITY"] = "1"
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "5"
        self._docker(
            "stop", self._scoped_named_container(f"{self.project}-run-worker-b-1", "run-worker-b")
        )
        self._compose("up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a")
        run_id = self._create_run(*self._context(), key="full-capacity-health")
        self._wait_status(run_id, "running", timeout=10)
        time.sleep(3.5)
        state = json.loads(self._docker("inspect", f"{self.project}-run-worker-a-1"))[0]["State"]
        assert state["Running"] is True
        assert state["Health"]["Status"] == "healthy"
        self._wait_status(run_id, "completed", timeout=5)
        self.environment["RUN_SIMULATED_DELAY_SECONDS"] = "0.5"
        self._compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "run-worker-a", "run-worker-b"
        )
        return run_id

    def _run_session(self, run_id: UUID) -> UUID:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT session_id FROM runs WHERE id=%s", (run_id,))
            row = cursor.fetchone()
        assert row is not None
        return row[0]

    def _api(
        self,
        method: str,
        path: str,
        user_id: UUID,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        token = jwt.encode(
            {"sub": str(user_id), "username": f"u-{user_id}", "exp": int(time.time()) + 3600},
            self.environment["RUN_CONTROL_JWT_SECRET_KEY"],
            algorithm="HS256",
        )
        request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(self.api_url + path, data=data, headers=request_headers, method=method)
        with urlopen(request, timeout=5) as response:  # noqa: S310 - isolated localhost harness
            return json.loads(response.read().decode("utf-8"))

    def _wait_attempt(
        self, run_id: UUID, attempt_no: int, status: str, *, timeout: float
    ) -> tuple[UUID, UUID]:
        found: tuple[UUID, UUID] | None = None

        def query() -> bool:
            nonlocal found
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id,worker_id FROM run_attempts "
                    "WHERE run_id=%s AND attempt_no=%s AND status=%s",
                    (run_id, attempt_no, status),
                )
                found = cursor.fetchone()
            return found is not None

        self._wait(query, timeout=timeout, message=f"attempt {attempt_no} not {status}")
        assert found is not None
        return found

    def _wait_status(self, run_id: UUID, status: str, *, timeout: float) -> None:
        def query() -> bool:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT status FROM runs WHERE id=%s", (run_id,))
                row = cursor.fetchone()
            return row == (status,)

        self._wait(query, timeout=timeout, message=f"Run {run_id} did not reach {status}")

    def _wait_status_in(self, run_id: UUID, statuses: set[str], *, timeout: float) -> str:
        observed: list[str] = []

        def query() -> bool:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT status FROM runs WHERE id=%s", (run_id,))
                row = cursor.fetchone()
            if row is not None:
                observed.append(str(row[0]))
            return row is not None and row[0] in statuses

        self._wait(
            query,
            timeout=timeout,
            message=f"Run {run_id} did not reach one of {sorted(statuses)}; observed={observed[-1:]}",
        )
        return observed[-1]

    def _wait_outbox_facts(
        self,
        run_id: UUID,
        event_type: str,
        predicate: Callable[[tuple[Any, ...] | None], bool],
        *,
        timeout: float = 10,
        select: str = "delivery_attempts,delivered_at,acknowledged_at",
    ) -> tuple[Any, ...]:
        last: tuple[Any, ...] | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {select} FROM run_outbox WHERE run_id=%s AND event_type=%s",
                    (run_id, event_type),
                )
                last = cursor.fetchone()
            if predicate(last):
                assert last is not None
                return last
            time.sleep(0.1)
        raise AssertionError(
            f"Outbox facts did not stabilize for run={run_id} event={event_type}; last={last!r}"
        )

    def _wait_outbox_by_id(
        self,
        outbox_id: UUID,
        predicate: Callable[[tuple[Any, ...] | None], bool],
        *,
        timeout: float = 10,
        select: str = "delivery_attempts,delivered_at,acknowledged_at",
    ) -> tuple[Any, ...]:
        last: tuple[Any, ...] | None = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {select} FROM run_outbox WHERE id=%s",
                    (outbox_id,),
                )
                last = cursor.fetchone()
            if predicate(last):
                assert last is not None
                return last
            time.sleep(0.1)
        raise AssertionError(
            f"Outbox facts did not stabilize for outbox_id={outbox_id}; last={last!r}"
        )

    def _container_for_worker(self, worker_id: UUID) -> str:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT metadata->>'hostname' FROM run_workers WHERE id=%s", (worker_id,)
            )
            worker_row = cursor.fetchone()
            assert worker_row is not None
            hostname = worker_row[0]
        for service in ("run-worker-a", "run-worker-b"):
            name = f"{self.project}-{service}-1"
            inspected = self._docker("inspect", "-f", "{{.Config.Hostname}}", name).strip()
            if inspected == hostname:
                return name
        raise AssertionError(f"no container for Worker {worker_id}")

    def _assert_processes_healthy(self) -> None:
        raw = self._compose("ps", "--format", "json")
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        expected = {
            "run-scheduler-a",
            "run-scheduler-b",
            "run-dispatcher",
            "run-worker-a",
            "run-worker-b",
            "run-api",
        }
        healthy = {
            row["Service"]
            for row in rows
            if row["State"] == "running" and row["Health"] == "healthy"
        }
        assert expected <= healthy

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    @staticmethod
    def _wait(predicate: Any, *, timeout: float, message: str) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        raise AssertionError(message)

    def _compose(self, *arguments: str, check: bool = True) -> str:
        return self._command(
            "docker",
            "compose",
            "-p",
            self.project,
            "--profile",
            "run-control",
            *arguments,
            check=check,
        )

    def _cleanup(self) -> None:
        attempts: list[str] = []
        down_succeeded = False
        for attempt in range(1, self._cleanup_attempts + 1):
            completed = self._command_result(
                "docker",
                "compose",
                "-p",
                self.project,
                "--profile",
                "run-control",
                "down",
                "-v",
                "--remove-orphans",
            )
            attempts.append(
                f"attempt={attempt} rc={completed.returncode} "
                f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
            )
            if completed.returncode == 0:
                down_succeeded = True
                break
            if attempt < self._cleanup_attempts:
                time.sleep(self._cleanup_retry_delay)

        leftovers: dict[str, str] = {}
        for kind, command in {
            "containers": ("docker", "ps", "-aq", "--filter"),
            "networks": ("docker", "network", "ls", "-q", "--filter"),
            "volumes": ("docker", "volume", "ls", "-q", "--filter"),
        }.items():
            completed = self._command_result(
                *command,
                f"label=com.docker.compose.project={self.project}",
            )
            if completed.returncode != 0:
                leftovers[kind] = (
                    f"audit rc={completed.returncode} stdout={completed.stdout!r} "
                    f"stderr={completed.stderr!r}"
                )
            elif completed.stdout.strip():
                leftovers[kind] = completed.stdout.strip()

        if not down_succeeded or leftovers:
            raise ComposeCleanupError(
                "Compose cleanup could not prove isolation; "
                + "; ".join(attempts)
                + f"; leftovers={leftovers!r}"
            )

    def _docker(self, *arguments: str) -> str:
        return self._command("docker", *arguments)

    def _command(self, *arguments: str, check: bool = True) -> str:
        completed = self._command_result(*arguments)
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed.stdout

    def _command_result(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self._runner(
            arguments,
            cwd=self.repo_root,
            env=self.environment,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
        )
