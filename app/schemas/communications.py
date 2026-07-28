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


class SavedResponseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    title: str
    body: str
    shared_location_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SavedResponseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=5000)
    shared_location_ids: list[uuid.UUID] = Field(default_factory=list)


class SavedResponseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=5000)
    shared_location_ids: list[uuid.UUID] | None = None


class ServiceHoursDay(BaseModel):
    day: int = Field(ge=0, le=6)  # 0=Sunday … 6=Saturday
    unavailable: bool = False
    start: str = "09:00"  # HH:MM
    end: str = "17:00"


class CustomDateHours(BaseModel):
    id: str
    date: str  # YYYY-MM-DD
    label: str = ""
    unavailable: bool = True
    start: str = "09:00"
    end: str = "17:00"


class OutOfOfficeSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    enabled: bool
    auto_reply_message: str
    service_hours: list[ServiceHoursDay]
    custom_dates: list[CustomDateHours]
    shared_location_ids: list[uuid.UUID] = Field(default_factory=list)
    updated_at: datetime
    # Informational: replies are limited to once every 30 minutes per conversation
    reply_throttle_minutes: int = 30


class OutOfOfficeSettingsUpdate(BaseModel):
    enabled: bool | None = None
    auto_reply_message: str | None = Field(default=None, max_length=320)
    service_hours: list[ServiceHoursDay] | None = None
    custom_dates: list[CustomDateHours] | None = None
    shared_location_ids: list[uuid.UUID] | None = None


class SmsRegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    status: str
    legal_business_name: str
    ein: str
    dba_name: str
    business_type: str
    business_address: str
    business_city: str
    business_state: str
    business_zip: str
    business_phone: str
    business_website: str
    auth_rep_name: str
    auth_rep_email: str
    auth_rep_phone: str
    auth_rep_title: str
    request_office_number_hosting: bool
    office_phone_number: str
    failure_reason: str
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    updated_at: datetime
    # True when patient SMS can be delivered for this location
    sms_enabled: bool = False


class SmsRegistrationUpdate(BaseModel):
    legal_business_name: str | None = Field(default=None, max_length=300)
    ein: str | None = Field(default=None, max_length=20)
    dba_name: str | None = Field(default=None, max_length=300)
    business_type: str | None = Field(default=None, max_length=100)
    business_address: str | None = Field(default=None, max_length=300)
    business_city: str | None = Field(default=None, max_length=100)
    business_state: str | None = Field(default=None, max_length=50)
    business_zip: str | None = Field(default=None, max_length=20)
    business_phone: str | None = Field(default=None, max_length=40)
    business_website: str | None = Field(default=None, max_length=300)
    auth_rep_name: str | None = Field(default=None, max_length=200)
    auth_rep_email: str | None = Field(default=None, max_length=200)
    auth_rep_phone: str | None = Field(default=None, max_length=40)
    auth_rep_title: str | None = Field(default=None, max_length=200)
    request_office_number_hosting: bool | None = None
    office_phone_number: str | None = Field(default=None, max_length=40)


class SmsRegistrationStatusUpdate(BaseModel):
    """Demo/admin: set review outcome (approve or fail)."""

    status: str = Field(pattern="^(approved|failed|in_progress)$")
    failure_reason: str | None = Field(default=None, max_length=2000)
