from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    INGESTING = "INGESTING"
    EXTRACTING = "EXTRACTING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentRead(BaseModel):
    id: UUID
    name: str
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int


class DocumentUploadResponse(BaseModel):
    document: DocumentRead
    extraction_started: bool
