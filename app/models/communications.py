"""Communication templates — automated patient outreach sequences."""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
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


class TemplateAutomationSend(Base):
    """One automated send recorded on a template's History tab."""

    __tablename__ = "communication_template_sends"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("communication_templates.id", ondelete="CASCADE"),
        index=True,
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    patient_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    patient_dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    communication_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="sms")  # sms | email
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    appointment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewResponse(Base):
    """Patient 1–5 survey rating from Reviews (Google prompt vs internal feedback)."""

    __tablename__ = "review_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    google_prompted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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


class SavedResponse(Base):
    """Reusable message snippets for the Messages composer (Settings → Messages)."""

    __tablename__ = "saved_responses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Additional locations that can use this response (owner location always can)
    shared_location_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


DEFAULT_OOO_MESSAGE = (
    "Thank you for your text message. Our staff is unavailable and will reach out as soon as possible."
)

DEFAULT_SERVICE_HOURS = [
    {"day": 0, "unavailable": True, "start": "09:00", "end": "17:00"},   # Sunday
    {"day": 1, "unavailable": False, "start": "09:00", "end": "17:00"},  # Monday
    {"day": 2, "unavailable": False, "start": "09:00", "end": "17:00"},
    {"day": 3, "unavailable": False, "start": "09:00", "end": "17:00"},
    {"day": 4, "unavailable": False, "start": "09:00", "end": "17:00"},
    {"day": 5, "unavailable": False, "start": "09:00", "end": "17:00"},
    {"day": 6, "unavailable": True, "start": "09:00", "end": "17:00"},  # Saturday
]


class OutOfOfficeSettings(Base):
    """Per-location out-of-office auto-reply for inbound SMS (Settings → Messages)."""

    __tablename__ = "out_of_office_settings"
    __table_args__ = (UniqueConstraint("location_id", name="uq_ooo_settings_location"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_reply_message: Mapped[str] = mapped_column(
        String(320), nullable=False, default=DEFAULT_OOO_MESSAGE
    )
    service_hours: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    custom_dates: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    shared_location_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SmsRegistrationStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    APPROVED = "approved"
    FAILED = "failed"


class SmsRegistration(Base):
    """A2P / compliance business registration for sending patient SMS."""

    __tablename__ = "sms_registrations"
    __table_args__ = (UniqueConstraint("location_id", name="uq_sms_registration_location"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=SmsRegistrationStatus.NOT_STARTED.value
    )

    # Business details (must match tax documentation)
    legal_business_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    ein: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    dba_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    business_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    business_address: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    business_city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    business_state: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    business_zip: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    business_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    business_website: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    # Authorized representative (carrier may contact to verify)
    auth_rep_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    auth_rep_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    auth_rep_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    auth_rep_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Optional: request hosting office number for SMS
    request_office_number_hosting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    office_phone_number: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
