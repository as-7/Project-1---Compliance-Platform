"""Seed organization controls + the three regulatory documents.

Idempotent: re-running won't duplicate rows. The seed runs at container
startup (see docker-compose.yml). Document extraction kicks off in the
background per uploaded document, so the first call to /api/controls/regulatory
may return an empty list while extraction is still in flight.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Document, DocumentStatus, OrganizationControl
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.extraction_runner import run_pipeline

log = get_logger(__name__)

_settings = get_settings()
_DATA_DIR = Path(__file__).parent / "data"


async def _seed_org_controls() -> int:
    payload = json.loads((_DATA_DIR / "organization_controls.json").read_text())
    inserted = 0
    async with SessionLocal() as session:
        for entry in payload:
            existing = (
                await session.execute(
                    select(OrganizationControl).where(
                        OrganizationControl.code == entry["code"]
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(OrganizationControl(**entry))
                inserted += 1
        await session.commit()
    log.info("seed.org_controls", inserted=inserted, total=len(payload))
    return inserted


async def _seed_documents() -> list[tuple[str, Path]]:
    """Copy seed regulatory excerpts into uploads/, register them, return tasks."""
    _settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    seeds = [
        ("SOC 2 Trust Services Criteria — Excerpt", _DATA_DIR / "soc2_excerpt.txt"),
        ("GDPR — Selected Articles Excerpt", _DATA_DIR / "gdpr_excerpt.txt"),
        ("HIPAA Security Rule — Excerpt", _DATA_DIR / "hipaa_excerpt.txt"),
    ]
    pending: list[tuple[str, Path]] = []
    async with SessionLocal() as session:
        for name, src in seeds:
            existing = (
                await session.execute(select(Document).where(Document.name == name))
            ).scalar_one_or_none()
            if existing is not None:
                continue
            doc_id = uuid4()
            target = _settings.uploads_dir / f"{doc_id}.txt"
            shutil.copyfile(src, target)
            session.add(
                Document(
                    id=doc_id,
                    name=name,
                    source_path=str(target),
                    status=DocumentStatus.UPLOADED,
                )
            )
            pending.append((str(doc_id), target))
        await session.commit()
    return pending


async def main() -> None:
    configure_logging()
    log.info("seed.start")
    await _seed_org_controls()
    pending = await _seed_documents()
    if not pending:
        log.info("seed.docs.already_present")
        return

    # Run pipelines sequentially so we don't overload the embedding model on
    # a tiny dev box. Errors are logged but don't abort startup.
    for doc_id, path in pending:
        try:
            from uuid import UUID

            await run_pipeline(UUID(doc_id), path)
        except Exception as exc:  # noqa: BLE001
            log.error("seed.pipeline_failed", document_id=doc_id, error=str(exc))
    log.info("seed.done")


if __name__ == "__main__":
    asyncio.run(main())
