"""Shared pydantic schemas."""
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class Framework(str, Enum):
    SOC2 = "SOC2"
    ISO27001 = "ISO27001"
    GDPR = "GDPR"
    HIPAA = "HIPAA"
    OTHER = "OTHER"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GapStatus(str, Enum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


class ControlSpec(BaseModel):
    """Structured-output schema enforced via Claude tool_use during extraction."""

    title: str = Field(..., max_length=512)
    description: str
    framework: Framework
    risk_domain: str = Field(..., max_length=128)
    severity: Severity
    source_chunk_id: str
    source_quote: str

    model_config = {"json_schema_extra": {"required": list(__annotations__.keys())}}


class Citation(BaseModel):
    chunk_id: str
    document_id: UUID | None = None
    document_name: str | None = None
    framework: Framework | None = None
    excerpt: str | None = None
    score: float | None = None
    control_id: UUID | None = None


class TimestampedModel(BaseModel):
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
