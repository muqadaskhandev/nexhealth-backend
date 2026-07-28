"""Communication templates — automated patient outreach sequences."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TemplateCategory(str, enum.Enum):
    APPOINTMENT_JOURNEY = "appointment_journey"
    DAILY = "daily"
    POST_APPOINTMENT = "post_appointment"
    PATIENT_BASED = "patient_based"
    MANUAL = "manual"


class TemplateStepKind(str, enum.Enum):
    TRIGGER = "trigger"
    EMAIL = "email"
    SMS = "sms"
    CONDITION = "condition"


class CommunicationTemplate(Base):
    __tablename__ = "communication_templates"
    __table_args__ = ()

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[TemplateCategory] = mapped_column(
        Enum(TemplateCategory, name="template_category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    multi_location: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Null = default template; set = customized sequence for that appointment type
    appointment_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointment_type_defs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    steps: Mapped[list["CommunicationTemplateStep"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="CommunicationTemplateStep.position",
    )


class CommunicationTemplateStep(Base):
    __tablename__ = "communication_template_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("communication_templates.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[TemplateStepKind] = mapped_column(
        Enum(TemplateStepKind, name="template_step_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    timing_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timing_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    condition_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    template: Mapped["CommunicationTemplate"] = relationship(back_populates="steps")


class TemplateConfiguration(Base):
    """Per-location sending hours for automated SMS templates."""

    __tablename__ = "template_configurations"
    __table_args__ = (UniqueConstraint("location_id", name="uq_template_config_location"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    sending_hours_start: Mapped[time] = mapped_column(Time, nullable=False, default=time(6, 0))
    sending_hours_end: Mapped[time] = mapped_column(Time, nullable=False, default=time(22, 0))
    customize_by_appointment_type: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    family_messaging_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    use_family_messaging_for_reminders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    family_messaging_age_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
