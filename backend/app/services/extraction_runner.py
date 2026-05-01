"""Glue: kick off ingestion → extraction → gap analysis as a background task."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.agents.extraction_agent import run_extraction
from app.db.models import Document, DocumentStatus
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.services.gap_analyzer import compute_gaps, persist_decisions
from app.services.ingestion import ingest_document

log = get_logger(__name__)


async def run_pipeline(document_id: UUID, file_path: Path) -> None:
    """Full pipeline for a newly uploaded document. Errors are persisted to
    the Document row and re-raised so background-task supervision sees them."""
    async with SessionLocal() as session:
        await ingest_document(session, document_id=document_id, file_path=file_path)

    async with SessionLocal() as session:
        doc = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one()
        doc.status = DocumentStatus.EXTRACTING
        await session.commit()
        document_name = doc.name

    try:
        run = await run_extraction(document_id, document_name=document_name)
    except Exception as exc:
        log.error("pipeline.extraction_failed", document_id=str(document_id), error=str(exc))
        async with SessionLocal() as session:
            doc = (
                await session.execute(select(Document).where(Document.id == document_id))
            ).scalar_one()
            doc.status = DocumentStatus.FAILED
            doc.error_message = f"Extraction failed: {exc}"
            await session.commit()
        return

    async with SessionLocal() as session:
        decisions = await compute_gaps(session, document_id=document_id)
        await persist_decisions(session, decisions)
        doc = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one()
        doc.status = DocumentStatus.READY
        await session.commit()

    log.info(
        "pipeline.done",
        document_id=str(document_id),
        controls=len(run.extracted_controls),
        gaps=len(decisions),
    )
