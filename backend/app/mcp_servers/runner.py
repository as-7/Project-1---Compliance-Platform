"""Boot both MCP servers as background tasks alongside the FastAPI app.

We use streamable-HTTP transport so external clients (and the n8n container)
can also call the MCP servers if needed.
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.logging_config import get_logger
from app.mcp_servers.control_registry import mcp as control_registry_mcp
from app.mcp_servers.document_store import mcp as document_store_mcp

log = get_logger(__name__)


async def _serve(server: Any, port: int, label: str) -> None:
    log.info("mcp.start", server=label, port=port)
    try:
        await server.run_async(transport="streamable-http", host="0.0.0.0", port=port)
    except asyncio.CancelledError:
        log.info("mcp.cancelled", server=label)
        raise
    except Exception as exc:
        log.error("mcp.crashed", server=label, error=str(exc))
        raise


async def start_mcp_servers() -> list[asyncio.Task]:
    s = get_settings()
    return [
        asyncio.create_task(
            _serve(control_registry_mcp, s.mcp_control_registry_port, "control-registry"),
            name="mcp-control-registry",
        ),
        asyncio.create_task(
            _serve(document_store_mcp, s.mcp_document_store_port, "document-store"),
            name="mcp-document-store",
        ),
    ]


async def stop_mcp_servers(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        if not t.done():
            t.cancel()
    for t in tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
