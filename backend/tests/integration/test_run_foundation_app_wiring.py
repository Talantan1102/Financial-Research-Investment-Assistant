"""Production wiring checks for the Phase 1 Run foundation."""

import pytest
from app.app_main import app
from app.core.database import Base


@pytest.mark.asyncio
async def test_build_async_database_returns_shared_engine_and_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.async_database import build_async_database

    monkeypatch.setenv("POSTGRES_USER", "run_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "run_password")
    monkeypatch.setenv("POSTGRES_HOST", "run-db")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_DB", "run_control")

    engine, factory = build_async_database()
    try:
        assert factory.kw["bind"] is engine
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.username == "run_user"
        assert engine.url.host == "run-db"
        assert engine.url.port == 5544
        assert engine.url.database == "run_control"
    finally:
        await engine.dispose()


def test_production_app_registers_routes() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/tenants" in paths
    assert "/api/v1/tenants/{tenant_id}/runs" in paths
    assert "/api/v1/tenants/{tenant_id}/runs/{run_id}/events" in paths


def test_production_openapi_exposes_exactly_six_run_operations() -> None:
    expected = {
        ("post", "/api/v1/tenants/{tenant_id}/runs"),
        ("get", "/api/v1/tenants/{tenant_id}/runs/{run_id}"),
        ("get", "/api/v1/tenants/{tenant_id}/runs/{run_id}/events"),
        ("get", "/api/v1/tenants/{tenant_id}/runs/{run_id}/trace"),
        ("post", "/api/v1/tenants/{tenant_id}/runs/{run_id}/cancel"),
        ("post", "/api/v1/tenants/{tenant_id}/runs/{run_id}/resume"),
    }
    run_prefix = "/api/v1/tenants/{tenant_id}/runs"
    actual = {
        (method, path)
        for path, path_item in app.openapi()["paths"].items()
        if path.startswith(run_prefix)
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert actual == expected


def test_foundation_tables_registered() -> None:
    expected = {
        "tenants",
        "tenant_memberships",
        "tenant_audit_logs",
        "run_sessions",
        "run_messages",
        "runs",
        "run_attempts",
        "run_pauses",
        "run_events",
    }
    assert expected <= set(Base.metadata.tables)
