from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import Framework, GapStatus, Severity


class RegulatoryControlRead(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    description: str
    framework: Framework
    risk_domain: str
    severity: Severity
    source_chunk_id: str
    source_quote: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RegulatoryControlList(BaseModel):
    items: list[RegulatoryControlRead]
    total: int


class OrganizationControlRead(BaseModel):
    id: UUID
    code: str
    title: str
    description: str
    risk_domain: str
    owner: str | None = None
    evidence_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrganizationControlCreate(BaseModel):
    code: str
    title: str
    description: str
    risk_domain: str
    owner: str | None = None
    evidence_url: str | None = None


class OrganizationControlUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    risk_domain: str | None = None
    owner: str | None = None
    evidence_url: str | None = None


class GapMappingRead(BaseModel):
    id: UUID
    regulatory_control_id: UUID
    organization_control_id: UUID | None
    status: GapStatus
    similarity: float
    rationale: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class GapSummaryItem(BaseModel):
    framework: Framework
    severity: Severity
    covered: int
    partial: int
    missing: int


class GapSummary(BaseModel):
    by_framework: list[GapSummaryItem]
    total_regulatory_controls: int
    total_org_controls: int
    coverage_pct: float
