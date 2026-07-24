from __future__ import annotations

from app.processes.run_api import app


def test_minimal_run_api_exposes_only_read_identity_preflight_routes() -> None:
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in app.routes
        if route.path in {"/auth/me", "/api/v1/tenants"}
    }

    assert methods_by_path == {
        "/auth/me": {"GET"},
        "/api/v1/tenants": {"GET"},
    }
