# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

# Document router package
# TODO(v0 plan Task 11): replaced by app.router.chat
# from .chat_router import router as chat_router
from .document_router import router as document_router
from .research_router import router as research_router
from .search_router import router as search_router

__all__ = ["document_router", "search_router", "research_router"]
