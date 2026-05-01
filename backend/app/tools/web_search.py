"""web_search Tool — uses BochaService Protocol (mock or real per BOCHA_MODE).

v0.5 was MockWebSearchTool against MockBochaService;
v0.6 renamed + Protocol-injected for real Bocha API integration.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.bocha_factory import BochaService
from app.tools.base import Tool, ToolError


class WebSearchArgs(BaseModel):
    query: str
    search_type: Literal["news", "industry", "report"] = "news"
    count: int = Field(default=5, ge=1, le=20)


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "搜索网络获取最新资讯或一般信息(v0.6 真接 Bocha API,可通过 BOCHA_MODE=mock 切回 mock)"
    )
    args_schema = WebSearchArgs

    def __init__(self, bocha: BochaService) -> None:
        self._bocha = bocha

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, WebSearchArgs):
            raise ToolError(f"args must be WebSearchArgs, got {type(args).__name__}")
        # Real Bocha API doesn't have search_type; augment query for news
        effective_query = args.query
        if args.search_type == "news":
            effective_query = f"{args.query} 最近新闻"
        elif args.search_type == "report":
            effective_query = f"{args.query} 研报"
        return await self._bocha.search(query=effective_query, count=args.count)
