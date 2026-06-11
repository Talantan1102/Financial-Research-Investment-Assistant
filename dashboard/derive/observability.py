"""看板实时拉后端聚合 API(stdlib urllib,无新依赖)。"""

from __future__ import annotations

import json
import urllib.request


def load_aggregates(backend_url: str, window: str = "7d") -> dict:
    """GET 后端 chatloop 聚合 API,返回解析后的 dict。失败抛异常(handler 负责降级)。"""
    url = (
        f"{backend_url.rstrip('/')}/api/v0/observability/chatloop/aggregates?window={window}"
    )
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — 内部固定后端
        return json.loads(resp.read().decode("utf-8"))
