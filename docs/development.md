# Development

Tested in the project workspace with Python 3.14.2; the supported range is Python 3.12 or newer. CI exercises Python 3.12 and 3.13. Install with `python -m pip install -e ".[dev]"`, run `ruff check app tests scripts`, then `pytest --cov=app`.

Tests use a deterministic offline provider. The MCP test launches `scripts/mock_mcp_server.py` locally over stdio. No paid API or external network is required after dependency installation.

The SQLite store is initialized on app startup. Set `AGENTFORGE_DATABASE_PATH` to a writable database path. Tests use temporary databases. Keep generated database files and credentials out of version control.

For the optional Anthropic adapter, set `AGENTFORGE_LLM_PROVIDER=anthropic` and provide `ANTHROPIC_API_KEY` in the process environment. Requests use a 30-second timeout and one SDK retry. The mock provider is the default.

MCP client usage is deliberately opt-in in application code. Use `MCPAdapter.connect_stdio(command, args, allowed_tools)` only for an administrator-configured trusted server, review discovered schemas, and call `register_tools` with the explicitly approved discovered tool list. MCP-adapted tools are marked approval-required. Never expose server command configuration to ordinary API callers.