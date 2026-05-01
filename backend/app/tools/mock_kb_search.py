"""mock_kb_search — uses MockBochaService for KB-style search v0.5.
Real Milvus integration deferred to v0.6.

search_type "docs" not supported by MockBochaService; falls back to
"report" (research reports) as the closest approximation to internal
knowledge-base documents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from app.service.mock_bocha_service import MockBochaService


class KbSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class MockKbSearchTool(Tool):
    name = "mock_kb_search"
    description = "搜索内部知识库(v0.5 mock,v0.6 真接 Milvus)"
    args_schema = KbSearchArgs

    def __init__(self, mock_bocha: MockBochaService | None = None) -> None:
        self._mock_bocha = mock_bocha

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, KbSearchArgs):
            raise ToolError(f"args must be KbSearchArgs, got {type(args).__name__}")
        if self._mock_bocha is None:
            raise ToolError("MockBochaService not injected; cannot run kb_search")
        items = await self._mock_bocha.generate_search_results(
            query=args.query,
            search_type="report",
            count=args.top_k,
        )
        return {"items": items}
