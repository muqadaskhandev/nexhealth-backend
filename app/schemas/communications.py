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
    location_name: str = ""
    created_at: datetime
    updated_at: datetime
    steps: list[TemplateStepOut] = Field(default_factory=list)


class CommunicationTemplateUpdate(BaseModel):
    is_active: bool | None = None
    description: str | None = None


class TemplateConfigurationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    sending_hours_start: time
    sending_hours_end: time
    updated_at: datetime


class TemplateConfigurationUpdate(BaseModel):
    sending_hours_start: time
    sending_hours_end: time
