"""ORM models for documents, controls, gap mappings, and chat sessions."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Framework(str, enum.Enum):
    SOC2 = "SOC2"
    ISO27001 = "ISO27001"
    GDPR = "GDPR"
    HIPAA = "HIPAA"
    OTHER = "OTHER"


class Severity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    INGESTING = "INGESTING"
    EXTRACTING = "EXTRACTING"
    READY = "READY"
    FAILED = "FAILED"


class GapStatus(str, enum.Enum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.UPLOADED, nullable=False
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    controls: Mapped[list["RegulatoryControl"]] = relationship(
        back_populates="document", cascade="all,delete-orphan"
    )


class RegulatoryControl(Base):
    """A control extracted from a regulatory document."""

    __tablename__ = "regulatory_controls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    framework: Mapped[Framework] = mapped_column(Enum(Framework, name="framework"), nullable=False)
    risk_domain: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False)
    source_chunk_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="controls")
    gap_mappings: Mapped[list["GapMapping"]] = relationship(
        back_populates="regulatory_control", cascade="all,delete-orphan"
    )


class OrganizationControl(Base):
    """A control the organization already has in place."""

    __tablename__ = "organization_controls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_domain: Mapped[str] = mapped_column(String(128), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    gap_mappings: Mapped[list["GapMapping"]] = relationship(back_populates="organization_control")


class GapMapping(Base):
    """Connects a regulatory control to the org control(s) that cover it."""

    __tablename__ = "gap_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    regulatory_control_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regulatory_controls.id", ondelete="CASCADE"), nullable=False
    )
    organization_control_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_controls.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[GapStatus] = mapped_column(Enum(GapStatus, name="gap_status"), nullable=False)
    similarity: Mapped[float] = mapped_column(nullable=False, default=0.0)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    regulatory_control: Mapped[RegulatoryControl] = relationship(back_populates="gap_mappings")
    organization_control: Mapped[OrganizationControl | None] = relationship(back_populates="gap_mappings")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all,delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")
