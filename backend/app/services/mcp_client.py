"""MCPClient — thin wrapper over mcp.ClientSession + stdio_client.

Lifecycle:
  - launch local mcp_server.py as subprocess via stdio_client
  - on shutdown, terminate subprocess
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    @classmethod
    @asynccontextmanager
    async def from_subprocess(
        cls,
        server_module: str = "app.mcp_server.server",
        profile: str = "chat_tools",
    ) -> AsyncIterator[MCPClient]:
        """Launch MCP server subprocess via stdio for the given profile.

        Plan 4 added `profile` (default 'chat_tools' for PR #39 backward compat).
        Memory tools are exposed by passing `profile='memory'`; the subprocess
        loads only that tool registry.
        """
        # Ensure subprocess can find app.* modules — backend/ must be in PYTHONPATH
        backend_path = Path(__file__).parent.parent.parent  # backend/
        env = os.environ.copy()
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{backend_path}{os.pathsep}{existing_pp}" if existing_pp else str(backend_path)
        )

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", server_module, "--profile", profile],
            env=env,
        )
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield cls(session)

    async def list_tools(self) -> list[dict[str, Any]]:
        resp = await self._session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in resp.tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from mcp.types import TextContent

        resp = await self._session.call_tool(name, args)
        # MCP returns list of content; we expect first to be TextContent with JSON
        first = resp.content[0] if resp.content else None
        text = first.text if isinstance(first, TextContent) else "{}"
        return json.loads(text)
