# Router package — new strict routers live in submodules (app.router.chat etc.)
# Legacy routers (document_router / research_router / search_router) are imported
# directly in app_main.py via the bare `router` package (--app-dir backend).
# They are NOT re-exported here because they use bare `schemas.*` imports that
# only resolve under the old app-dir invocation, not under the `backend/` source root.

__all__: list[str] = []
