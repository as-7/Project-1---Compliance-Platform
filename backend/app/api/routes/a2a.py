"""A2A — Agent-to-Agent protocol surface for the Extraction Agent.

We follow the public A2A spec lightly:
  - GET /.well-known/agent.json     →  Agent Card
  - POST /a2a/tasks                  →  submit a task (sync, returns task)
  - GET /a2a/tasks/{task_id}         →  poll task state

The Agent Card describes capabilities, supported input MIME types, and the
endpoint to invoke. A simple A2A client lives at scripts/a2a_client_demo.py.
"""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.services.extraction_runner import run_pipeline

router = APIRouter()
log = get_logger(__name__)
_settings = get_settings()


# In-memory task store. Good enough for the demo; in prod you'd persist.
_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = asyncio.Lock()


@router.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    base = _settings.a2a_public_base_url.rstrip("/")
    return {
        "schemaVersion": "0.1",
        "name": "extraction-agent",
        "displayName": "Compliance Extraction Agent",
        "description": (
            "Plan-and-Execute agent that ingests a regulatory document and "
            "extracts compliance controls (SOC2 / ISO 27001 / GDPR / HIPAA) "
            "into a structured registry. Performs gap analysis against the "
            "organization's existing controls."
        ),
        "version": "0.1.0",
        "provider": {"organization": "Project 1 - Compliance", "url": base},
        "skills": [
            {
                "id": "extract_controls_from_document",
                "name": "Extract regulatory controls from a document",
                "description": (
                    "Accepts a PDF/text/markdown regulatory document, ingests "
                    "it into the vector store, runs the extraction pipeline, "
                    "and returns the structured controls + gap mappings."
                ),
                "inputModes": ["application/pdf", "text/plain", "text/markdown"],
                "outputModes": ["application/json"],
            }
        ],
        "endpoints": {
            "tasks": f"{base}/a2a/tasks",
            "task_status": f"{base}/a2a/tasks/{{task_id}}",
        },
        "authentication": {"schemes": []},
        "capabilities": {
            "streaming": False,
            "stateful": True,
            "fileUploads": True,
            "structuredOutput": True,
        },
    }


class TaskSubmitText(BaseModel):
    document_name: str
    text: str


@router.post("/a2a/tasks")
async def submit_task(
    background: BackgroundTasks,
    payload: TaskSubmitText | None = None,
    file: UploadFile | None = None,
) -> dict[str, Any]:
    """Accept either a JSON body with inline text OR a multipart upload."""
    if payload is None and file is None:
        raise HTTPException(400, detail="Provide JSON {document_name,text} or upload a file.")

    document_id = uuid4()
    _settings.uploads_dir.mkdir(parents=True, exist_ok=True)

    if file is not None:
        suffix = Path(file.filename or "").suffix.lower() or ".txt"
        target_path = _settings.uploads_dir / f"{document_id}{suffix}"
        with target_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        document_name = file.filename or f"a2a-{document_id}"
    else:
        target_path = _settings.uploads_dir / f"{document_id}.txt"
        target_path.write_text(payload.text, encoding="utf-8")  # type: ignore[union-attr]
        document_name = payload.document_name  # type: ignore[union-attr]

    async with SessionLocal() as session:
        doc = Document(
            id=document_id,
            name=document_name,
            source_path=str(target_path),
            status=DocumentStatus.UPLOADED,
        )
        session.add(doc)
        await session.commit()

    task_id = str(uuid4())
    async with _tasks_lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "skill": "extract_controls_from_document",
            "state": "running",
            "document_id": str(document_id),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "result": None,
            "error": None,
        }

    async def _run() -> None:
        try:
            await run_pipeline(document_id, target_path)
            async with SessionLocal() as session:
                from sqlalchemy import select  # local import to avoid cycle

                from app.db.models import RegulatoryControl

                rows = (
                    await session.execute(
                        select(RegulatoryControl).where(
                            RegulatoryControl.document_id == document_id
                        )
                    )
                ).scalars().all()
                controls = [
                    {
                        "id": str(r.id),
                        "title": r.title,
                        "framework": r.framework.value,
                        "severity": r.severity.value,
                        "risk_domain": r.risk_domain,
                    }
                    for r in rows
                ]
            async with _tasks_lock:
                _tasks[task_id].update(
                    {
                        "state": "completed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "result": {
                            "document_id": str(document_id),
                            "controls": controls,
                            "control_count": len(controls),
                        },
                    }
                )
        except Exception as exc:  # noqa: BLE001
            log.error("a2a.task_failed", task_id=task_id, error=str(exc))
            async with _tasks_lock:
                _tasks[task_id].update(
                    {
                        "state": "failed",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(exc),
                    }
                )

    background.add_task(_run)
    log.info("a2a.task_submitted", task_id=task_id, document_id=str(document_id))
    return {"task_id": task_id, "state": "running", "document_id": str(document_id)}


@router.get("/a2a/tasks/{task_id}")
async def task_status(task_id: str) -> dict[str, Any]:
    async with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(404, detail="Unknown task_id")
    return task
