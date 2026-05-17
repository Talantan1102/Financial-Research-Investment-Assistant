"""L2 e2e: 起 serve fixture + celery worker subprocess, 跑首轮对话, 验证 title 异步落库.

依赖项目 e2e fixture (serve_base_url + celery_worker_subprocess); 若 fixture 不可用则
skip。User 跑 dogfood 时手动: cd backend && uv run pytest tests/e2e/test_chat_title_e2e.py -v -m e2e

serve_base_url 约定: 测试读取 SERVE_BASE_URL 环境变量(默认 http://127.0.0.1:8000),
并 ping /health 确认 server 在线; 若不在线则 skip。
这让 CI(无 serve 进程)安静 skip, dogfood 只需先 `uv run poe serve` 再跑测试。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

# 检查 requests 是否可用
_E2E_AVAILABLE = True
try:
    import requests  # noqa: F401
except ImportError:
    _E2E_AVAILABLE = False


def _docker_available() -> bool:
    """True only if `docker` binary exists AND `docker info` returns 0."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not _E2E_AVAILABLE,
        reason="requests not installed in this env",
    ),
]


@pytest.fixture(scope="module")
def serve_base_url() -> str:
    """Return the base URL of a running serve process.

    Reads SERVE_BASE_URL env var (default http://127.0.0.1:8000).
    Pings /health; skips the whole module if server is not reachable.
    In CI (no serve process started) this skips cleanly.
    In dogfood: start `uv run poe serve` first, then run this test.
    """
    import requests

    base = os.environ.get("SERVE_BASE_URL", "http://127.0.0.1:8000")
    try:
        resp = requests.get(f"{base}/health", timeout=3)
        if resp.status_code not in (200, 404):
            pytest.skip(f"serve at {base} returned {resp.status_code} — not healthy")
    except requests.exceptions.ConnectionError:
        pytest.skip(f"serve not reachable at {base} — start `uv run poe serve` first")
    return base


def test_first_round_triggers_llm_title_generation(serve_base_url: str, celery_worker_subprocess):
    """端到端: 创建 session → 发首条 user 消息 → 等异步 task → title != '新对话'."""
    import requests

    # 1. 创建 session
    resp = requests.post(f"{serve_base_url}/api/v0/chats/", json={})
    resp.raise_for_status()
    session = resp.json()
    sid = session["id"]
    assert session["title"] == "新对话"

    # 2. 发用户消息 → 触发 chat_runner Celery task (Plan 2 enqueue path)
    #    POST /api/v0/chat with session_id + message (anonymous user, no auth needed)
    resp = requests.post(
        f"{serve_base_url}/api/v0/chat",
        json={"session_id": sid, "message": "贵州茅台最近怎么样?"},
    )
    resp.raise_for_status()

    # 3. 等 chat_runner 完成 + generate_session_title 落库 (~5-10s 总等待)
    deadline = time.time() + 30
    title = "新对话"
    while time.time() < deadline:
        resp = requests.get(f"{serve_base_url}/api/v0/chats/{sid}")
        data = resp.json()
        title = data["session"]["title"]
        if title != "新对话":
            break
        time.sleep(1)

    assert title != "新对话", f"title 没在 30s 内被异步更新, 仍为 '{title}'"
    assert len(title) <= 30, f"title 太长: {title!r}"
