from typing import Any

from pydantic import BaseModel, Field


class WebSearchRequest(BaseModel):
    """Web搜索请求模型"""

    query: str = Field(..., description="搜索查询文本")
    gl: str = Field("us", description="Google国家代码（例如：us, cn, jp等）")
    hl: str = Field("en", description="语言代码（例如：en, zh-cn, ja等）")
    autocorrect: bool = Field(True, description="是否启用自动纠错")
    page: int = Field(1, description="搜索结果页码")
    search_type: str = Field("search", description="搜索类型（search, news, images等）")


class SearchResultItem(BaseModel):
    """搜索结果项模型"""

    type: str
    title: str | None = None
    link: str | None = None
    snippet: str | None = None
    position: int | None = None
    description: str | None = None
    source: str | None = None
    attributes: dict[str, Any] | None = None
    question: str | None = None
    queries: list[str] | None = None


class WebSearchResponse(BaseModel):
    """Web搜索响应模型"""

    success: bool
    message: str | None = None
    query: str
    results: list[SearchResultItem] = []
    raw_results: dict[str, Any] | None = None
