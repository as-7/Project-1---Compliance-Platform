"""Chroma client wrapper.

Uses Chroma in HTTP mode (separate container) so the embeddings live in a
persistent volume and other services (e.g. MCP servers) can share state.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.logging_config import get_logger
from app.services.embeddings import embed_texts

log = get_logger(__name__)


@lru_cache
def _client() -> chromadb.HttpClient:
    s = get_settings()
    log.info("chroma.connect", host=s.chroma_host, port=s.chroma_port)
    return chromadb.HttpClient(
        host=s.chroma_host,
        port=s.chroma_port,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection():
    s = get_settings()
    client = _client()
    return client.get_or_create_collection(
        name=s.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )


async def add_chunks(
    *,
    chunk_ids: list[str],
    texts: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    if not chunk_ids:
        return
    embeds = await embed_texts(texts)

    def _do() -> None:
        _collection().upsert(
            ids=chunk_ids, embeddings=embeds, documents=texts, metadatas=metadatas
        )

    await asyncio.to_thread(_do)


async def query(
    *,
    query_text: str,
    top_k: int = 5,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    embeds = await embed_texts([query_text])

    def _do() -> dict[str, Any]:
        return _collection().query(
            query_embeddings=embeds,
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    raw = await asyncio.to_thread(_do)
    if not raw or not raw.get("ids") or not raw["ids"][0]:
        return []
    ids = raw["ids"][0]
    docs = raw["documents"][0]
    metas = raw["metadatas"][0]
    dists = raw["distances"][0]
    out: list[dict[str, Any]] = []
    for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=True):
        out.append(
            {
                "chunk_id": cid,
                "text": doc,
                "metadata": meta or {},
                "score": 1.0 - float(dist),  # cosine distance → similarity
            }
        )
    return out


async def get_chunk(chunk_id: str) -> dict[str, Any] | None:
    def _do() -> dict[str, Any]:
        return _collection().get(ids=[chunk_id], include=["documents", "metadatas"])

    raw = await asyncio.to_thread(_do)
    if not raw or not raw.get("ids"):
        return None
    return {
        "chunk_id": raw["ids"][0],
        "text": raw["documents"][0],
        "metadata": raw["metadatas"][0] or {},
    }


async def delete_document(document_id: str) -> int:
    def _do() -> int:
        existing = _collection().get(where={"document_id": document_id})
        ids = existing.get("ids") or []
        if ids:
            _collection().delete(ids=ids)
        return len(ids)

    return await asyncio.to_thread(_do)


async def list_documents() -> list[dict[str, Any]]:
    def _do() -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        result = _collection().get(include=["metadatas"])
        for meta in result.get("metadatas") or []:
            if not meta:
                continue
            doc_id = meta.get("document_id")
            if not doc_id:
                continue
            entry = out.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "document_name": meta.get("document_name"),
                    "chunk_count": 0,
                },
            )
            entry["chunk_count"] += 1
        return list(out.values())

    return await asyncio.to_thread(_do)
