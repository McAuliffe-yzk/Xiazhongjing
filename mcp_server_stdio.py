"""stdio entry point for local MCP clients such as Claude Desktop."""

from mcp_server import mcp


if __name__ == "__main__":
    mcp.run(transport="stdio")
