"""Gap analysis endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import (
    Framework,
    GapMapping,
    GapStatus,
    OrganizationControl,
    RegulatoryControl,
    Severity,
)
from app.schemas.controls import (
    GapMappingRead,
    GapSummary,
    GapSummaryItem,
)
from app.services.gap_analyzer import compute_gaps, persist_decisions

router = APIRouter()


@router.get("", response_model=list[GapMappingRead])
async def list_gap_mappings(
    document_id: UUID | None = Query(None),
    status: GapStatus | None = Query(None),
    session: AsyncSession = Depends(db_session),
) -> list[GapMappingRead]:
    stmt = select(GapMapping).join(
        RegulatoryControl, GapMapping.regulatory_control_id == RegulatoryControl.id
    )
    if document_id:
        stmt = stmt.where(RegulatoryControl.document_id == document_id)
    if status:
        stmt = stmt.where(GapMapping.status == status)
    rows = (await session.execute(stmt)).scalars().all()
    return [GapMappingRead.model_validate(r) for r in rows]


@router.post("/recompute", response_model=GapSummary)
async def recompute_gaps(
    document_id: UUID | None = Query(None),
    session: AsyncSession = Depends(db_session),
) -> GapSummary:
    decisions = await compute_gaps(session, document_id=document_id)
    await persist_decisions(session, decisions)
    return await summary(session)


@router.get("/summary", response_model=GapSummary)
async def summary(session: AsyncSession = Depends(db_session)) -> GapSummary:
    total_reg = (
        await session.execute(select(func.count(RegulatoryControl.id)))
    ).scalar_one()
    total_org = (
        await session.execute(select(func.count(OrganizationControl.id)))
    ).scalar_one()

    rows = (
        await session.execute(
            select(
                RegulatoryControl.framework,
                RegulatoryControl.severity,
                GapMapping.status,
                func.count(GapMapping.id),
            )
            .join(GapMapping, GapMapping.regulatory_control_id == RegulatoryControl.id)
            .group_by(
                RegulatoryControl.framework,
                RegulatoryControl.severity,
                GapMapping.status,
            )
        )
    ).all()

    bucket: dict[tuple[Framework, Severity], dict[GapStatus, int]] = {}
    for fw, sev, st, n in rows:
        d = bucket.setdefault(
            (fw, sev),
            {GapStatus.COVERED: 0, GapStatus.PARTIAL: 0, GapStatus.MISSING: 0},
        )
        d[st] = n

    items = [
        GapSummaryItem(
            framework=fw,
            severity=sev,
            covered=counts[GapStatus.COVERED],
            partial=counts[GapStatus.PARTIAL],
            missing=counts[GapStatus.MISSING],
        )
        for (fw, sev), counts in sorted(
            bucket.items(), key=lambda kv: (kv[0][0].value, kv[0][1].value)
        )
    ]
    covered = sum(i.covered for i in items)
    coverage = (covered / total_reg) if total_reg else 0.0
    return GapSummary(
        by_framework=items,
        total_regulatory_controls=total_reg,
        total_org_controls=total_org,
        coverage_pct=round(coverage, 4),
    )
