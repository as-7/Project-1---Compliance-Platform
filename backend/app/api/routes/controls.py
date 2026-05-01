"""Control inventory endpoints — regulatory + organization."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import (
    Framework,
    OrganizationControl,
    RegulatoryControl,
    Severity,
)
from app.schemas.controls import (
    OrganizationControlCreate,
    OrganizationControlRead,
    OrganizationControlUpdate,
    RegulatoryControlList,
    RegulatoryControlRead,
)

router = APIRouter()


@router.get("/regulatory", response_model=RegulatoryControlList)
async def list_regulatory_controls(
    framework: Framework | None = None,
    severity: Severity | None = None,
    risk_domain: str | None = None,
    document_id: UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(db_session),
) -> RegulatoryControlList:
    stmt = select(RegulatoryControl)
    if framework:
        stmt = stmt.where(RegulatoryControl.framework == framework)
    if severity:
        stmt = stmt.where(RegulatoryControl.severity == severity)
    if risk_domain:
        stmt = stmt.where(RegulatoryControl.risk_domain.ilike(f"%{risk_domain}%"))
    if document_id:
        stmt = stmt.where(RegulatoryControl.document_id == document_id)
    stmt = stmt.order_by(RegulatoryControl.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [RegulatoryControlRead.model_validate(r) for r in rows]
    return RegulatoryControlList(items=items, total=len(items))


@router.get("/organization", response_model=list[OrganizationControlRead])
async def list_organization_controls(
    session: AsyncSession = Depends(db_session),
) -> list[OrganizationControlRead]:
    rows = (
        await session.execute(
            select(OrganizationControl).order_by(OrganizationControl.code)
        )
    ).scalars().all()
    return [OrganizationControlRead.model_validate(r) for r in rows]


@router.post("/organization", response_model=OrganizationControlRead, status_code=201)
async def create_organization_control(
    payload: OrganizationControlCreate,
    session: AsyncSession = Depends(db_session),
) -> OrganizationControlRead:
    row = OrganizationControl(**payload.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return OrganizationControlRead.model_validate(row)


@router.patch("/organization/{control_id}", response_model=OrganizationControlRead)
async def update_organization_control(
    control_id: UUID,
    payload: OrganizationControlUpdate,
    session: AsyncSession = Depends(db_session),
) -> OrganizationControlRead:
    row = (
        await session.execute(
            select(OrganizationControl).where(OrganizationControl.id == control_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Organization control not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return OrganizationControlRead.model_validate(row)
