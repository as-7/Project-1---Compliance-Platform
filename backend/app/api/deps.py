"""Common FastAPI dependencies."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session


async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for s in get_session():
        yield s


SessionDep = Depends(db_session)
