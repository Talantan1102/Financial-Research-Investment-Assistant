"""Minimal real FastAPI surface for isolated run-control acceptance tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, status
from sqlalchemy import text

from app.core.async_database import build_async_database
from app.core.security import decode_token
from app.router.auth_router import get_current_user_required
from app.router.runs import router as runs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine, factory = build_async_database()
    app.state.db_async_engine = engine
    app.state.async_session_factory = factory
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Run Control API", lifespan=lifespan)
app.include_router(runs_router)


async def _run_control_actor(authorization: str | None = Header(default=None)) -> SimpleNamespace:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = decode_token(authorization.removeprefix("Bearer ").strip())
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    return SimpleNamespace(id=UUID(token.user_id), is_active=True)


app.dependency_overrides[get_current_user_required] = _run_control_actor


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    async with request.app.state.async_session_factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}
