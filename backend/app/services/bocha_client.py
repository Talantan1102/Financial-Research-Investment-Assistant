"""BochaClient — async raw httpx wrapper for Bocha Search API.

Endpoint: POST https://api.bochaai.com/v1/web-search
Auth:     Authorization: Bearer <api_key>

Response shape normalized to:
  {"items": [{"title", "url", "summary", "snippet", "site_name", "date"}, ...]}
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.bocha_errors import (
    BochaAuthError,
    BochaClientError,
    BochaNetworkError,
    BochaRateLimitError,
    BochaServerError,
)

_DEFAULT_BASE_URL = "https://api.bochaai.com/v1/web-search"
_DEFAULT_TIMEOUT_S = 15.0


class BochaClient:
    """Async client for Bocha Search API. Single-shot call, no retry / no rate limit
    (caller layers those on top via RateLimiter / CircuitBreaker / retry helper)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    async def search(self, *, query: str, count: int) -> dict[str, Any]:
        """Single web-search call. Raises one of 5 BochaError subclasses on failure.

        Returns dict with shape:
            {"items": [{"title", "url", "summary", "snippet", "site_name", "date"}, ...]}
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "summary": True, "count": count, "page": 1}

        try:
            response = await self._client.post(self._base_url, headers=headers, json=payload)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as e:
            raise BochaNetworkError(f"network error: {e}") from e
        except httpx.HTTPError as e:
            raise BochaNetworkError(f"transport error: {e}") from e

        status = response.status_code
        if status == 200:
            return _normalize(response.json())
        if status == 429:
            raise BochaRateLimitError(f"rate limit (429): {response.text[:200]}")
        if status in (401, 403):
            raise BochaAuthError(f"auth error ({status}): {response.text[:200]}")
        if 500 <= status < 600:
            raise BochaServerError(f"server error ({status}): {response.text[:200]}")
        raise BochaClientError(f"client error ({status}): {response.text[:200]}")

    async def aclose(self) -> None:
        await self._client.aclose()


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Bocha response → unified shape used by tools."""
    web_pages = raw.get("data", {}).get("webPages", {}).get("value", [])
    items: list[dict[str, Any]] = []
    for entry in web_pages:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "title": entry.get("name", ""),
                "url": entry.get("url", ""),
                "summary": entry.get("summary", "") or entry.get("snippet", ""),
                "snippet": entry.get("snippet", ""),
                "site_name": entry.get("siteName", ""),
                "date": entry.get("datePublished", ""),
            }
        )
    return {"items": items}
