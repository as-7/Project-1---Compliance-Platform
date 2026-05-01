"""Run on container start: create tables if missing."""
from __future__ import annotations

import asyncio

from app.db.base import Base
from app.db import models  # noqa: F401  -- ensures models are registered
from app.db.session import engine
from app.logging_config import configure_logging, get_logger

log = get_logger(__name__)


async def main() -> None:
    configure_logging()
    log.info("db.init.start")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("db.init.done")


if __name__ == "__main__":
    asyncio.run(main())
