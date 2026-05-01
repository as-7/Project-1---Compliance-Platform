"""FastAPI entrypoint — wires routes, CORS, lifespan, MCP server bootstrap."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import a2a, chat, controls, documents, gaps, health
from app.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from app.mcp_servers.runner import start_mcp_servers, stop_mcp_servers
from sqlalchemy import update

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)


async def _recover_stuck_documents() -> None:
    """Mark any document still in INGESTING/EXTRACTING as FAILED on boot —
    the BackgroundTask that owned it died with the previous container."""
    async with SessionLocal() as session:
        stuck = (DocumentStatus.INGESTING, DocumentStatus.EXTRACTING, DocumentStatus.UPLOADED)
        result = await session.execute(
            update(Document)
            .where(Document.status.in_(stuck))
            .values(
                status=DocumentStatus.FAILED,
                error_message="Extraction interrupted by backend restart",
            )
        )
        await session.commit()
        if result.rowcount:
            log.warning("startup.recovered_stuck_documents", count=result.rowcount)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("app.startup", version=__version__)
    await _recover_stuck_documents()
    mcp_tasks = await start_mcp_servers()
    app.state.mcp_tasks = mcp_tasks
    try:
        yield
    finally:
        log.info("app.shutdown")
        await stop_mcp_servers(mcp_tasks)


app = FastAPI(
    title="Regulatory Compliance Intelligence Platform",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(controls.router, prefix="/api/controls", tags=["controls"])
app.include_router(gaps.router, prefix="/api/gaps", tags=["gaps"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(a2a.router, tags=["a2a"])
