"""After extraction, compute gap mappings between regulatory and org controls.

Approach: embed each regulatory control's title+description and search for the
nearest organization controls (cosine similarity over the same embedding model
used for RAG). A high-similarity match within the same risk_domain → COVERED.
A medium match or different-domain match → PARTIAL. No reasonable match →
MISSING.

Thresholds are intentionally conservative; we surface them in the response so
the frontend can show why a mapping was made.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    GapMapping,
    GapStatus,
    OrganizationControl,
    RegulatoryControl,
)
from app.logging_config import get_logger
from app.services.embeddings import embed_texts

log = get_logger(__name__)

COVERED_THRESHOLD = 0.62
PARTIAL_THRESHOLD = 0.45


@dataclass
class GapDecision:
    regulatory_control_id: UUID
    organization_control_id: UUID | None
    status: GapStatus
    similarity: float
    rationale: str


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b)  # already L2-normalized in embeddings.py


async def compute_gaps(
    session: AsyncSession,
    *,
    document_id: UUID | None = None,
) -> list[GapDecision]:
    reg_q = select(RegulatoryControl)
    if document_id:
        reg_q = reg_q.where(RegulatoryControl.document_id == document_id)
    reg_rows = (await session.execute(reg_q)).scalars().all()
    org_rows = (await session.execute(select(OrganizationControl))).scalars().all()

    if not reg_rows:
        return []
    if not org_rows:
        decisions = [
            GapDecision(
                regulatory_control_id=r.id,
                organization_control_id=None,
                status=GapStatus.MISSING,
                similarity=0.0,
                rationale="No organization controls defined.",
            )
            for r in reg_rows
        ]
        return decisions

    reg_texts = [f"{r.title}. {r.description}" for r in reg_rows]
    org_texts = [f"{o.title}. {o.description}" for o in org_rows]

    reg_vecs = np.array(await embed_texts(reg_texts))
    org_vecs = np.array(await embed_texts(org_texts))

    decisions: list[GapDecision] = []
    sims = reg_vecs @ org_vecs.T  # (R, O)
    for i, r in enumerate(reg_rows):
        j = int(sims[i].argmax())
        score = float(sims[i, j])
        org = org_rows[j]
        same_domain = (org.risk_domain.lower() == r.risk_domain.lower())
        if score >= COVERED_THRESHOLD and same_domain:
            status, rationale = (
                GapStatus.COVERED,
                f"Matches org control {org.code} in {org.risk_domain}.",
            )
        elif score >= PARTIAL_THRESHOLD:
            status, rationale = (
                GapStatus.PARTIAL,
                f"Partial overlap with {org.code} (similarity {score:.2f}, domain "
                f"{'match' if same_domain else 'mismatch'}).",
            )
            org_id_for_partial = org.id if same_domain or score >= 0.55 else None
            decisions.append(
                GapDecision(
                    regulatory_control_id=r.id,
                    organization_control_id=org_id_for_partial,
                    status=status,
                    similarity=score,
                    rationale=rationale,
                )
            )
            continue
        else:
            status, rationale = (
                GapStatus.MISSING,
                f"Closest org control {org.code} similarity only {score:.2f}.",
            )
            decisions.append(
                GapDecision(
                    regulatory_control_id=r.id,
                    organization_control_id=None,
                    status=status,
                    similarity=score,
                    rationale=rationale,
                )
            )
            continue

        decisions.append(
            GapDecision(
                regulatory_control_id=r.id,
                organization_control_id=org.id,
                status=status,
                similarity=score,
                rationale=rationale,
            )
        )

    log.info(
        "gap_analyzer.computed",
        regulatory=len(reg_rows),
        organization=len(org_rows),
        covered=sum(1 for d in decisions if d.status == GapStatus.COVERED),
        partial=sum(1 for d in decisions if d.status == GapStatus.PARTIAL),
        missing=sum(1 for d in decisions if d.status == GapStatus.MISSING),
    )
    return decisions


async def persist_decisions(
    session: AsyncSession, decisions: list[GapDecision]
) -> int:
    """Upsert all GapDecision rows."""
    n = 0
    for d in decisions:
        existing = (
            await session.execute(
                select(GapMapping).where(
                    GapMapping.regulatory_control_id == d.regulatory_control_id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = GapMapping(regulatory_control_id=d.regulatory_control_id)
            session.add(existing)
        existing.organization_control_id = d.organization_control_id
        existing.status = d.status
        existing.similarity = d.similarity
        existing.rationale = d.rationale
        n += 1
    await session.commit()
    return n


async def to_summary(decisions: list[GapDecision]) -> dict[str, Any]:
    return {
        "total": len(decisions),
        "covered": sum(1 for d in decisions if d.status == GapStatus.COVERED),
        "partial": sum(1 for d in decisions if d.status == GapStatus.PARTIAL),
        "missing": sum(1 for d in decisions if d.status == GapStatus.MISSING),
    }
