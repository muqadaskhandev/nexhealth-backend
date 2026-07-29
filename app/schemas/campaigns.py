"""Campaign API schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CampaignImage(BaseModel):
    id: str
    name: str = ""
    data_url: str = ""  # base64 data URL or remote URL
    alt: str = ""
    width: int | None = None
    height: int | None = None
    link_url: str = ""


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    practice_id: uuid.UUID
    location_ids: list[uuid.UUID] = Field(default_factory=list)
    title: str
    status: str
    is_favorite_template: bool
    source_campaign_id: uuid.UUID | None = None
    wizard_step: str
    audience_filters: dict[str, Any] = Field(default_factory=dict)
    selected_patient_ids: list[uuid.UUID] = Field(default_factory=list)
    excluded_patient_ids: list[uuid.UUID] = Field(default_factory=list)
    has_email: bool
    email_subject: str
    email_preview_text: str
    email_body: str
    email_images: list[CampaignImage] = Field(default_factory=list)
    has_sms: bool
    sms_body: str
    ai_prompt: str
    scheduled_at: datetime | None = None
    sent_at: datetime | None = None
    recipient_count: int
    created_by_user_id: uuid.UUID | None = None
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class CampaignCreateBlank(BaseModel):
    title: str = Field(default="Untitled campaign", max_length=300)
    location_ids: list[uuid.UUID] = Field(default_factory=list)


class CampaignCopyRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    location_ids: list[uuid.UUID] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    location_ids: list[uuid.UUID] | None = None
    wizard_step: str | None = None
    audience_filters: dict[str, Any] | None = None
    selected_patient_ids: list[uuid.UUID] | None = None
    excluded_patient_ids: list[uuid.UUID] | None = None
    has_email: bool | None = None
    email_subject: str | None = Field(default=None, max_length=300)
    email_preview_text: str | None = Field(default=None, max_length=500)
    email_body: str | None = None
    email_images: list[CampaignImage] | None = None
    has_sms: bool | None = None
    sms_body: str | None = Field(default=None, max_length=425)
    ai_prompt: str | None = None


class CampaignAudiencePatient(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    dob: str | None = None


class CampaignAudiencePreviewOut(BaseModel):
    total: int
    patients: list[CampaignAudiencePatient]


class CampaignGenerateAiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    channel: str = Field(default="email", pattern="^(email|sms)$")


class CampaignGenerateAiOut(BaseModel):
    subject: str = ""
    body: str
    preview_text: str = ""


class CampaignScheduleRequest(BaseModel):
    scheduled_at: datetime


class CampaignSendTestRequest(BaseModel):
    channel: str = Field(pattern="^(email|sms)$")
    to_email: str | None = None
    to_phone: str | None = None
