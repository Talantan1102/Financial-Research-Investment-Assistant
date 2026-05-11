"""Memory MCP tools registry — Plan 4 ship.

6 tools spanning 3 tiers:
  Tier 1 (working memory write): core_memory_append / core_memory_replace
  Tier 2 (archival graph):       archival_memory_insert / archival_memory_search
                                 / archival_memory_traverse
  Tier 3 (chat history recall):  recall_memory_search

Loaded by `app.mcp_server.server.build_server(profile="memory")`.

Per shared contracts § 1, this directory is exclusively the memory profile;
PR #39 chat_tools profile lives directly in `app.mcp_server.tools.*` (one
level up).
"""

from __future__ import annotations

MEMORY_TOOL_MODULES: list[str] = [
    "app.mcp_server.tools.memory.core_memory_append",
    "app.mcp_server.tools.memory.core_memory_replace",
    "app.mcp_server.tools.memory.archival_memory_insert",
    "app.mcp_server.tools.memory.archival_memory_search",
    "app.mcp_server.tools.memory.archival_memory_traverse",
    "app.mcp_server.tools.memory.recall_memory_search",
]

__all__ = ["MEMORY_TOOL_MODULES"]
