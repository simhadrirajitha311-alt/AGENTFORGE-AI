import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("agentforge-local-test")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(
        name="echo",
        description="Return the supplied text for local adapter tests",
        inputSchema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "echo":
        raise ValueError("Unknown test tool")
    return [TextContent(type="text", text=arguments["text"])]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())