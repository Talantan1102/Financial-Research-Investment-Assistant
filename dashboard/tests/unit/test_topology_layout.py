"""Plan 3 Task 1 — topology_layout 单测。"""

from __future__ import annotations

from dashboard.derive.topology_layout import (
    CONNECTIONS,
    MODULES,
    connection_endpoints,
    layout_with_progress,
)


def test_modules_have_all_7_dims() -> None:
    ids = {m.dim_id for m in MODULES}
    assert ids == {
        "execution",
        "tool",
        "context",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    }


def test_connections_use_valid_ids() -> None:
    valid_ids = {m.dim_id for m in MODULES}
    for c in CONNECTIONS:
        assert c.from_id in valid_ids
        assert c.to_id in valid_ids


def test_connections_have_3_types() -> None:
    types = {c.type for c in CONNECTIONS}
    assert types == {"cross_cut", "runtime", "bypass"}


def test_layout_with_progress_returns_7() -> None:
    fake_layers = [
        {"id": dim_id, "lit": 3, "wip": 1, "todo": 5, "total": 9}
        for dim_id in [
            "execution",
            "tool",
            "context",
            "lifecycle",
            "observability",
            "verification",
            "governance",
        ]
    ]
    out = layout_with_progress(fake_layers)
    assert len(out) == 7
    for m in out:
        assert m.lit == 3
        assert m.pct == int(3 / 9 * 100)


def test_layout_handles_missing_dim() -> None:
    fake_layers = [{"id": "execution", "lit": 1, "wip": 0, "todo": 0, "total": 1}]
    out = layout_with_progress(fake_layers)
    by_id = {m.dim_id: m for m in out}
    assert by_id["governance"].total == 0
    assert by_id["execution"].lit == 1


def test_connection_endpoints_no_dangling() -> None:
    fake_layers = [
        {"id": dim_id, "lit": 0, "wip": 0, "todo": 0, "total": 0}
        for dim_id in [
            "execution",
            "tool",
            "context",
            "lifecycle",
            "observability",
            "verification",
            "governance",
        ]
    ]
    progress = layout_with_progress(fake_layers)
    by_id = {m.dim_id: m for m in progress}
    endpoints = connection_endpoints(by_id)
    assert len(endpoints) == len(CONNECTIONS)
    for _, (ax, ay), (bx, by) in endpoints:
        assert 0 <= ax <= 600
        assert 0 <= ay <= 320
        assert 0 <= bx <= 600
        assert 0 <= by <= 320
