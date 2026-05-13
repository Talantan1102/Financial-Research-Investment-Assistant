"""SSE /refresh endpoint L1 集成 — 事件流验证 + milvus 降级守护。"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 SSE test 用独立 sqlite + 禁 milvus / embedding env。"""
    monkeypatch.setattr("dashboard.server.DB_PATH", tmp_path / "board.db")
    monkeypatch.delenv("HARNESS_BOARD_MILVUS_HOST", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def _parse_sse(body: str) -> list[tuple[str, str]]:
    """解析 SSE body 为 [(event, data_json), ...]。"""
    out: list[tuple[str, str]] = []
    current_event = ""
    current_data: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            if current_event:
                out.append((current_event, "\n".join(current_data)))
                current_data = []
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:") :].strip())
        elif line == "" and current_event:
            out.append((current_event, "\n".join(current_data)))
            current_event = ""
            current_data = []
    if current_event:
        out.append((current_event, "\n".join(current_data)))
    return out


def test_refresh_sse_returns_event_stream_with_done() -> None:
    """SSE 流至少 ≥ 11 event(5 step × 2 + 1 done)。"""
    import json

    from dashboard.server import app

    with TestClient(app) as client, client.stream("POST", "/refresh") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())

    events = _parse_sse(body)
    step_events = [e for e in events if e[0] == "step"]
    done_events = [e for e in events if e[0] == "done"]
    assert len(step_events) >= 10  # 5 × (running + done|skip|error)
    assert len(done_events) == 1

    done_payload = json.loads(done_events[0][1])
    assert "total_ms" in done_payload
    assert "steps_summary" in done_payload
    assert done_payload["steps_summary"]["error"] == 0


def test_refresh_sse_milvus_skip_does_not_block_snapshot() -> None:
    """env 未设 milvus → milvus_reindex skip + snapshot_finalize 仍 done。"""
    import json

    from dashboard.server import app

    with TestClient(app) as client, client.stream("POST", "/refresh") as r:
        body = "".join(chunk.decode("utf-8") for chunk in r.iter_bytes())

    events = _parse_sse(body)
    step_data = [json.loads(d) for ev, d in events if ev == "step"]
    milvus_done = [d for d in step_data if d["step"] == "milvus_reindex" and d["status"] == "skip"]
    snapshot_done = [
        d for d in step_data if d["step"] == "snapshot_finalize" and d["status"] == "done"
    ]
    assert len(milvus_done) == 1
    assert "milvus disabled" in milvus_done[0]["detail"].lower()
    assert len(snapshot_done) == 1
