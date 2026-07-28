"""Schemas for communication templates and sending-hours config."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class TemplateStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    subtitle: str = ""
    body: str = ""
    subject: str = ""
    timing_value: int | None = None
    timing_unit: str | None = None
    condition_label: str | None = None
    position: int
    meta: dict = Field(default_factory=dict)


class TemplateStepUpdate(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    body: str | None = Field(default=None, max_length=5000)
    subject: str | None = Field(default=None, max_length=300)
    timing_value: int | None = None
    timing_unit: str | None = None
    condition_label: str | None = None


class TemplateStepCreate(BaseModel):
    kind: str = Field(pattern="^(email|sms)$")
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    subject: str = ""


class CommunicationTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    category: str
    is_active: bool
    total_sent: int
    recipients: int
    multi_location: bool
    appointment_type_id: uuid.UUID | None = None
    appointment_type_name: str = ""
    location_name: str = ""
    created_at: datetime
    updated_at: datetime
    steps: list[TemplateStepOut] = Field(default_factory=list)


class CommunicationTemplateUpdate(BaseModel):
    is_active: bool | None = None
    description: str | None = None


class TemplateVariantToggle(BaseModel):
    appointment_type_id: uuid.UUID
    enabled: bool


class TemplateAppointmentTypeStatus(BaseModel):
    appointment_type_id: uuid.UUID
    appointment_type_name: str
    enabled: bool
    variant_id: uuid.UUID | None = None


class TemplateConfigurationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    sending_hours_start: time
    sending_hours_end: time
    customize_by_appointment_type: bool = False
    family_messaging_enabled: bool = False
    use_family_messaging_for_reminders: bool = False
    family_messaging_age_limit: int | None = None
    updated_at: datetime


class TemplateConfigurationUpdate(BaseModel):
    sending_hours_start: time | None = None
    sending_hours_end: time | None = None
    customize_by_appointment_type: bool | None = None
    family_messaging_enabled: bool | None = None
    use_family_messaging_for_reminders: bool | None = None
    family_messaging_age_limit: int | None = None


# ── Message grouping ─────────────────────────────────────────────────────────

class MessageGroupingAppointmentIn(BaseModel):
    id: uuid.UUID | None = None
    patient_id: uuid.UUID
    patient_name: str
    patient_phone: str = ""
    guarantor_phone: str | None = None
    starts_at: datetime
    duration_minutes: int = 30
    appointment_type: str = ""
    journey_key: str | None = None


class MessageGroupingPreviewRequest(BaseModel):
    template_content: str = Field(
        default="{{INSERTCONFIRMAPPT}}",
        description="Reminder body used to detect consolidating smart commands",
    )
    family_messaging_enabled: bool | None = None
    use_family_messaging_for_reminders: bool | None = None
    appointment_journeys_enabled: bool | None = None
    appointments: list[MessageGroupingAppointmentIn] | None = None
    on_date: date | None = None  # when appointments omitted, load location appts for this day


class MessageGroupOut(BaseModel):
    mode: str
    recipient_phone: str
    recipient_label: str
    appointment_ids: list[str]
    listed_appointment_ids: list[str]
    patient_names: list[str]
    notes: list[str]
    confirm_applies_to_all: bool


class MessageGroupingPreviewOut(BaseModel):
    consolidation_supported: bool
    family_messaging_active: bool
    groups: list[MessageGroupOut]


class OtherTemplateDedupeRequest(BaseModel):
    template_slug: str
    content: str = ""
    phone: str
    patient_name: str
    last_sent_at: datetime | None = None
    mentioned_appointment_count: int = 1
    now: datetime | None = None


class OtherTemplateDedupeOut(BaseModel):
    should_send: bool
    reason: str
    confirm_applies_to_all_mentioned: bool


class TemplateAutomationHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    patient_id: uuid.UUID | None = None
    patient_name: str
    patient_dob: date | None = None
    communication_label: str
    channel: str
    sent_at: datetime
    provider_name: str
    appointment_at: datetime | None = None
