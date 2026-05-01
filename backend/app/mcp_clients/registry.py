"""MCP client registry — agents call into MCP servers via this thin wrapper.

We connect to the streamable-HTTP MCP servers exposed by the same backend
container (ports 9001, 9002). This keeps the contract clean: agents do NOT
import DB sessions or Chroma — they only call MCP tools.

Connection lifecycle:
    The first call to `client(name)` opens a persistent client session and
    caches it for the process. Cleanup happens at app shutdown via
    `close_all()`.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import Client

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)

_clients: dict[str, Client] = {}
_lock = asyncio.Lock()


def _url_for(server: str) -> str:
    s = get_settings()
    if server == "control-registry":
        return f"http://localhost:{s.mcp_control_registry_port}/mcp"
    if server == "document-store":
        return f"http://localhost:{s.mcp_document_store_port}/mcp"
    raise ValueError(f"Unknown MCP server: {server}")


async def client(server: str) -> Client:
    async with _lock:
        existing = _clients.get(server)
        if existing is not None:
            return existing
        c = Client(_url_for(server))
        await c.__aenter__()
        _clients[server] = c
        log.info("mcp_client.connected", server=server)
        return c


async def call_tool(server: str, name: str, arguments: dict[str, Any]) -> Any:
    c = await client(server)
    result = await c.call_tool(name, arguments)
    return result


async def read_resource(server: str, uri: str) -> str:
    c = await client(server)
    payload = await c.read_resource(uri)
    if isinstance(payload, list) and payload:
        first = payload[0]
        return getattr(first, "text", str(first))
    return str(payload)


async def close_all() -> None:
    for name, c in list(_clients.items()):
        try:
            await c.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        _clients.pop(name, None)
        log.info("mcp_client.closed", server=name)
