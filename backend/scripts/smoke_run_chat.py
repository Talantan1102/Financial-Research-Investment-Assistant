"""Credential-safe live smoke for the v1 Run chat path.

The script intentionally emits one small JSON object containing only route,
opaque identifiers, status, and timing. It never logs the bearer token, model
credential, prompt, response text, or trace payload.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SmokeResult(TypedDict):
    run_id: str
    session_id: str
    status: str
    elapsed_seconds: float
    model_route: str


def sanitize_result(
    *,
    run_id: str,
    session_id: str,
    status: str,
    elapsed_seconds: float,
    model_route: str,
) -> SmokeResult:
    """Return the complete allow-list of fields safe to print."""
    return {
        "run_id": run_id,
        "session_id": session_id,
        "status": status,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "model_route": model_route,
    }


def _request_json(
    url: str,
    *,
    token: str,
    timeout: float,
    method: str = "GET",
    body: dict[str, object] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit smoke target
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("Run API returned a non-object response")
    return value


def _request_text(url: str, *, token: str, timeout: float) -> str:
    request = Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - explicit smoke target
        return response.read().decode("utf-8")


def _completed_content(events: str) -> str:
    current_event = ""
    for line in events.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif current_event == "run.completed" and line.startswith("data: "):
            value = json.loads(line.removeprefix("data: "))
            if isinstance(value, dict) and isinstance(value.get("content"), str):
                return value["content"].strip()
    return ""


def run_smoke() -> SmokeResult:
    base_url = os.environ.get("RUN_CHAT_BASE_URL", "http://127.0.0.1:18080").rstrip("/")
    tenant_id = os.environ["RUN_CHAT_TENANT_ID"]
    token = os.environ["RUN_CHAT_AUTH_TOKEN"]
    prompt = os.environ.get("RUN_CHAT_SMOKE_PROMPT", "Reply briefly that the run path is ready.")
    timeout = float(os.environ.get("RUN_CHAT_SMOKE_TIMEOUT_SECONDS", "90"))
    if timeout <= 0:
        raise ValueError("RUN_CHAT_SMOKE_TIMEOUT_SECONDS must be positive")
    route = os.environ.get(
        "RUN_CHAT_MODEL_ROUTE",
        "/".join(
            filter(
                None,
                (
                    os.environ.get("LLM_PROVIDER", "configured"),
                    os.environ.get("LLM_MODEL", os.environ.get("DASHSCOPE_MODEL", "default")),
                ),
            )
        ),
    )
    runs_url = f"{base_url}/api/v1/tenants/{tenant_id}/runs"
    started = time.monotonic()
    created = _request_json(
        runs_url,
        token=token,
        timeout=min(timeout, 30),
        method="POST",
        body={"prompt": prompt},
        idempotency_key=f"live-smoke-{uuid.uuid4()}",
    )
    run_id = str(created.get("id", ""))
    session_id = str(created.get("session_id", ""))
    if not run_id or not session_id:
        raise RuntimeError("Run API did not return run/session identifiers")

    terminal = {"completed", "failed", "cancelled"}
    status = str(created.get("status", ""))
    deadline = started + timeout
    while status not in terminal and time.monotonic() < deadline:
        time.sleep(0.25)
        current = _request_json(
            f"{runs_url}/{run_id}",
            token=token,
            timeout=min(max(deadline - time.monotonic(), 0.1), 10),
        )
        status = str(current.get("status", ""))
    if status != "completed":
        if status not in terminal:
            raise TimeoutError("Run chat smoke timed out before a terminal status")
        raise RuntimeError(f"Run chat smoke finished with status={status}")

    remaining = min(max(deadline - time.monotonic(), 0.1), 10)
    events = _request_text(f"{runs_url}/{run_id}/events", token=token, timeout=remaining)
    if not _completed_content(events):
        raise RuntimeError("completed Run did not expose a nonempty final message")
    trace = _request_json(
        f"{runs_url}/{run_id}/trace",
        token=token,
        timeout=min(max(deadline - time.monotonic(), 0.1), 10),
    )
    if not isinstance(trace.get("items"), list) or not trace["items"]:
        raise RuntimeError("completed Run did not expose a trace")
    return sanitize_result(
        run_id=run_id,
        session_id=session_id,
        status=status,
        elapsed_seconds=time.monotonic() - started,
        model_route=route,
    )


def main() -> int:
    try:
        result = run_smoke()
    except (KeyError, ValueError, RuntimeError, TimeoutError, HTTPError, URLError) as exc:
        # The exception may include a URL/status but never the request headers or body.
        print(json.dumps({"status": "error", "error": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
