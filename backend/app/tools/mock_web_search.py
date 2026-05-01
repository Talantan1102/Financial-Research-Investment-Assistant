"""mock_web_search — uses MockBochaService LLM-driven mock for v0.5.
Real Bocha API integration deferred to v0.6.

search_type is restricted to the four types MockBochaService supports:
  news / announcement / industry / report.
("general" not supported by MockBochaService; closest general-purpose
types are "news" or "industry".)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.service.mock_bocha_service import MockBochaService


class WebSearchArgs(BaseModel):
    query: str
    search_type: Literal["news", "announcement", "industry", "report"] = "news"
    count: int = Field(default=5, ge=1, le=20)


class MockWebSearchTool(Tool):
    name = "mock_web_search"
    description = "搜索网络获取最新资讯或一般信息(v0.5 mock,v0.6 真接入)"
    args_schema = WebSearchArgs

    def __init__(self, mock_bocha: MockBochaService | None = None) -> None:
        self._mock_bocha = mock_bocha

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, WebSearchArgs):
            raise ToolError(f"args must be WebSearchArgs, got {type(args).__name__}")
        if self._mock_bocha is None:
            raise ToolError("MockBochaService not injected; cannot run web_search")
        items = await self._mock_bocha.generate_search_results(
            query=args.query,
            search_type=args.search_type,
            count=args.count,
        )
        return {"items": items}
