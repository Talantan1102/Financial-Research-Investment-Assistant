"""Self-bootstrapping Compose L2.5 acceptance harness for Phase 2 run control."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import errors
from redis import Redis


@dataclass(frozen=True)
class ComposeAcceptanceResult:
    project: str
    parallel_runs: tuple[UUID, UUID]
    crash_run: UUID
    redis_restart_run: UUID
    serial_runs: tuple[UUID, UUID]


def _free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ComposeRunControlHarness:
    def __init__(self, repo_root: Path) -> None:
        suffix = uuid4().hex[:10]
        self.project = f"rcp6-{suffix}"
        self.postgres_container = f"{self.project}-postgres"
        self.redis_container = f"{self.project}-redis"
        self.postgres_port = _free_port()
        self.redis_port = _free_port()
        self.repo_root = repo_root
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "RUN_CONTROL_POSTGRES_CONTAINER_NAME": self.postgres_container,
                "RUN_CONTROL_REDIS_CONTAINER_NAME": self.redis_container,
                "POSTGRES_PUBLISHED_PORT": str(self.postgres_port),
                "REDIS_PUBLISHED_PORT": str(self.redis_port),
                "RUN_LEASE_SECONDS": "3",
                "RUN_HEARTBEAT_TTL_SECONDS": "3",
                "RUN_HEARTBEAT_INTERVAL_SECONDS": "0.25",
                "RUN_RENEW_INTERVAL_SECONDS": "0.25",
                "RUN_POLL_INTERVAL_SECONDS": "0.1",
                "RUN_SIMULATED_DELAY_SECONDS": "0.5",
            }
        )
        self.database_url = (
            f"postgresql://postgres:postgres123@127.0.0.1:{self.postgres_port}/industry_assistant"
        )
        self.redis_url = f"redis://127.0.0.1:{self.redis_port}/0"

    def run(self) -> ComposeAcceptanceResult:
        try:
            self._compose(
                "up",
                "-d",
                "--build",
                "--wait",
                "run-scheduler-a",
                "run-scheduler-b",
                "run-dispatcher",
                "run-worker-a",
                "run-worker-b",
            )
            self._assert_processes_healthy()
            parallel = self._parallel_and_duplicate()
            crash = self._kill_and_recover()
            redis_restart = self._restart_redis_with_durable_outbox()
            serial = self._same_session_serialization()
            return ComposeAcceptanceResult(
                project=self.project,
                parallel_runs=parallel,
                crash_run=crash,
                redis_restart_run=redis_restart,
                serial_runs=serial,
            )
        finally:
            self._compose("down", "-v", "--remove-orphans", check=False)

    def _parallel_and_duplicate(self) -> tuple[UUID, UUID]:
        context_a = self._context()
        context_b = self._context(tenant_id=context_a[0], user_id=context_a[1])
        run_a = self._insert_run(*context_a, key="parallel-a")
        run_b = self._insert_run(*context_b, key="parallel-b")
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
            cursor.execute(
                "SELECT o.id,o.tenant_id,o.attempt_id,o.worker_id,o.delivery_attempts "
                "FROM run_outbox o WHERE o.run_id=%s AND o.event_type='attempt.assigned'",
                (run_a,),
            )
            outbox_row = cursor.fetchone()
            assert outbox_row is not None
            outbox_id, tenant_id, attempt_id, worker_id, delivery_attempts = outbox_row
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
        run_id = self._insert_run(*self._context(), key="crash")
        first = self._wait_attempt(run_id, 1, "running", timeout=10)
        self._docker("kill", self._container_for_worker(first[1]))
        second = self._wait_attempt(run_id, 2, "running", timeout=10)
        assert second[1] != first[1]
        self._wait_status(run_id, "completed", timeout=10)
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
        self._docker("stop", dispatcher)
        run_id = self._insert_run(*self._context(), key="redis-restart")
        self._wait_status(run_id, "assigned", timeout=10)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT delivery_attempts,delivered_at,acknowledged_at FROM run_outbox "
                "WHERE run_id=%s AND event_type='attempt.assigned'",
                (run_id,),
            )
            assert cursor.fetchone() == (0, None, None)
        self._docker("restart", self.redis_container)
        self._docker("start", dispatcher)
        self._wait_status(run_id, "completed", timeout=15)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT delivery_attempts,delivered_at IS NOT NULL,acknowledged_at IS NOT NULL "
                "FROM run_outbox WHERE run_id=%s AND event_type='attempt.assigned'",
                (run_id,),
            )
            assert cursor.fetchone() == (1, True, True)
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
        first = self._insert_run(*context, key="serial-a")
        self._wait_status(first, "running", timeout=10)
        try:
            self._insert_run(*context, key="serial-rejected")
        except errors.UniqueViolation:
            pass
        else:
            raise AssertionError("same Session accepted two active Runs")
        self._wait_status(first, "completed", timeout=10)
        second = self._insert_run(*context, key="serial-b")
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
    ) -> tuple[UUID, UUID, UUID, UUID]:
        tenant_id = tenant_id or uuid4()
        user_id = user_id or uuid4()
        session_id = uuid4()
        message_id = uuid4()
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
            cursor.execute(
                "INSERT INTO run_sessions(id,tenant_id,created_by_user_id,title,created_at,updated_at) "
                "VALUES (%s,%s,%s,'acceptance',now(),now())",
                (session_id, tenant_id, user_id),
            )
            cursor.execute(
                "INSERT INTO run_messages(id,tenant_id,session_id,role,content,status,created_at) "
                "VALUES (%s,%s,%s,'user','acceptance','done',now())",
                (message_id, tenant_id, session_id),
            )
        return tenant_id, user_id, session_id, message_id

    def _insert_run(
        self,
        tenant_id: UUID,
        user_id: UUID,
        session_id: UUID,
        message_id: UUID,
        *,
        key: str,
    ) -> UUID:
        run_id, event_id, outbox_id = uuid4(), uuid4(), uuid4()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO runs(id,tenant_id,session_id,created_by_user_id,run_type,status,"
                "idempotency_key,request_hash,input_message_id,retry_count,queue_reason,created_at,"
                "queued_at) VALUES (%s,%s,%s,%s,'chat','queued',%s,%s,%s,0,'created',now(),now())",
                (run_id, tenant_id, session_id, user_id, key, uuid4().hex * 2, message_id),
            )
            cursor.execute(
                "INSERT INTO run_events(id,tenant_id,run_id,seq,event_type,payload,created_at) "
                "VALUES (%s,%s,%s,1,'run.created','{}',now())",
                (event_id, tenant_id, run_id),
            )
            cursor.execute(
                "INSERT INTO run_outbox(id,event_type,tenant_id,run_id,payload,dedupe_key,"
                "available_at,delivery_attempts,created_at) VALUES "
                "(%s,'schedule.wake',%s,%s,'{}',%s,now(),0,now())",
                (outbox_id, tenant_id, run_id, f"schedule.wake:{run_id}:create"),
            )
        return run_id

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

    def _docker(self, *arguments: str) -> str:
        return self._command("docker", *arguments)

    def _command(self, *arguments: str, check: bool = True) -> str:
        completed = subprocess.run(
            arguments,
            cwd=self.repo_root,
            env=self.environment,
            check=check,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
        )
        return completed.stdout
