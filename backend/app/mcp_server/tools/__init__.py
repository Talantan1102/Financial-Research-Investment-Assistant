"""MCP tool adapter modules.

Each sub-module exports:
  TOOL_DEF: mcp.types.Tool  — metadata used by build_server() list_tools handler
  handle(args: dict) -> list[TextContent]  — called by build_server() call_tool handler

build_server() (in server.py) aggregates all TOOL_DEFs into ONE @list_tools handler
and dispatches by name via ONE @call_tool handler, because the MCP SDK only keeps
the last registered handler per request type.
"""
