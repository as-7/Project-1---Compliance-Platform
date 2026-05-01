from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import Citation


class ChatMessageRead(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    citations: list[Citation] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionRead(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    messages: list[ChatMessageRead] = []

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    session_id: UUID | None = None
    question: str
