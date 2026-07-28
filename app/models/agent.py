"""Conversational intake agent models (Milestone 3)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentSessionStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    EMERGENCY_STOPPED = "emergency_stopped"


class AgentTurnRole(str, enum.Enum):
    PATIENT = "patient"
    AGENT = "agent"
    SYSTEM = "system"


class AgentAnswerStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class AgentReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentSession(Base):
    """One conversational intake run for a patient + form request."""

    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    form_access_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_access_tokens.id", ondelete="CASCADE"), index=True
    )
    form_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_requests.id", ondelete="CASCADE"), index=True
    )
    form_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_templates.id", ondelete="CASCADE")
    )
    status: Mapped[AgentSessionStatus] = mapped_column(
        Enum(AgentSessionStatus, name="agent_session_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AgentSessionStatus.IN_PROGRESS,
    )
    current_field_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    draft_answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentTurn(Base):
    """One message in the agent conversation transcript."""

    __tablename__ = "agent_turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[AgentTurnRole] = mapped_column(
        Enum(AgentTurnRole, name="agent_turn_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    field_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentAnswer(Base):
    """Structured field answer with raw patient text vs AI-extracted value."""

    __tablename__ = "agent_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    field_id: Mapped[str] = mapped_column(String(80), nullable=False)
    field_label: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    sync_target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_patient_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parsed_value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ai_generated: Mapped[bool] = mapped_column(nullable=False, default=True)
    status: Mapped[AgentAnswerStatus] = mapped_column(
        Enum(AgentAnswerStatus, name="agent_answer_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AgentAnswerStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentReview(Base):
    """Staff review of an agent-completed intake."""

    __tablename__ = "agent_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    form_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("form_submissions.id", ondelete="SET NULL"), nullable=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[AgentReviewStatus] = mapped_column(
        Enum(AgentReviewStatus, name="agent_review_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AgentReviewStatus.PENDING,
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentAuditLog(Base):
    """Non-PHI audit trail for agent events (field ids, event types — no message bodies)."""

    __tablename__ = "agent_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
