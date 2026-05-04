"""TushareClient — pure async HTTP transport for tushare Pro API.

No business logic, no cache, no rate limit. Returns pd.DataFrame.

Default base_url matches cassette recording host so VCR can replay
without env override (memory feedback_cassette_host_in_match_on).
"""

from __future__ import annotations

from typing import Any

import httpx
import pandas as pd


class TushareError(RuntimeError):
    """Raised when tushare API returns code != 0."""


class TushareNetworkError(TushareError):
    """Raised when a network-level error occurs (DNS / TCP / TLS / timeout).

    Always chained from the original httpx exception via `raise ... from`.
    Allows service layer to distinguish:
      - TushareError       → tushare app error (code != 0)
      - TushareNetworkError → network down / unreachable (subclass of TushareError)
    """


class TushareClient:
    def __init__(
        self,
        token: str,
        base_url: str = "http://api.tushare.pro",
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must not be empty")
        self._token = token
        self.base_url = base_url
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    async def call(
        self,
        api_name: str,
        params: dict[str, Any],
        fields: str | None = None,
    ) -> pd.DataFrame:
        body: dict[str, Any] = {
            "api_name": api_name,
            "token": self._token,
            "params": params,
        }
        if fields is not None:
            body["fields"] = fields

        try:
            resp = await self._client.post(self.base_url, json=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TushareNetworkError(f"network error calling {api_name}: {exc}") from exc

        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            raise TushareError(
                f"tushare api {api_name} failed: code={code} msg={payload.get('msg')!r}"
            )

        data = payload.get("data") or {}
        cols = data.get("fields") or []
        rows = data.get("items") or []
        return pd.DataFrame(rows, columns=cols)

    async def aclose(self) -> None:
        await self._client.aclose()
