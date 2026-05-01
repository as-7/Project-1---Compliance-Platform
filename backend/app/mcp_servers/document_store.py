"""MCP Server 2 — Document Store.

Exposes Tools to search the regulatory document corpus (semantic search over
Chroma), retrieve specific chunks, and list ingested documents. Exposes a
Resource that lists the current document inventory.

Agents must reach the regulatory corpus only through this server.
"""
import json
from typing import Any
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import Document
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.services import chroma_client

log = get_logger(__name__)

mcp = FastMCP(name="document-store", version="0.1.0")


class SearchInput(BaseModel):
    query: str
    top_k: int = Field(5, ge=1, le=25)
    document_id: UUID | None = None


class GetChunkInput(BaseModel):
    chunk_id: str


class ListChunksInput(BaseModel):
    document_id: UUID


@mcp.tool()
async def search_documents(payload: SearchInput) -> list[dict[str, Any]]:
    """Semantic search over ingested regulatory documents."""
    where = {"document_id": str(payload.document_id)} if payload.document_id else None
    hits = await chroma_client.query(
        query_text=payload.query, top_k=payload.top_k, where=where
    )
    return hits


@mcp.tool()
async def get_chunk(payload: GetChunkInput) -> dict[str, Any] | None:
    """Fetch a single chunk's full text and metadata by id."""
    return await chroma_client.get_chunk(payload.chunk_id)


@mcp.tool()
async def list_chunks(payload: ListChunksInput) -> list[dict[str, Any]]:
    """List every chunk for a given document, in order."""
    where = {"document_id": str(payload.document_id)}

    def _do() -> dict[str, Any]:
        return chroma_client._collection().get(  # noqa: SLF001
            where=where, include=["documents", "metadatas"]
        )

    import asyncio

    raw = await asyncio.to_thread(_do)
    out: list[dict[str, Any]] = []
    for cid, doc, meta in zip(
        raw.get("ids") or [],
        raw.get("documents") or [],
        raw.get("metadatas") or [],
        strict=True,
    ):
        out.append({"chunk_id": cid, "text": doc, "metadata": meta or {}})
    out.sort(key=lambda x: x["metadata"].get("order", 0))
    return out


@mcp.tool()
async def list_documents() -> list[dict[str, Any]]:
    """List documents currently ingested into the vector store."""
    async with SessionLocal() as session:
        rows = (await session.execute(select(Document))).scalars().all()
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status.value,
                "page_count": r.page_count,
                "chunk_count": r.chunk_count,
            }
            for r in rows
        ]


@mcp.resource("documents://inventory")
async def inventory_resource() -> str:
    docs = await list_documents()
    return json.dumps({"documents": docs, "total": len(docs)}, indent=2)
