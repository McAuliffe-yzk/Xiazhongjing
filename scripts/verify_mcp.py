"""Verify an MCP Streamable HTTP endpoint with the official Python SDK."""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def verify(url: str) -> None:
    async with streamable_http_client(url) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            initialize = await session.initialize()
            tools = await session.list_tools()
            print(json.dumps({
                "protocolVersion": initialize.protocolVersion,
                "server": initialize.serverInfo.model_dump(),
                "tool_count": len(tools.tools),
                "tools": [tool.name for tool in tools.tools],
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(verify(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080/mcp"))
