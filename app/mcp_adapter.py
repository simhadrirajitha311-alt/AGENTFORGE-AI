import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from jsonschema import validate
from pydantic import Field, create_model

from app.tools import ToolInput, ToolRegistry, ToolSpec


class MCPAdapter:
    """Explicitly allowlisted MCP access using the official Python SDK."""

    def __init__(self, allowed_tools: set[str], timeout_seconds: float = 10):
        self.allowed_tools = allowed_tools
        self.timeout_seconds = timeout_seconds
        self.schemas: dict[str, dict[str, Any]] = {}

    async def discover(self, session: Any) -> list[dict[str, Any]]:
        response = await asyncio.wait_for(session.list_tools(), timeout=self.timeout_seconds)
        discovered = []
        for tool in response.tools:
            if tool.name in self.allowed_tools:
                self.schemas[tool.name] = tool.inputSchema
                discovered.append({"name": tool.name, "description": tool.description or "",
                                   "input_schema": tool.inputSchema})
        return discovered

    async def call(self, session: Any, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.allowed_tools:
            raise PermissionError(f"MCP tool is not approved: {name}")
        if name not in self.schemas:
            raise ValueError(f"MCP tool schema has not been discovered: {name}")
        validate(instance=arguments, schema=self.schemas[name])
        return await asyncio.wait_for(
            session.call_tool(name, arguments), timeout=self.timeout_seconds,
        )

    def register_tools(
        self, registry: ToolRegistry, command: str, args: list[str],
        discovered_tools: list[dict[str, Any]],
    ) -> None:
        for tool in discovered_tools:
            name, schema = tool["name"], tool["input_schema"]
            required = set(schema.get("required", []))
            fields = {
                key: (Any, Field(...) if key in required else Field(default=None))
                for key in schema.get("properties", {})
            }
            input_model = create_model(
                f"MCP_{name}_{uuid4().hex[:8]}", __base__=ToolInput, **fields,
            )

            def invoke(_approved_name: str = name, **arguments: Any) -> dict[str, Any]:
                return asyncio.run(self._call_stdio(command, args, _approved_name, arguments))

            output_model = create_model(
                f"MCPOutput_{uuid4().hex[:8]}",
                is_error=(bool, False),
                structured_content=(Any | None, None),
                content=(list[dict[str, Any]], Field(default_factory=list)),
            )
            registry.register(ToolSpec(
                name=name, description=tool.get("description", "Approved MCP tool"),
                input_model=input_model, handler=invoke, output_model=output_model,
                permission="mcp",
                timeout_seconds=self.timeout_seconds, approval_required=True,
            ))

    async def _call_stdio(
        self, command: str, args: list[str], name: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with self.connect_stdio(command, args, {name}, self.timeout_seconds) as (
            adapter, session, discovered,
        ):
            if name not in {tool["name"] for tool in discovered}:
                raise PermissionError(f"Configured MCP tool is not available: {name}")
            result = await adapter.call(session, name, arguments)
            return {
                "is_error": bool(getattr(result, "isError", False)),
                "structured_content": getattr(result, "structuredContent", None),
                "content": [
                    {"type": getattr(item, "type", "unknown"),
                     "text": getattr(item, "text", "")}
                    for item in getattr(result, "content", [])
                ],
            }

    @staticmethod
    @asynccontextmanager
    async def connect_stdio(command: str, args: list[str], allowed_tools: set[str], timeout_seconds: float = 10):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(command=command, args=args)
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            adapter = MCPAdapter(allowed_tools, timeout_seconds)
            tools = await adapter.discover(session)
            yield adapter, session, tools
