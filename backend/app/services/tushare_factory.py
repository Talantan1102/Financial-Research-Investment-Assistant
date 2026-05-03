"""tushare factory — env-driven mock/real switch.

Sibling to bocha_factory / kb_factory(8th application of Protocol pattern).
"""

from __future__ import annotations

import os
from pathlib import Path

from app.services.rate_limiter import RateLimiter
from app.services.tushare_cache import TushareCache
from app.services.tushare_client import TushareClient
from app.services.tushare_service import RealTushareService, TushareService

_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "tushare_cache.sqlite"


def build_tushare_service() -> TushareService:
    """Pick TushareService impl per env:
    - TUSHARE_MODE unset or "mock" → MockTushareAdapter (Task 4 will install)
    - TUSHARE_MODE = "real" → RealTushareService(httpx, tushare Pro)
    """
    mode = os.environ.get("TUSHARE_MODE", "mock").lower()
    if mode == "mock":
        # Task 4 installs LegacyMockTushareAdapter; for now import lazily
        from app.services.tushare_mock_adapter import LegacyMockTushareAdapter

        return LegacyMockTushareAdapter()
    if mode == "real":
        if "TUSHARE_TOKEN" not in os.environ:
            raise KeyError("TUSHARE_TOKEN required when TUSHARE_MODE=real")
        client = TushareClient(token=os.environ["TUSHARE_TOKEN"])
        cache = TushareCache(db_path=_CACHE_PATH)
        return RealTushareService(
            client=client,
            cache=cache,
            rate_limiter=RateLimiter(max_calls=400, window_s=60.0),
        )
    raise ValueError(f"TUSHARE_MODE must be 'mock' or 'real', got {mode!r}")
