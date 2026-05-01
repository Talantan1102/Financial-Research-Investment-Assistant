"""BochaService Protocol + factory.

Tools (WebSearchTool, GetNewsTool) depend on the Protocol, not on a
concrete class. The factory build_bocha_service_from_env() picks
MockBochaService (legacy mock) or BochaClient (real) based on
BOCHA_MODE env var.

For backward compatibility with v0/v0.5 MockBochaService.generate_search_results(...)
signature, a thin _MockBochaAdapter wraps it to expose .search() shape.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from app.services.bocha_client import BochaClient


@runtime_checkable
class BochaService(Protocol):
    """Common interface for MockBochaService + BochaClient (search-only).

    Returns dict shape {"items": [...]} with normalized fields per Task 3.
    """

    async def search(self, *, query: str, count: int) -> dict[str, Any]: ...


class _MockBochaAdapter:
    """Wraps legacy MockBochaService.generate_search_results into BochaService.search shape."""

    def __init__(self) -> None:
        # Lazy import to avoid app/service/__init__.py legacy import chain at module load
        from importlib.util import module_from_spec, spec_from_file_location
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "service" / "mock_bocha_service.py"
        spec = spec_from_file_location("_mock_bocha_module", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        # MockBochaService.__init__ takes no args — uses LLMConfig() internally
        self._inner = module.MockBochaService()

    async def search(self, *, query: str, count: int) -> dict[str, Any]:
        # MockBochaService default search_type="news" (v0.5 Task 2 verified)
        result = await self._inner.generate_search_results(
            query=query, search_type="news", count=count
        )
        if isinstance(result, dict) and "items" in result:
            return result
        # Some legacy paths return list directly
        return {"items": result if isinstance(result, list) else []}


def build_bocha_service_from_env() -> BochaService:
    """Pick BochaService impl per env:
    - BOCHA_MODE unset or "mock" → _MockBochaAdapter (LLM-driven mock)
    - BOCHA_MODE = "real" → BochaClient (httpx, Bocha API)
    Anything else raises ValueError.
    """
    mode = os.environ.get("BOCHA_MODE", "mock").lower()
    if mode == "mock":
        return _MockBochaAdapter()
    if mode == "real":
        if "BOCHA_API_KEY" not in os.environ:
            raise KeyError("BOCHA_API_KEY required when BOCHA_MODE=real")
        base_url = os.environ.get("BOCHA_BASE_URL", "https://api.bochaai.com/v1/web-search")
        from pathlib import Path

        from app.services.circuit_breaker import CircuitBreaker
        from app.services.cost_budget import CostBudget
        from app.services.quota_counter import QuotaCounter
        from app.services.rate_limiter import RateLimiter
        from app.services.reliable_bocha_service import ReliableBochaService

        client = BochaClient(api_key=os.environ["BOCHA_API_KEY"], base_url=base_url)
        return ReliableBochaService(
            inner=client,
            rate_limiter=RateLimiter(max_calls=60, window_s=60.0),
            circuit_breaker=CircuitBreaker(failure_threshold=5, cooldown_s=30.0),
            quota_counter=QuotaCounter(
                db_path=Path("backend/data/eval.sqlite"),
                name="bocha_search_monthly",
                monthly_limit=1000,
            ),
            cost_budget=CostBudget(limit_cny=20.0),
            per_call_cost_cny=0.02,
            max_retries=3,
        )
    raise ValueError(f"BOCHA_MODE must be 'mock' or 'real', got {mode!r}")
