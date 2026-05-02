"""KbSearchTool — wraps KbSearchService for tool registry use.

v0.5 mock 留下的 borrow-MockBochaService 路径已被替代 — KB_MODE=mock 走
MockKbSearchService(返回固定 stub),KB_MODE=real 走 Milvus。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.kb_search_service import KbSearchService
from app.tools.base import Tool, ToolError


class KbSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    collections: list[str] | None = None
    threshold: float | None = None
    filters: dict[str, Any] | None = None


class KbSearchTool(Tool):
    name = "kb_search"
    description = "搜索内部知识库(研报 / 财报 / 政策 3 类 corpus,通过 KB_MODE 切换 mock|real)"
    args_schema = KbSearchArgs

    def __init__(self, kb_service: KbSearchService) -> None:
        self._kb = kb_service

    async def run(self, args: BaseModel) -> dict[str, Any]:
        if not isinstance(args, KbSearchArgs):
            raise ToolError(f"args must be KbSearchArgs, got {type(args).__name__}")
        hits = await self._kb.search(
            query=args.query,
            collections=args.collections,
            top_k=args.top_k,
            threshold=args.threshold,
            filters=args.filters,
        )
        return {
            "items": [
                {
                    "chunk_id": h.chunk_id,
                    "chunk_text": h.chunk_text,
                    "similarity": h.similarity,
                    **h.metadata,
                }
                for h in hits
            ]
        }
