"""Chat endpoints — list sessions, fetch one, and stream responses via SSE."""
from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.qa_agent import stream_answer
from app.api.deps import db_session
from app.db.models import ChatMessage, ChatSession
from app.logging_config import get_logger
from app.schemas.chat import ChatRequest, ChatSessionRead

router = APIRouter()
log = get_logger(__name__)


@router.post("/sessions", response_model=ChatSessionRead, status_code=201)
async def create_session(session: AsyncSession = Depends(db_session)) -> ChatSessionRead:
    chat_session = ChatSession(id=uuid4())
    session.add(chat_session)
    await session.commit()
    await session.refresh(chat_session)
    return ChatSessionRead.model_validate(chat_session)


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(session: AsyncSession = Depends(db_session)) -> list[ChatSessionRead]:
    rows = (
        await session.execute(select(ChatSession).order_by(ChatSession.created_at.desc()))
    ).scalars().all()
    return [ChatSessionRead.model_validate(r) for r in rows]


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
async def get_session(
    session_id: UUID, session: AsyncSession = Depends(db_session)
) -> ChatSessionRead:
    row = (
        await session.execute(select(ChatSession).where(ChatSession.id == session_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail="Session not found")
    return ChatSessionRead.model_validate(row)


@router.post("/stream")
async def stream(payload: ChatRequest, session: AsyncSession = Depends(db_session)):
    if payload.session_id is None:
        chat_session = ChatSession(id=uuid4())
        session.add(chat_session)
        await session.commit()
        await session.refresh(chat_session)
        session_id = chat_session.id
    else:
        existing = (
            await session.execute(
                select(ChatSession).where(ChatSession.id == payload.session_id)
            )
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(404, detail="Session not found")
        session_id = existing.id

    user_msg = ChatMessage(
        session_id=session_id, role="user", content=payload.question
    )
    session.add(user_msg)
    await session.commit()

    history_rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in history_rows[:-1]]

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            answer_buf: list[str] = []
            citations: list[dict] = []
            async for ev in stream_answer(question=payload.question, history=history):
                if ev.type == "token" and ev.text:
                    answer_buf.append(ev.text)
                    await queue.put({"event": "token", "data": ev.text})
                elif ev.type == "tool_use":
                    await queue.put(
                        {
                            "event": "tool_use",
                            "data": json.dumps({"tool": ev.tool, "input": ev.detail}),
                        }
                    )
                elif ev.type == "tool_result":
                    await queue.put(
                        {
                            "event": "tool_result",
                            "data": json.dumps({"tool": ev.tool, "preview": ev.detail}),
                        }
                    )
                elif ev.type == "final":
                    if ev.detail and "answer" in ev.detail and not answer_buf:
                        answer_buf.append(ev.detail["answer"])
                    citations = (ev.detail or {}).get("citations") or []
                    await queue.put({"event": "final", "data": json.dumps(ev.detail)})
            answer_text = "".join(answer_buf)
            async with type(session)(bind=session.bind) as persist_session:
                msg = ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=answer_text,
                    citations={"items": citations} if citations else None,
                )
                persist_session.add(msg)
                await persist_session.commit()
        except Exception as exc:  # noqa: BLE001
            log.error("chat.producer_failed", error=str(exc))
            await queue.put({"event": "error", "data": json.dumps({"error": str(exc)})})
        finally:
            await queue.put(None)

    task = asyncio.create_task(producer())

    async def sse_iter():
        yield {
            "event": "session",
            "data": json.dumps({"session_id": str(session_id)}),
        }
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(sse_iter())
