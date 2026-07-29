"""One-off email/SMS outreach campaigns."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAVORITE = "favorite"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=CampaignStatus.DRAFT.value)

    is_favorite_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )

    wizard_step: Mapped[str] = mapped_column(String(30), nullable=False, default="audience")
    audience_filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    selected_patient_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    excluded_patient_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    has_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    email_preview_text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    email_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email_images: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    has_sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sms_body: Mapped[str] = mapped_column(String(425), nullable=False, default="")

    ai_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CampaignSendLog(Base):
    __tablename__ = "campaign_send_logs"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "patient_id", "channel", name="uq_campaign_send_patient_channel"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    patient_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="sent")
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
