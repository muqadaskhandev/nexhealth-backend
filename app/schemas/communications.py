"""Schemas for communication templates and sending-hours config."""
from __future__ import annotations

import uuid
from datetime import datetime, time

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
