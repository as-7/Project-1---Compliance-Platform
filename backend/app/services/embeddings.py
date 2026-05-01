"""Embedding model — local sentence-transformers.

Loaded lazily on first use to avoid blocking app startup.
Encoding is CPU-bound, so we run it via asyncio.to_thread to keep
the event loop free.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import get_settings
from app.logging_config import get_logger

log = get_logger(__name__)


@lru_cache
def _model() -> SentenceTransformer:
    name = get_settings().embedding_model
    log.info("embeddings.load", model=name)
    m = SentenceTransformer(name)
    log.info("embeddings.loaded", model=name, dim=m.get_sentence_embedding_dimension())
    return m


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns list of float vectors."""
    if not texts:
        return []

    def _do() -> list[list[float]]:
        vectors = _model().encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]

    return await asyncio.to_thread(_do)


async def embed_one(text: str) -> list[float]:
    return (await embed_texts([text]))[0]


def expected_dim() -> int:
    return get_settings().embedding_dim
