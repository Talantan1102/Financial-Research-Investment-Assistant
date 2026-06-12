"""看板实时拉后端聚合 / 逐日 API(stdlib urllib,无新依赖)。"""

from __future__ import annotations

import json
import urllib.request


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — 内部固定后端
        return json.loads(resp.read().decode("utf-8"))


def load_aggregates(
    backend_url: str,
    window: str | None = None,
    frm: str | None = None,
    to: str | None = None,
) -> dict:
    """GET chatloop 聚合;给 frm/to 走任意范围,否则走 window(默认 7d)。"""
    base = f"{backend_url.rstrip('/')}/api/v0/observability/chatloop/aggregates"
    if frm and to:
        return _get(f"{base}?from={frm}&to={to}")
    return _get(f"{base}?window={window or '7d'}")


def load_daily(backend_url: str, frm: str, to: str) -> dict:
    """GET 逐日分桶 {days: [...]}。"""
    base = f"{backend_url.rstrip('/')}/api/v0/observability/chatloop/daily"
    return _get(f"{base}?from={frm}&to={to}")
