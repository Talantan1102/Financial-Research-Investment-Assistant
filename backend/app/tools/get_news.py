"""Tool: get_news — retrieve recent financial news items for a stock or market."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.service.mock_bocha_service import MockBochaService


class NewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = Field(default=5, ge=1)
    days_back: int = Field(default=7, ge=1)


class GetNewsTool(Tool):
    """Return recent news items relevant to a given stock (or market-wide).

    Data source: MockBochaService.generate_search_results (search_type='news').
    MockTushareService has no news endpoint; MockBochaService is the closest
    match and returns structured title/summary/url/datePublished data.

    Note: MockBochaService.__init__ reads LLMConfig directly (no DI injection),
    so it is constructed internally here rather than injected.  This is
    acceptable for the v0 mock tier; v1 will wire real Bocha via DI.
    """

    name = "get_news"
    description = (
        "Return recent news items for a given A-share (ts_code) or "
        "general market news when ts_code is omitted. n: number of items (default 5)."
    )
    args_schema = NewsArgs

    def __init__(self, mock_bocha: MockBochaService) -> None:
        self._mock_bocha = mock_bocha

    async def run(self, args: BaseModel) -> dict[str, Any]:
        validated = NewsArgs.model_validate(args.model_dump())

        # Build a query string from ts_code or fall back to general market news
        query = f"股票 {validated.ts_code} 最新新闻" if validated.ts_code else "A股市场最新财经新闻"

        freshness_map = {1: "Day", 7: "Week", 30: "Month"}
        freshness = freshness_map.get(validated.days_back, "Month")

        try:
            result = await self._mock_bocha.generate_search_results(
                query=query,
                search_type="news",
                count=validated.n,
                freshness=freshness,
            )
        except Exception as exc:
            raise ToolError(f"MockBochaService call failed: {exc}") from exc

        # Extract webPages.value list from Bocha-format response
        pages: list[dict[str, Any]] = result.get("webPages", {}).get("value", [])

        items = [
            {
                "title": page.get("name", ""),
                "summary": page.get("summary", page.get("snippet", "")),
                "url": page.get("url", ""),
                "published_at": page.get("datePublished", ""),
            }
            for page in pages[: validated.n]
        ]

        return {"items": items}
