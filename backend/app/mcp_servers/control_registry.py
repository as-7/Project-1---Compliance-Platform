"""MCP Server 1 — Control Registry.

Exposes Tools to CRUD/search the Postgres-backed control inventory and a
Resource that returns the live gap-analysis summary. Agents must reach
the control DB only through this server.
"""
import json
from typing import Any, Literal
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db.models import (
    Framework,
    GapMapping,
    GapStatus,
    OrganizationControl,
    RegulatoryControl,
    Severity,
)
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.schemas.common import ControlSpec

log = get_logger(__name__)

mcp = FastMCP(name="control-registry", version="0.1.0")


# ----------------------------------------------------------------------------
# Tool input/output models
# ----------------------------------------------------------------------------


class CreateRegulatoryControlInput(BaseModel):
    document_id: UUID
    spec: ControlSpec


class CreateRegulatoryControlOutput(BaseModel):
    id: UUID
    title: str


class SearchInput(BaseModel):
    query: str | None = None
    framework: Framework | None = None
    severity: Severity | None = None
    risk_domain: str | None = None
    limit: int = Field(50, ge=1, le=500)


class RegulatoryControlOut(BaseModel):
    id: UUID
    document_id: UUID
    title: str
    description: str
    framework: Framework
    risk_domain: str
    severity: Severity
    source_chunk_id: str
    source_quote: str

    model_config = {"from_attributes": True}


class OrganizationControlOut(BaseModel):
    id: UUID
    code: str
    title: str
    description: str
    risk_domain: str

    model_config = {"from_attributes": True}


class GapMappingInput(BaseModel):
    regulatory_control_id: UUID
    organization_control_id: UUID | None
    status: Literal["COVERED", "PARTIAL", "MISSING"]
    similarity: float = 0.0
    rationale: str | None = None


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------


@mcp.tool()
async def create_regulatory_control(payload: CreateRegulatoryControlInput) -> dict[str, Any]:
    """Persist a single extracted regulatory control to the registry."""
    async with SessionLocal() as session:
        spec = payload.spec
        row = RegulatoryControl(
            document_id=payload.document_id,
            title=spec.title,
            description=spec.description,
            framework=Framework(spec.framework.value),
            risk_domain=spec.risk_domain,
            severity=Severity(spec.severity.value),
            source_chunk_id=spec.source_chunk_id,
            source_quote=spec.source_quote,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        log.info("control_registry.created", id=str(row.id), title=row.title)
        return {"id": str(row.id), "title": row.title}


@mcp.tool()
async def search_regulatory_controls(payload: SearchInput) -> list[dict[str, Any]]:
    """Search regulatory controls by free-text + filters."""
    async with SessionLocal() as session:
        stmt = select(RegulatoryControl)
        if payload.framework:
            stmt = stmt.where(RegulatoryControl.framework == Framework(payload.framework.value))
        if payload.severity:
            stmt = stmt.where(RegulatoryControl.severity == Severity(payload.severity.value))
        if payload.risk_domain:
            stmt = stmt.where(RegulatoryControl.risk_domain.ilike(f"%{payload.risk_domain}%"))
        if payload.query:
            q = f"%{payload.query}%"
            stmt = stmt.where(
                (RegulatoryControl.title.ilike(q)) | (RegulatoryControl.description.ilike(q))
            )
        stmt = stmt.limit(payload.limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [RegulatoryControlOut.model_validate(r).model_dump(mode="json") for r in rows]


@mcp.tool()
async def search_organization_controls(payload: SearchInput) -> list[dict[str, Any]]:
    """Search the organization's existing controls."""
    async with SessionLocal() as session:
        stmt = select(OrganizationControl)
        if payload.risk_domain:
            stmt = stmt.where(OrganizationControl.risk_domain.ilike(f"%{payload.risk_domain}%"))
        if payload.query:
            q = f"%{payload.query}%"
            stmt = stmt.where(
                (OrganizationControl.title.ilike(q))
                | (OrganizationControl.description.ilike(q))
                | (OrganizationControl.code.ilike(q))
            )
        stmt = stmt.limit(payload.limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [OrganizationControlOut.model_validate(r).model_dump(mode="json") for r in rows]


@mcp.tool()
async def upsert_gap_mapping(payload: GapMappingInput) -> dict[str, Any]:
    """Record a gap-analysis decision for a regulatory control."""
    async with SessionLocal() as session:
        existing_q = select(GapMapping).where(
            GapMapping.regulatory_control_id == payload.regulatory_control_id
        )
        existing = (await session.execute(existing_q)).scalar_one_or_none()
        if existing is None:
            existing = GapMapping(regulatory_control_id=payload.regulatory_control_id)
            session.add(existing)
        existing.organization_control_id = payload.organization_control_id
        existing.status = GapStatus(payload.status)
        existing.similarity = payload.similarity
        existing.rationale = payload.rationale
        await session.commit()
        await session.refresh(existing)
        return {"id": str(existing.id), "status": existing.status.value}


@mcp.tool()
async def get_gap_summary() -> dict[str, Any]:
    """Return the same payload as the gap-summary Resource (callable variant)."""
    return await _compute_gap_summary()


# ----------------------------------------------------------------------------
# Resource: live gap summary
# ----------------------------------------------------------------------------


async def _compute_gap_summary() -> dict[str, Any]:
    async with SessionLocal() as session:
        total_reg = (await session.execute(select(func.count(RegulatoryControl.id)))).scalar_one()
        total_org = (await session.execute(select(func.count(OrganizationControl.id)))).scalar_one()
        rows = (
            await session.execute(
                select(
                    RegulatoryControl.framework,
                    RegulatoryControl.severity,
                    GapMapping.status,
                    func.count(GapMapping.id),
                )
                .join(GapMapping, GapMapping.regulatory_control_id == RegulatoryControl.id)
                .group_by(RegulatoryControl.framework, RegulatoryControl.severity, GapMapping.status)
            )
        ).all()

        bucket: dict[tuple[str, str], dict[str, int]] = {}
        for fw, sev, status, n in rows:
            key = (fw.value if hasattr(fw, "value") else str(fw),
                   sev.value if hasattr(sev, "value") else str(sev))
            d = bucket.setdefault(key, {"COVERED": 0, "PARTIAL": 0, "MISSING": 0})
            status_val = status.value if hasattr(status, "value") else str(status)
            d[status_val] = n

        items: list[dict[str, Any]] = []
        for (fw, sev), counts in sorted(bucket.items()):
            items.append(
                {
                    "framework": fw,
                    "severity": sev,
                    "covered": counts["COVERED"],
                    "partial": counts["PARTIAL"],
                    "missing": counts["MISSING"],
                }
            )

        covered = sum(i["covered"] for i in items)
        coverage = (covered / total_reg) if total_reg else 0.0
        return {
            "by_framework": items,
            "total_regulatory_controls": total_reg,
            "total_org_controls": total_org,
            "coverage_pct": round(coverage, 4),
        }


@mcp.resource("registry://gap-summary")
async def gap_summary_resource() -> str:
    """Live snapshot of organizational coverage vs. regulatory controls."""
    payload = await _compute_gap_summary()
    return json.dumps(payload, indent=2)
