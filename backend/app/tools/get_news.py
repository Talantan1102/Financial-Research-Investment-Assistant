"""get_news Tool — uses BochaService Protocol for news search."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.bocha_factory import BochaService
from app.tools.base import Tool, ToolError


class NewsArgs(BaseModel):
    ts_code: str | None = None
    n: int = Field(default=5, ge=1, le=20)
    days_back: int = Field(default=7, ge=1, le=90)


class GetNewsTool(Tool):
    name = "get_news"
    description = "获取最近的财经资讯(可指定股票或大盘),走 Bocha 搜索"
    args_schema = NewsArgs

    def __init__(self, bocha: BochaService) -> None:
        self._bocha = bocha

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, NewsArgs):
            raise ToolError(f"args must be NewsArgs, got {type(args).__name__}")
        # Build query: add ts_code if specified, plus "最近新闻" keyword
        parts: list[str] = []
        if args.ts_code:
            parts.append(args.ts_code)
        parts.append("最近新闻")
        query = " ".join(parts)
        return await self._bocha.search(query=query, count=args.n)
