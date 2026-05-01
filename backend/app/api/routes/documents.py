"""Document upload + listing endpoints."""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import get_settings
from app.db.models import Document, DocumentStatus
from app.logging_config import get_logger
from app.schemas.documents import (
    DocumentList,
    DocumentRead,
    DocumentUploadResponse,
)
from app.services.extraction_runner import run_pipeline

router = APIRouter()
log = get_logger(__name__)
_settings = get_settings()


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile,
    session: AsyncSession = Depends(db_session),
) -> DocumentUploadResponse:
    if not file.filename:
        raise HTTPException(400, detail="filename required")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(400, detail=f"Unsupported file type: {suffix}")

    document_id = uuid4()
    _settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    target_path = _settings.uploads_dir / f"{document_id}{suffix}"
    with target_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    document = Document(
        id=document_id,
        name=file.filename,
        source_path=str(target_path),
        status=DocumentStatus.UPLOADED,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    background.add_task(run_pipeline, document_id, target_path)
    log.info("documents.upload_accepted", id=str(document_id), name=file.filename)

    return DocumentUploadResponse(
        document=DocumentRead.model_validate(document),
        extraction_started=True,
    )


@router.get("", response_model=DocumentList)
async def list_documents(session: AsyncSession = Depends(db_session)) -> DocumentList:
    rows = (
        await session.execute(select(Document).order_by(Document.created_at.desc()))
    ).scalars().all()
    items = [DocumentRead.model_validate(r) for r in rows]
    return DocumentList(items=items, total=len(items))


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID, session: AsyncSession = Depends(db_session)
) -> DocumentRead:
    row = (
        await session.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Document not found")
    return DocumentRead.model_validate(row)
