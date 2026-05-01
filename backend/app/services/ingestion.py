"""Document ingestion pipeline: load → chunk → embed → store in Chroma."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus
from app.logging_config import get_logger
from app.services.chroma_client import add_chunks, delete_document
from app.services.chunker import chunk_document

log = get_logger(__name__)


def _read_pdf(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    pages = [p.extract_text() or "" for p in reader.pages]
    return ("\n\n".join(pages), len(pages))


def _read_text(path: Path) -> tuple[str, int]:
    return (path.read_text(encoding="utf-8", errors="ignore"), 1)


def _load(path: Path) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix in {".txt", ".md", ".markdown"}:
        return _read_text(path)
    raise ValueError(f"Unsupported document type: {suffix}")


async def ingest_document(
    session: AsyncSession,
    *,
    document_id: UUID,
    file_path: Path,
) -> dict[str, Any]:
    """Ingest a single uploaded document. Updates Document status in-place."""
    log.info("ingest.start", document_id=str(document_id), path=str(file_path))

    document = (await session.execute(select(Document).where(Document.id == document_id))).scalar_one()
    document.status = DocumentStatus.INGESTING
    await session.commit()

    try:
        text, page_count = _load(file_path)
        chunks = chunk_document(text, document_id=str(document_id))
        if not chunks:
            raise RuntimeError("No chunks produced")

        # Replace any prior embeddings for this document_id (idempotent re-ingest).
        await delete_document(str(document_id))

        await add_chunks(
            chunk_ids=[c.chunk_id for c in chunks],
            texts=[c.text for c in chunks],
            metadatas=[
                {
                    "document_id": str(document_id),
                    "document_name": document.name,
                    "section": c.section or "",
                    "order": c.order,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                }
                for c in chunks
            ],
        )

        document.page_count = page_count
        document.chunk_count = len(chunks)
        document.status = DocumentStatus.READY
        document.error_message = None
        await session.commit()
        log.info(
            "ingest.done",
            document_id=str(document_id),
            chunks=len(chunks),
            pages=page_count,
        )
        return {"chunks": len(chunks), "pages": page_count}

    except Exception as exc:
        document.status = DocumentStatus.FAILED
        document.error_message = str(exc)
        await session.commit()
        log.error("ingest.failed", document_id=str(document_id), error=str(exc))
        raise
