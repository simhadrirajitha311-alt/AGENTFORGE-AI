import asyncio
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

from app.mcp_adapter import MCPAdapter
from app.storage import Store
from app.tools import ToolRegistry


def test_official_mcp_sdk_local_stdio_server():
    server_script = Path(__file__).parents[1] / "scripts" / "mock_mcp_server.py"

    async def exercise():
        async with MCPAdapter.connect_stdio(
            sys.executable, [str(server_script)], {"echo"}, timeout_seconds=5,
        ) as (adapter, session, discovered):
            assert [tool["name"] for tool in discovered] == ["echo"]
            result = await adapter.call(session, "echo", {"text": "local MCP works"})
            assert result.content[0].text == "local MCP works"
            with pytest.raises(ValidationError):
                await adapter.call(session, "echo", {"unexpected": "argument"})
            with pytest.raises(PermissionError):
                await adapter.call(session, "not-approved", {})
            store = Store(Path(":memory:"))
            registry = ToolRegistry(store)
            adapter.register_tools(registry, sys.executable, [str(server_script)], discovered)
            try:
                bridged = await asyncio.to_thread(
                    registry.invoke, "echo", {"text": "registered MCP tool"},
                )
            finally:
                store.close()
            assert bridged["content"][0]["text"] == "registered MCP tool"

    asyncio.run(exercise())