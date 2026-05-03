"""Adapter wrapping legacy MockTushareService into TushareService Protocol shape.

Lazy import to avoid app/service/__init__.py legacy import chain at module load.
The inner MockTushareService instance is built on first method call (lazy), so
constructing LegacyMockTushareAdapter does NOT instantiate LLMService. This
allows unit tests (LLM_MODE=none guard) to call build_tushare_service() and do
isinstance checks without triggering the LLM_MODE=none RuntimeError.

Notes:
- MockTushareService.__init__ requires an LLMService instance; we build one
  via build_llm_service_from_env() on first use.
- aclose() is a no-op: legacy MockTushareService holds no network connections
  or file handles that require explicit cleanup.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

import pandas as pd


class LegacyMockTushareAdapter:
    """Wraps legacy MockTushareService to satisfy TushareService Protocol.

    Delegates each Protocol method to the corresponding generate_* method
    on the inner legacy mock instance. The inner instance is created lazily
    on first method call to avoid LLMService construction at build time.
    """

    def __init__(self) -> None:
        self._inner: Any = None  # lazy; built on first use via _ensure_inner()

    def _ensure_inner(self) -> Any:
        """Build MockTushareService on first call (lazy initialization)."""
        if self._inner is not None:
            return self._inner

        # Build LLMService — MockTushareService.__init__ requires it.
        from app.services.openai_client import build_llm_service_from_env

        llm = build_llm_service_from_env()

        # Load legacy module directly to avoid app/service/__init__.py chain.
        path = Path(__file__).resolve().parents[1] / "service" / "mock_tushare_service.py"
        spec = spec_from_file_location("_mock_tushare_module", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        self._inner = module.MockTushareService(llm=llm)
        return self._inner

    async def get_daily(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return await self._ensure_inner().generate_daily_data(
            ts_code=ts_code, start_date=start, end_date=end
        )

    async def get_income(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        return await self._ensure_inner().generate_income(ts_code=ts_code)

    async def get_fina_indicator(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_fina_indicator(ts_code=ts_code)

    async def get_balance_sheet(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        # Delegates to existing LLM-based generate_balance_sheet (accepts ts_code: str | None).
        return await self._ensure_inner().generate_balance_sheet(ts_code=ts_code, end_date=end_date)

    async def get_cashflow(self, *, ts_code: str, end_date: str | None = None) -> pd.DataFrame:
        return await self._ensure_inner().generate_cashflow(ts_code=ts_code, end_date=end_date)

    async def get_stk_holdernumber(
        self, *, ts_code: str, end_date: str | None = None
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_stk_holdernumber(
            ts_code=ts_code, end_date=end_date
        )

    async def get_disclosure_date(
        self, *, ts_code: str | None, start: str, end: str
    ) -> pd.DataFrame:
        return await self._ensure_inner().generate_disclosure_date(
            ts_code=ts_code, start=start, end=end
        )

    async def get_anns(self, *, ts_code: str, start: str, end: str) -> pd.DataFrame:
        return await self._ensure_inner().generate_anns(ts_code=ts_code, start=start, end=end)

    async def aclose(self) -> None:
        """No-op: legacy MockTushareService has no connections to close."""
        pass
