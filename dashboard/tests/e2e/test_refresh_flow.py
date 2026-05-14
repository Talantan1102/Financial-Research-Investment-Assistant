"""Optional Playwright e2e tests for Harness Board.

Skipped automatically when playwright is not installed.
Install to run:
    uv add playwright pytest-playwright --optional dev
    uv run playwright install chromium
Then run:
    uv run pytest -m e2e dashboard/tests/e2e/ -v
"""

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import Page  # noqa: E402

pytestmark = pytest.mark.e2e

BASE_URL = "http://localhost:8910"


def test_refresh_flow(page: Page) -> None:
    """/ 首页加载 + chip 可见 + GET /refresh 触发后返回 200。"""
    page.goto(BASE_URL)
    page.wait_for_selector(".chip", timeout=5000)
    chips = page.locator(".chip")
    assert chips.count() > 0, "首页应含 ≥1 chip"

    resp = page.request.get(f"{BASE_URL}/refresh")
    assert resp.status == 200, f"GET /refresh 应返回 200,得到 {resp.status}"


def test_overview_has_enough_nodes(page: Page) -> None:
    """/overview 图谱节点 ≥35 (seed 有 35+ DeepCard)。"""
    import json

    resp = page.request.get(f"{BASE_URL}/api/overview/graph.json")
    assert resp.status == 200, f"/api/overview/graph.json 应返回 200,得到 {resp.status}"
    data = json.loads(resp.body())
    nodes = [
        el for el in data.get("elements", []) if "position" in el or el.get("group") == "nodes"
    ]
    # fallback: count any element with data.id present (cytoscape format)
    if not nodes:
        nodes = [
            el
            for el in data.get("elements", [])
            if "data" in el and "source" not in el.get("data", {})
        ]
    assert len(nodes) >= 35, f"overview 图谱应含 ≥35 节点,实际 {len(nodes)}"
